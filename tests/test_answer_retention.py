import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from app import answer_store, config, main
from app.vector_store import VectorStore


@pytest.fixture
def retained(secured, tmp_path, monkeypatch):
    client, keys, policy, policy_path = secured
    path = tmp_path / "answers.sqlite3"
    monkeypatch.setattr(config, "ANSWER_RETENTION_DB", str(path))
    monkeypatch.setattr(config, "ANSWER_RETENTION_DAYS", 30)
    monkeypatch.setattr(config, "RETRIEVAL_SERVICE_URL", "")
    store = VectorStore(2, backend="faiss")
    store.add([[1, 0]], ["protected evidence"], metadatas=[{
        "tenant_id": "tenant-a", "collection_id": "project-a", "document_id": "source",
    }])
    monkeypatch.setattr(main, "vector_store", store)
    monkeypatch.setattr(main, "generate_answer", lambda *args, **kwargs: "protected answer payload")
    monkeypatch.setattr(main, "classify_question_domain", lambda question: "general")
    return client, keys, policy, policy_path, path, store


def headers(keys, name="writer"):
    return {"Authorization": f"Bearer {keys[name]}"}


def save(client, keys, **extra):
    return client.post("/ask", json={
        "question": "protected question payload", "retain_answer": True, **extra,
    }, headers=headers(keys))


def test_opt_in_owner_only_and_metadata_listing(retained):
    client, keys, _, _, path, _ = retained
    response = client.post("/ask", json={"question": "unsaved"}, headers=headers(keys))
    assert response.status_code == 200
    assert not path.exists()
    response = save(client, keys)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    answer_id = response.json()["answer_id"]
    result = client.get(f"/answers/{answer_id}", headers=headers(keys))
    assert result.json()["answer"] == "protected answer payload"
    assert result.json()["question"] == "protected question payload"
    assert result.json()["expires_at"] - result.json()["created_at"] == 30 * 86400
    for name in ("reader", "other", "admin"):
        assert client.get(f"/answers/{answer_id}", headers=headers(keys, name)).status_code == 404
        assert client.delete(f"/answers/{answer_id}", headers=headers(keys, name)).status_code == 404
    listing = client.get("/answers", headers=headers(keys)).json()
    assert len(listing) == 1
    assert set(listing[0]) == {"id", "created_at", "expires_at", "status"}
    assert client.get("/answers", headers=headers(keys, "reader")).json() == []
    assert client.get(f"/answers/{answer_id}").status_code == 401


def assert_scrubbed(path):
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT question, answer, status FROM answers").fetchone() == (
            None, None, "redacted",
        )
    assert b"protected answer payload" not in path.read_bytes()
    assert b"protected question payload" not in path.read_bytes()


@pytest.mark.parametrize("change", ["index", "replacement", "restart", "policy"])
def test_invalidation_scrubs_entire_payload_permanently(retained, monkeypatch, change):
    client, keys, policy, policy_path, path, store = retained
    answer_id = save(client, keys).json()["answer_id"]
    if change == "index":
        store.clear()
    elif change == "replacement":
        store.replace([[0, 1]], ["replacement"], source_document="source",
                      metadata_list=[{"tenant_id": "tenant-a", "collection_id": "project-a"}],
                      filters={"tenant_id": "tenant-a", "collection_id": "project-a"})
    elif change == "restart":
        monkeypatch.setattr(main, "vector_store", VectorStore(2, backend="faiss"))
    else:
        policy["users"][1]["roles"] = ["ingest"]
        policy_path.write_text(json.dumps(policy))
    result = client.get(f"/answers/{answer_id}", headers=headers(keys))
    assert result.status_code == 410
    assert "protected" not in result.text
    assert_scrubbed(path)
    # Even restoring the old index namespace cannot restore scrubbed text.
    monkeypatch.setattr(main, "vector_store", store)
    assert client.get(f"/answers/{answer_id}", headers=headers(keys)).status_code == 410


def test_revoked_project_denies_read_and_allows_owner_erasure(retained):
    client, keys, policy, policy_path, path, _ = retained
    answer_id = save(client, keys).json()["answer_id"]
    original = policy_path.read_text()
    policy["users"][0]["scopes"][0]["collection_id"] = "revoked"
    policy_path.write_text(json.dumps(policy))
    assert client.get(f"/answers/{answer_id}", headers=headers(keys)).status_code == 403
    assert_scrubbed(path)
    policy_path.write_text(original)
    assert client.get(f"/answers/{answer_id}", headers=headers(keys)).status_code == 410
    assert client.delete(f"/answers/{answer_id}", headers=headers(keys)).status_code == 200
    assert client.get(f"/answers/{answer_id}", headers=headers(keys)).status_code == 404


def test_exact_expiry_and_shortened_policy_delete_content(retained, monkeypatch):
    client, keys, _, _, path, _ = retained
    response = save(client, keys).json()
    expires_at = response["answer_expires_at"]
    monkeypatch.setattr(answer_store, "time", SimpleNamespace(time=lambda: expires_at - 0.01))
    assert client.get(f"/answers/{response['answer_id']}", headers=headers(keys)).status_code == 200
    monkeypatch.setattr(answer_store, "time", SimpleNamespace(time=lambda: expires_at))
    assert client.get(f"/answers/{response['answer_id']}", headers=headers(keys)).status_code == 404
    assert b"protected answer payload" not in path.read_bytes()


def test_maintenance_without_reads_purges_and_redacts_on_policy_outage(retained, monkeypatch):
    client, keys, _, policy_path, path, _ = retained
    save(client, keys)
    policy_path.write_text("invalid")
    with pytest.raises(HTTPException) as error:
        main._maintain_answers()
    assert error.value.status_code == 503
    assert_scrubbed(path)
    monkeypatch.setattr(answer_store, "time", SimpleNamespace(time=lambda: 10**12))
    answer_store.maintain(None)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 0


def test_inflight_index_change_cannot_save_stale_answer(retained, monkeypatch):
    client, keys, _, _, path, store = retained
    def generate(*args, **kwargs):
        store.clear()
        return "protected answer payload"
    monkeypatch.setattr(main, "generate_answer", generate)
    assert save(client, keys).status_code == 409
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 0


def test_storage_unavailable_and_remote_retention_fail_before_provider(retained, monkeypatch):
    client, keys, _, _, _, _ = retained
    def unexpected(*args, **kwargs):
        pytest.fail("provider must not be called")
    monkeypatch.setattr(main, "generate_answer", unexpected)
    monkeypatch.setattr(config, "ANSWER_RETENTION_DB", "")
    assert save(client, keys).status_code == 503
    monkeypatch.setattr(config, "ANSWER_RETENTION_DB", str(main.Path.cwd() / "private.sqlite3"))
    assert save(client, keys).status_code == 503
    monkeypatch.setattr(config, "RETRIEVAL_SERVICE_URL", "https://retrieval.invalid")
    assert save(client, keys).status_code == 409


def test_concurrent_saves_and_capacity_are_bounded(retained, monkeypatch):
    client, keys, _, _, _, _ = retained
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: save(client, keys), range(6)))
    assert all(result.status_code == 200 for result in results)
    assert len({result.json()["answer_id"] for result in results}) == 6
    monkeypatch.setattr(answer_store, "MAX_RECORDS", 6)
    assert save(client, keys).status_code == 409
    assert len(client.get("/answers", headers=headers(keys)).json()) == 6


def test_lowering_retention_period_purges_older_answers(retained, monkeypatch):
    client, keys, _, _, path, _ = retained
    result = save(client, keys).json()
    created_at = result["answer_expires_at"] - 30 * 86400
    monkeypatch.setattr(config, "ANSWER_RETENTION_DAYS", 1)
    monkeypatch.setattr(answer_store, "time", SimpleNamespace(time=lambda: created_at + 86400))
    main._maintain_answers()
    assert client.get(f"/answers/{result['answer_id']}", headers=headers(keys)).status_code == 404
    assert b"protected answer payload" not in path.read_bytes()


def test_lifespan_runs_retention_cleanup_and_stops_worker(retained, monkeypatch):
    client, keys, _, _, path, _ = retained
    response = save(client, keys).json()
    monkeypatch.setattr(main, "get_model", lambda: None)
    monkeypatch.setattr(main, "ensure_worker_started", lambda: None)
    monkeypatch.setattr(answer_store, "time", SimpleNamespace(time=lambda: response["answer_expires_at"]))
    with client:
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 0


def test_missing_policy_and_oversized_answer_do_not_expose_saved_text(retained, monkeypatch):
    client, keys, _, policy_path, _, _ = retained
    answer_id = save(client, keys).json()["answer_id"]
    original = policy_path.read_text()
    policy_path.unlink()
    result = client.get(f"/answers/{answer_id}", headers=headers(keys))
    assert result.status_code == 503
    assert "protected" not in result.text
    policy_path.write_text(original)
    monkeypatch.setattr(main, "generate_answer", lambda *args, **kwargs: "x" * 100001)
    result = save(client, keys)
    assert result.status_code == 422
    assert len(client.get("/answers", headers=headers(keys)).json()) == 1
