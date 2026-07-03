"""Tests for the FastAPI endpoints in `app.main`.

This module contains small, deterministic tests that exercise the
two HTTP endpoints provided by the example RAG app:

- POST `/upload`: accepts a file upload, extracts text, chunks it,
  computes embeddings, and builds an in-memory `VectorStore`.
- POST `/ask`: accepts a question and returns an answer based on the
  current in-memory index.

To keep these tests fast and hermetic we use `fastapi.testclient.TestClient`
and `pytest`'s `monkeypatch` fixture to replace expensive or networked
operations (text extraction, embedding, and LLM calls) with small,
predictable fakes.

Run the tests with:

	python -m pytest tests/test_api.py -q

"""

import io

import pytest
from fastapi.testclient import TestClient

from app import feedback_store, main, slo_metrics


# TestClient wraps the FastAPI app and lets us call endpoints synchronously
client = TestClient(main.app)


def setup_function():
    """Reset module-level state before each test.

    The application stores a `vector_store` at module scope when a document
    is uploaded; tests must clear it to avoid cross-test interference.
    """

    main.vector_store = None
    slo_metrics.reset()
    feedback_store.reset()


def test_ask_without_upload():
    """When no document has been uploaded, `/ask` should return an
    informative message rather than attempting retrieval or generation.
    """

    main.vector_store = None
    resp = client.post("/ask", json={"question": "Hello"})
    assert resp.status_code == 200
    assert resp.json() == {"answer": "No document uploaded yet."}


def test_upload_and_ask(monkeypatch):
    """Smoke-test the upload -> ask flow using monkeypatched helpers.

    We replace the real `extract_text`, `chunk_text`, `embed_text`,
    `VectorStore` and `generate_answer` with tiny fakes so the test is
    deterministic and fast. The test verifies that `/upload` returns a
    success message and that `/ask` later returns the expected fake
    answer produced by the patched `generate_answer` function.
    """

    # --- Fake implementations used in this test ---
    def fake_extract_text(path):
        return "This is a small test document."

    def fake_chunk_text(text):
        # Single chunk containing the entire test document
        return [text]

    def fake_embed_text(chunks):
        # Return a small fixed-dimension vector per chunk
        return [[0.0, 0.0, 0.0, 0.0] for _ in chunks]

    class FakeVectorStore:
        def __init__(self, dim):
            self.texts = []
            self.clear_called = False

        def clear(self, source_document=None, filters=None):
            self.clear_called = True
            self.texts = []

        def add(self, embeddings, texts, source_document=None, metadata_list=None):
            self.texts.extend(texts)

        def search(self, query_embedding, top_k=5, source_document=None, filters=None):
            return self.texts[:top_k]

    def fake_generate_answer(
        question,
        vector_store,
        tenant_id=None,
        collection_id=None,
        document_id=None,
        document_date=None,
        author=None,
        tag=None,
        source_system=None,
    ):
        return f"FAKE ANSWER: {question}"

    # Patch functions and classes used by the endpoint handlers
    monkeypatch.setattr(main, "extract_text", fake_extract_text)
    monkeypatch.setattr(main, "chunk_text", fake_chunk_text)
    monkeypatch.setattr(main, "embed_text", fake_embed_text)
    monkeypatch.setattr(main, "VectorStore", FakeVectorStore)
    monkeypatch.setattr(main, "generate_answer", fake_generate_answer)

    # Upload a dummy file (actual content ignored by fakes)
    files = {"file": ("doc.txt", b"ignored", "text/plain")}
    r = client.post("/upload", files=files)
    assert r.status_code == 200
    assert r.json().get("message") == "Document processed successfully"
    assert main.vector_store.clear_called is True

    # Ask a question and verify the fake generator is invoked
    r2 = client.post("/ask", json={"question": "What is this?"})
    assert r2.status_code == 200
    assert r2.json().get("answer") == "FAKE ANSWER: What is this?"


def test_upload_large_file_is_queued_async(monkeypatch):
    def fake_extract_text(path):
        return "This is a larger test document that should be queued."

    def fake_chunk_text(text):
        return [text]

    def fake_embed_text(chunks):
        return [[0.0, 0.0, 0.0, 0.0] for _ in chunks]

    class FakeVectorStore:
        def __init__(self, dim):
            self.texts = []

        def clear(self, source_document=None, filters=None):
            self.texts = []

        def add(self, embeddings, texts, source_document=None, metadata_list=None):
            self.texts.extend(texts)

        def search(self, query_embedding, top_k=5, source_document=None, filters=None):
            return self.texts[:top_k]

    monkeypatch.setattr(main, "extract_text", fake_extract_text)
    monkeypatch.setattr(main, "chunk_text", fake_chunk_text)
    monkeypatch.setattr(main, "embed_text", fake_embed_text)
    monkeypatch.setattr(main, "VectorStore", FakeVectorStore)
    monkeypatch.setattr(main.config, "ASYNC_INGESTION_MIN_BYTES", 1)
    monkeypatch.setattr(main, "enqueue_job", lambda handler, *args, **kwargs: "job-123")

    files = {"file": ("big-doc.txt", b"x" * 1024, "text/plain")}
    r = client.post("/upload", files=files)

    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "queued"
    assert payload["job_id"] == "job-123"


def test_upload_unsupported_file_type_returns_server_error():
    files = {"file": ("data.bin", b"\x00\x01", "application/octet-stream")}
    with pytest.raises(ValueError, match="Unsupported file type"):
        client.post("/upload", files=files)


def test_ingestion_job_status_endpoint(monkeypatch):
    monkeypatch.setattr(main, "get_job", lambda job_id: {"job_id": job_id, "status": "queued"})

    resp = client.get("/ingestion-jobs/job-123")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-123"


def test_metrics_endpoint_reports_slo_snapshot():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    payload = resp.json()
    assert "p95_latency_seconds" in payload
    assert "error_rate" in payload
    assert "throughput_rps" in payload
    assert "avg_retrieval_hit_quality" in payload


def test_feedback_capture_and_summary():
    good = {
        "question": "What is the project scope?",
        "answer": "It includes ingestion, retrieval, and QA.",
        "rating": "up",
        "collection_id": "project-alpha",
    }
    bad = {
        "question": "Who authored the policy?",
        "answer": "Unknown.",
        "rating": "down",
        "correction": "The author is Getinet Aga.",
        "collection_id": "project-alpha",
        "author": "Getinet Aga",
    }

    r1 = client.post("/feedback", json=good)
    r2 = client.post("/feedback", json=bad)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["status"] == "recorded"
    assert r2.json()["status"] == "recorded"

    summary = client.get("/feedback/summary")
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["total_feedback"] == 2
    assert payload["thumbs_up"] == 1
    assert payload["thumbs_down"] == 1
    assert payload["corrections_count"] == 1
    assert payload["recent_corrections"][0]["correction"] == "The author is Getinet Aga."


def test_feedback_rejects_invalid_rating():
    resp = client.post(
        "/feedback",
        json={
            "question": "Q",
            "answer": "A",
            "rating": "maybe",
        },
    )
    assert resp.status_code == 422


def test_ask_passes_advanced_retrieval_filters(monkeypatch):
    class FakeVectorStore:
        pass

    main.vector_store = FakeVectorStore()

    captured = {}

    def fake_generate_answer(
        question,
        vector_store,
        tenant_id=None,
        collection_id=None,
        document_id=None,
        document_date=None,
        author=None,
        tag=None,
        source_system=None,
    ):
        captured["question"] = question
        captured["tenant_id"] = tenant_id
        captured["collection_id"] = collection_id
        captured["document_id"] = document_id
        captured["document_date"] = document_date
        captured["author"] = author
        captured["tag"] = tag
        captured["source_system"] = source_system
        return "Filtered answer"

    monkeypatch.setattr(main, "generate_answer", fake_generate_answer)

    payload = {
        "question": "What did the source say?",
        "tenant_id": "tenant-a",
        "collection_id": "project-alpha",
        "document_id": "doc-01",
        "document_date": "2026-07-01",
        "author": "Getinet Aga",
        "tag": "release-notes",
        "source_system": "confluence",
    }
    resp = client.post("/ask", json=payload)
    assert resp.status_code == 200
    assert resp.json()["answer"] == "Filtered answer"
    assert captured == payload