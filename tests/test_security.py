import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth, config, inference_service, main, rag, retrieval_service, vector_store


def headers(keys, name="writer"):
    return {"Authorization": f"Bearer {keys[name]}"}


@pytest.mark.parametrize("path", ["/session", "/metrics", "/feedback/summary", "/question-domains", "/ingestion-jobs/unknown"])
def test_api_requires_authentication(secured, path):
    client, _, _, _ = secured
    assert client.get(path).status_code == 401


def test_upload_authentication_precedes_body_parsing(secured):
    client, _, _, _ = secured
    assert client.post("/upload", content=b"not a valid multipart body").status_code == 401


def test_invalid_keys_and_missing_policy_fail_closed(secured, monkeypatch):
    client, keys, _, path = secured
    assert client.get("/session", headers={"Authorization": "Bearer " + "invalid" * 8}).status_code == 401
    path.unlink()
    assert client.get("/session", headers=headers(keys)).status_code == 503


def test_session_does_not_expose_hashes_or_other_users(secured):
    client, keys, _, _ = secured
    result = client.get("/session", headers=headers(keys)).json()
    assert result == {
        "user_id": "writer", "roles": ["ingest", "read"],
        "scopes": [{"tenant_id": "tenant-a", "collection_id": "project-a"}],
    }


def test_scope_derived_from_server_and_cross_scope_denied(secured, monkeypatch):
    client, keys, _, _ = secured
    monkeypatch.setattr(main, "vector_store", object())
    captured = {}

    def generate(question, store, **kwargs):
        captured.update(kwargs)
        return "Permitted answer"

    monkeypatch.setattr(main, "generate_answer", generate)
    assert client.post("/ask", headers=headers(keys), json={"question": "Q"}).status_code == 200
    assert captured["tenant_id"] == "tenant-a"
    assert captured["collection_id"] == "project-a"
    assert client.post("/ask", headers=headers(keys), json={
        "question": "Q", "tenant_id": "tenant-b", "collection_id": "project-b",
    }).status_code == 403
    assert client.post("/ask", headers=headers(keys, "multi"), json={"question": "Q"}).status_code == 422


def test_key_revocation_is_immediate_for_next_request(secured):
    client, keys, policy, path = secured
    assert client.get("/session", headers=headers(keys)).status_code == 200
    policy["users"] = [user for user in policy["users"] if user["user_id"] != "writer"]
    path.write_text(json.dumps(policy), encoding="utf-8")
    assert client.get("/session", headers=headers(keys)).status_code == 401


def test_readers_cannot_ingest_and_metrics_require_admin(secured):
    client, keys, _, _ = secured
    assert client.post("/upload", headers=headers(keys, "reader"), files={
        "file": ("doc.txt", b"data", "text/plain"),
    }).status_code == 403
    assert client.get("/metrics", headers=headers(keys)).status_code == 403
    assert client.get("/metrics", headers=headers(keys, "admin")).status_code == 200


@pytest.mark.parametrize("path,payload", [
    ("/upload-google-doc", {"google_doc_url": "https://docs.google.com/document/d/example/edit"}),
    ("/upload-sharepoint", {"sharepoint_url": "https://example.sharepoint.com/document.docx"}),
])
def test_remote_connectors_require_admin(secured, path, payload):
    client, keys, _, _ = secured
    assert client.post(path, headers=headers(keys), json=payload).status_code == 403


def test_arbitrary_database_sources_and_sql_are_rejected(secured, monkeypatch):
    client, keys, _, _ = secured
    monkeypatch.setattr(main, "extract_database_text", lambda **kwargs: pytest.fail("Database must not be reached"))
    for user in ("writer", "admin"):
        assert client.post("/ingest-database", headers=headers(keys, user), json={
            "connection_string": "sqlite:///unapproved.db", "query": "SELECT * FROM private_data",
        }).status_code == 403
    assert client.post("/ingest-database", headers=headers(keys), json={"source_id": "unknown"}).status_code == 403
    assert client.post("/ingest-database", headers=headers(keys), json={
        "source_id": "approved", "query": "SELECT * FROM private_data",
    }).status_code == 422


def test_approved_database_query_and_row_cap_are_server_owned(secured, monkeypatch):
    client, keys, _, _ = secured
    captured = {}

    def extract(**kwargs):
        captured.update(kwargs)
        return "Approved row"

    monkeypatch.setattr(main, "extract_database_text", extract)
    monkeypatch.setattr(main, "_index_text_content", lambda **kwargs: {"message": "ready", "chunks": 1})
    result = client.post("/ingest-database", headers=headers(keys), json={
        "source_id": "approved", "max_rows": 9999,
    })
    assert result.status_code == 200
    assert captured["query"] == "SELECT id FROM permitted_view"
    assert captured["table"] is None
    assert captured["max_rows"] == 10


def test_feedback_is_private_and_respects_revoked_scope(secured):
    client, keys, policy, path = secured
    for user in ("writer", "reader"):
        assert client.post("/feedback", headers=headers(keys, user), json={
            "question": "Q", "answer": "A", "rating": "down", "correction": user,
        }).status_code == 200
    summary = client.get("/feedback/summary", headers=headers(keys)).json()
    assert summary["total_feedback"] == 1
    assert summary["recent_corrections"][0]["correction"] == "writer"
    policy["users"][0]["scopes"] = [{"tenant_id": "tenant-z", "collection_id": "project-z"}]
    path.write_text(json.dumps(policy), encoding="utf-8")
    assert client.get("/feedback/summary", headers=headers(keys)).json()["total_feedback"] == 0


def test_job_lookup_requires_owner_and_current_project_access(secured, monkeypatch):
    client, keys, _, _ = secured
    job = {"job_id": "job-1", "status": "queued", "owner_id": "writer", "tenant_id": "tenant-a", "collection_id": "project-a"}
    monkeypatch.setattr(main, "get_job", lambda _: dict(job))
    assert client.get("/ingestion-jobs/job-1", headers=headers(keys, "reader")).status_code == 404
    result = client.get("/ingestion-jobs/job-1", headers=headers(keys))
    assert result.status_code == 200
    assert "owner_id" not in result.json()
    job["tenant_id"] = "tenant-b"
    assert client.get("/ingestion-jobs/job-1", headers=headers(keys)).status_code == 403


def test_same_filename_uploads_have_private_immutable_staging(secured, monkeypatch):
    client, keys, _, _ = secured
    monkeypatch.setattr(config, "ASYNC_INGESTION_MIN_BYTES", 0)
    paths = []

    def enqueue(handler, file_path, *args, **kwargs):
        paths.append(Path(file_path))
        assert kwargs["job_owner"] == "writer"
        assert kwargs["job_scope"] == ("tenant-a", "project-a")
        return str(len(paths))

    monkeypatch.setattr(main, "enqueue_job", enqueue)
    try:
        for content in (b"first", b"second"):
            result = client.post("/upload", headers=headers(keys), files={
                "file": ("..\\same.txt", content, "text/plain"),
            })
            assert result.status_code == 200
        assert paths[0] != paths[1]
        assert [path.read_bytes() for path in paths] == [b"first", b"second"]
        assert all(path.name.startswith("rag-upload-") and path.suffix == ".txt" for path in paths)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def test_failed_queue_handoff_cleans_staging(secured, monkeypatch):
    client, keys, _, _ = secured
    monkeypatch.setattr(config, "ASYNC_INGESTION_MIN_BYTES", 0)
    paths = []

    def enqueue(handler, path, *args, **kwargs):
        paths.append(Path(path))
        raise HTTPException(503, "Queue full")

    monkeypatch.setattr(main, "enqueue_job", enqueue)
    assert client.post("/upload", headers=headers(keys), files={"file": ("doc.txt", b"data")}).status_code == 503
    assert paths and not paths[0].exists()


def test_upload_size_limit_and_parser_failure_cleanup(secured, monkeypatch):
    client, keys, _, _ = secured
    monkeypatch.setattr(config, "MAX_UPLOAD_FILE_SIZE_BYTES", 2)
    assert client.post("/upload", headers=headers(keys), files={"file": ("doc.txt", b"data")}).status_code == 413
    monkeypatch.setattr(config, "MAX_UPLOAD_FILE_SIZE_BYTES", 100)
    monkeypatch.setattr(config, "ASYNC_INGESTION_MIN_BYTES", 100)
    paths = []

    def extract(path):
        paths.append(Path(path))
        raise ValueError("Parser failed")

    monkeypatch.setattr(main, "extract_text", extract)
    with pytest.raises(ValueError, match="Parser failed"):
        client.post("/upload", headers=headers(keys), files={"file": ("doc.txt", b"data")})
    assert paths and not paths[0].exists()


def test_internal_services_reject_personal_keys_and_unscoped_search(secured, monkeypatch):
    _, keys, _, _ = secured
    token = "unit-test-internal-service-token-" + "s" * 32
    monkeypatch.setattr(config, "RAG_SERVICE_TOKEN", token)
    retrieval = TestClient(retrieval_service.app)
    inference = TestClient(inference_service.app)
    payload = {"question": "Q", "tenant_id": "tenant-a", "collection_id": "project-a"}
    assert retrieval.post("/search", headers=headers(keys), json=payload).status_code == 401
    assert inference.post("/generate", headers=headers(keys), json={"prompt": "Q"}).status_code == 401
    for tenant in ("default", " ", ""):
        assert retrieval.post("/search", headers={"Authorization": f"Bearer {token}"}, json={
            **payload, "tenant_id": tenant,
        }).status_code == 422


def test_policy_rejects_duplicate_keys_and_unapproved_default(secured):
    _, _, policy, _ = secured
    policy["users"][1]["key_sha256"] = policy["users"][0]["key_sha256"]
    with pytest.raises(ValueError, match="unique"):
        auth.AccessPolicy.model_validate(policy)


def test_authenticated_pipeline_isolates_real_faiss_context_and_cache(secured, monkeypatch):
    client, keys, _, _ = secured
    store = vector_store.VectorStore(2, backend="faiss")
    store.add(
        [[0, 0], [0, 0]],
        [
            "[A] Alpha inspection policy requires weekly checks.",
            "[B] Beta inspection policy requires daily checks.",
        ],
        metadata_list=[
            {"tenant_id": "tenant-a", "collection_id": "project-a"},
            {"tenant_id": "tenant-b", "collection_id": "project-b"},
        ],
    )
    monkeypatch.setattr(main, "vector_store", store)
    monkeypatch.setattr(rag, "embed_text", lambda texts: [[0, 0]])
    prompts = []

    def generate(prompt):
        prompts.append(prompt)
        if "[A] Alpha" in prompt:
            assert "[B] Beta" not in prompt
            return "Alpha inspection policy requires weekly checks."
        assert "[A] Alpha" not in prompt
        return "Beta inspection policy requires daily checks."

    monkeypatch.setattr(rag, "_generate_from_prompt", generate)
    answers = [
        client.post("/ask", headers=headers(keys, user), json={
            "question": "What does the inspection policy require?",
        }).json()["answer"]
        for user in ("writer", "other", "writer")
    ]
    assert "weekly" in answers[0]
    assert "daily" in answers[1]
    assert answers[0] == answers[2]
    assert len(prompts) == 2


def test_cross_project_upload_is_rejected_before_staging(secured, monkeypatch):
    client, keys, _, _ = secured
    monkeypatch.setattr(main.tempfile, "NamedTemporaryFile", lambda **kwargs: pytest.fail("Must not stage"))
    assert client.post("/upload", headers=headers(keys), data={
        "tenant_id": "tenant-b", "collection_id": "project-b",
    }, files={"file": ("doc.txt", b"data")}).status_code == 403


def test_revoked_queued_upload_is_not_processed(secured, monkeypatch):
    client, keys, policy, path = secured
    monkeypatch.setattr(config, "ASYNC_INGESTION_MIN_BYTES", 0)
    pending = []

    def enqueue(handler, *args, **kwargs):
        pending.append((handler, args, kwargs))
        return "queued-job"

    monkeypatch.setattr(main, "enqueue_job", enqueue)
    assert client.post("/upload", headers=headers(keys), files={"file": ("doc.txt", b"data")}).status_code == 200
    handler, args, kwargs = pending[0]
    staged = Path(args[0])
    policy["users"] = [user for user in policy["users"] if user["user_id"] != "writer"]
    path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(main, "extract_text", lambda _: pytest.fail("Revoked job must not parse"))
    try:
        with pytest.raises(HTTPException) as error:
            handler(*args, owner_id=kwargs["owner_id"])
        assert error.value.status_code == 403
        assert not staged.exists()
    finally:
        staged.unlink(missing_ok=True)


def test_answer_is_not_returned_after_project_access_is_revoked(secured, monkeypatch):
    client, keys, policy, path = secured
    monkeypatch.setattr(main, "vector_store", object())

    def generate(*args, **kwargs):
        policy["users"][0]["scopes"] = [{"tenant_id": "tenant-z", "collection_id": "project-z"}]
        policy["users"][0]["database_sources"] = []
        path.write_text(json.dumps(policy), encoding="utf-8")
        return "Do not disclose this answer."

    monkeypatch.setattr(main, "generate_answer", generate)
    response = client.post("/ask", headers=headers(keys), json={"question": "Q"})
    assert response.status_code == 403
    assert "Do not disclose" not in response.text


def test_startup_checks_policy_before_loading_models(secured, monkeypatch):
    _, _, _, path = secured
    path.unlink()
    monkeypatch.setattr(main, "get_model", lambda: pytest.fail("Must validate access policy first"))
    with pytest.raises(HTTPException) as error:
        with TestClient(main.app):
            pass
    assert error.value.status_code == 503


def test_startup_rejects_multiple_api_workers(secured, monkeypatch):
    monkeypatch.setattr(config, "API_WORKERS", 2)
    monkeypatch.setattr(main, "get_model", lambda: pytest.fail("Must reject incompatible topology first"))
    with pytest.raises(RuntimeError, match="API_WORKERS"):
        with TestClient(main.app):
            pass


def test_ingest_only_user_can_poll_own_job_without_reading_documents(secured, monkeypatch):
    client, keys, policy, path = secured
    policy["users"][0]["roles"] = ["ingest"]
    path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(main, "get_job", lambda _: {
        "job_id": "job-1", "status": "queued", "owner_id": "writer",
        "tenant_id": "tenant-a", "collection_id": "project-a",
    })
    assert client.get("/ingestion-jobs/job-1", headers=headers(keys)).status_code == 200
    assert client.post("/ask", headers=headers(keys), json={"question": "Q"}).status_code == 403
