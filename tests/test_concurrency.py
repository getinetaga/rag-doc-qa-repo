"""Concurrent answer safety and a small simulated-provider load measurement."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import config, main, rag, slo_metrics, vector_store


def headers(keys, name="writer"):
    return {"Authorization": f"Bearer {keys[name]}"}


def _scoped_code_store(monkeypatch):
    store = vector_store.VectorStore(2, backend="faiss")
    for tenant, project, code in (
        ("tenant-a", "project-a", "ALPHA"),
        ("tenant-b", "project-b", "BETA"),
    ):
        store.add(
            [[1.0, 0.0]], [f"[Section 1] The project code is {code}."],
            source_document="doc",
            metadata_list=[{"tenant_id": tenant, "collection_id": project, "document_id": "doc"}],
        )
    monkeypatch.setattr(main, "vector_store", store)
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(config, "RETRIEVAL_SERVICE_URL", "")
    monkeypatch.setattr(config, "INFERENCE_SERVICE_URL", "")
    return store


def _code_answer(prompt):
    codes = [code for code in ("ALPHA", "BETA", "GAMMA") if f"The project code is {code}." in prompt]
    assert len(codes) == 1, "A provider prompt must contain only the requested project's context."
    return f"The project code is {codes[0]}."


def test_questions_generate_concurrently_without_cross_project_context(secured, monkeypatch):
    client, keys, _, _ = secured
    _scoped_code_store(monkeypatch)
    monkeypatch.setattr(main, "_answer_slots", threading.BoundedSemaphore(2))
    rendezvous = threading.Barrier(2)

    def provider(prompt):
        rendezvous.wait(timeout=5)
        return _code_answer(prompt)

    monkeypatch.setattr(rag, "_generate_from_prompt", provider)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(client.post, "/ask", headers=headers(keys, name), json={
                "question": "What is the project code?", "document_id": "doc",
            })
            for name in ("writer", "other")
        ]
        responses = [future.result(timeout=10) for future in futures]
    assert [response.status_code for response in responses] == [200, 200]
    assert "ALPHA" in responses[0].json()["answer"]
    assert "BETA" not in responses[0].json()["answer"]
    assert "BETA" in responses[1].json()["answer"]
    assert "ALPHA" not in responses[1].json()["answer"]


def test_answer_overload_rejects_without_blocking_other_endpoints(secured, monkeypatch):
    client, keys, _, _ = secured
    monkeypatch.setattr(main, "vector_store", object())
    monkeypatch.setattr(main, "_answer_slots", threading.BoundedSemaphore(1))
    started, release = threading.Event(), threading.Event()

    def generate(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5)
        return "Permitted answer"

    monkeypatch.setattr(main, "generate_answer", generate)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(client.post, "/ask", headers=headers(keys), json={"question": "Q"})
        try:
            assert started.wait(timeout=5)
            overloaded = client.post("/ask", headers=headers(keys), json={"question": "Q"})
            assert overloaded.status_code == 503
            assert overloaded.headers["retry-after"] == "1"
            assert "capacity" in overloaded.json()["detail"]
            assert client.get("/session", headers=headers(keys)).status_code == 200
            assert client.post("/ask", json={"question": "Q"}).status_code == 401
            assert client.post("/ask", headers=headers(keys), json={
                "question": "Q", "tenant_id": "tenant-b", "collection_id": "project-b",
            }).status_code == 403
        finally:
            release.set()
        assert first.result(timeout=5).status_code == 200
    assert client.post("/ask", headers=headers(keys), json={"question": "Q"}).status_code == 200


@pytest.mark.parametrize("failure", ["exception", "revocation"])
def test_answer_slot_released_after_failure(secured, monkeypatch, failure):
    client, keys, policy, path = secured
    monkeypatch.setattr(main, "vector_store", object())
    monkeypatch.setattr(main, "_answer_slots", threading.BoundedSemaphore(1))
    original_policy = json.dumps(policy)

    def generate(*args, **kwargs):
        if failure == "exception":
            raise RuntimeError("Simulated generation failure")
        policy["users"] = [user for user in policy["users"] if user["user_id"] != "writer"]
        path.write_text(json.dumps(policy), encoding="utf-8")
        return "Must not be disclosed"

    monkeypatch.setattr(main, "generate_answer", generate)
    if failure == "exception":
        with pytest.raises(RuntimeError, match="Simulated generation"):
            client.post("/ask", headers=headers(keys), json={"question": "Q"})
    else:
        response = client.post("/ask", headers=headers(keys), json={"question": "Q"})
        assert response.status_code == 403
        assert "Must not be disclosed" not in response.text
    path.write_text(original_policy, encoding="utf-8")
    monkeypatch.setattr(main, "generate_answer", lambda *args, **kwargs: "Recovered")
    assert client.post("/ask", headers=headers(keys), json={"question": "Q"}).status_code == 200


def test_replacement_proceeds_during_generation_and_invalidates_old_snapshot(secured, monkeypatch):
    client, keys, _, _ = secured
    store = _scoped_code_store(monkeypatch)
    monkeypatch.setattr(main, "chunk_text", lambda text: [text])
    monkeypatch.setattr(main, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    started, release = threading.Event(), threading.Event()

    def provider(prompt):
        if "The project code is ALPHA." in prompt:
            started.set()
            assert release.wait(timeout=5)
        return _code_answer(prompt)

    monkeypatch.setattr(rag, "_generate_from_prompt", provider)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, "/ask", headers=headers(keys), json={
            "question": "What is the project code?", "document_id": "doc",
        })
        try:
            assert started.wait(timeout=5)
            replacement = executor.submit(
                main._index_text_content,
                "[Section 1] The project code is GAMMA.", "tenant-a", "project-a",
                "doc", "doc.txt", owner_id="writer",
            )
            assert replacement.result(timeout=3)["chunks"] == 1
        finally:
            release.set()
        original = first.result(timeout=5)
    assert original.status_code == 200
    assert "ALPHA" in original.json()["answer"]
    updated = client.post("/ask", headers=headers(keys), json={
        "question": "What is the project code?", "document_id": "doc",
    })
    assert "GAMMA" in updated.json()["answer"]
    assert "ALPHA" not in updated.json()["answer"]
    other = client.post("/ask", headers=headers(keys, "other"), json={
        "question": "What is the project code?", "document_id": "doc",
    })
    assert "BETA" in other.json()["answer"]
    assert store.revision == 3


def test_cache_generation_tracks_replacement_during_embedding(secured, monkeypatch):
    client, keys, _, _ = secured
    store = _scoped_code_store(monkeypatch)
    started, release = threading.Event(), threading.Event()

    def embed(texts):
        started.set()
        assert release.wait(timeout=5)
        return [[1.0, 0.0]]

    monkeypatch.setattr(rag, "embed_text", embed)
    monkeypatch.setattr(rag, "_generate_from_prompt", _code_answer)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, "/ask", headers=headers(keys), json={
            "question": "What is the project code?", "document_id": "doc",
        })
        try:
            assert started.wait(timeout=5)
            replacement = executor.submit(
                store.replace, [[1.0, 0.0]], ["[Section 1] The project code is GAMMA."],
                source_document="doc",
                metadata_list=[{"tenant_id": "tenant-a", "collection_id": "project-a", "document_id": "doc"}],
                filters={"tenant_id": "tenant-a", "collection_id": "project-a", "document_id": "doc"},
            )
            replacement.result(timeout=3)
        finally:
            release.set()
        assert "GAMMA" in first.result(timeout=5).json()["answer"]
    monkeypatch.setattr(rag, "embed_text", lambda texts: pytest.fail("Expected the new-revision response cache"))
    response = client.post("/ask", headers=headers(keys), json={
        "question": "What is the project code?", "document_id": "doc",
    })
    assert response.status_code == 200
    assert "GAMMA" in response.json()["answer"]


def test_concurrency_load_with_simulated_provider(secured, monkeypatch):
    client, keys, _, _ = secured
    _scoped_code_store(monkeypatch)
    monkeypatch.setattr(rag, "_can_cache", lambda store: False)
    results = []
    for concurrency in (1, 4):
        monkeypatch.setattr(main, "_answer_slots", threading.BoundedSemaphore(concurrency))
        rendezvous = threading.Barrier(concurrency)
        counter_lock = threading.Lock()
        active, peak = 0, 0

        def provider(prompt):
            nonlocal active, peak
            with counter_lock:
                active += 1
                peak = max(peak, active)
            try:
                rendezvous.wait(timeout=5)
                time.sleep(0.1)
                return _code_answer(prompt)
            finally:
                with counter_lock:
                    active -= 1

        monkeypatch.setattr(rag, "_generate_from_prompt", provider)

        def request(index):
            name, code = ("writer", "ALPHA") if index % 2 == 0 else ("other", "BETA")
            started = time.perf_counter()
            response = client.post("/ask", headers=headers(keys, name), json={
                "question": "What is the project code?", "document_id": "doc",
            })
            assert response.status_code == 200
            assert code in response.json()["answer"]
            return time.perf_counter() - started

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            latencies = list(executor.map(request, range(12)))
        elapsed = time.perf_counter() - started
        assert peak == concurrency
        results.append({
            "requests": 12, "concurrency": concurrency, "peak_generations": peak,
            "wall_seconds": round(elapsed, 3), "requests_per_second": round(12 / elapsed, 2),
            "p95_seconds": round(slo_metrics._percentile(latencies, 0.95), 3),
            "simulated_provider_seconds": 0.1,
        })
    print("\nSIMULATED_PROVIDER_LOAD " + json.dumps(results))


def test_concurrent_openai_initialization_uses_one_client_and_bounded_timeouts(monkeypatch):
    created = []
    client = object()
    rendezvous = threading.Barrier(4)

    def construct(**kwargs):
        created.append(kwargs)
        time.sleep(0.02)
        return client

    def initialize():
        rendezvous.wait(timeout=5)
        return rag._get_openai_client()

    monkeypatch.setattr(rag, "_openai_client", None)
    monkeypatch.setattr(rag, "OpenAI", construct)
    monkeypatch.setattr(config, "LLM_REQUEST_TIMEOUT_SECONDS", 17)
    with ThreadPoolExecutor(max_workers=4) as executor:
        clients = list(executor.map(lambda _: initialize(), range(4)))
    assert all(result is client for result in clients)
    assert len(created) == 1
    assert created[0]["timeout"] == 17
    assert created[0]["max_retries"] == 0


def test_http_providers_and_internal_services_use_configured_timeout(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"generated_text": "Answer"}

    def post(url, **kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr(rag.requests, "post", post)
    monkeypatch.setattr(config, "LLM_REQUEST_TIMEOUT_SECONDS", 17)
    monkeypatch.setattr(config, "HUGGINGFACE_API_KEY", "unit-test-provider-key")
    monkeypatch.setattr(config, "RAG_SERVICE_TOKEN", "unit-test-service-token-" + "x" * 32)
    assert rag._call_huggingface("test-model", "Prompt") == "Answer"
    assert rag._post_json("http://internal/generate", {"prompt": "Prompt"}) == {"generated_text": "Answer"}
    assert [call["timeout"] for call in calls] == [17, 17]
