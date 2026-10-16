import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app import config, feedback_store, main, rag, slo_metrics


@pytest.fixture
def secured(tmp_path, monkeypatch):
    keys = {name: f"unit-test-{name}-" + "x" * 40 for name in ("writer", "reader", "other", "admin", "multi")}
    scope = {"tenant_id": "tenant-a", "collection_id": "project-a"}
    other_scope = {"tenant_id": "tenant-b", "collection_id": "project-b"}
    users = []
    for name in keys:
        users.append({
            "user_id": name,
            "key_sha256": hashlib.sha256(keys[name].encode()).hexdigest(),
            "roles": ["read", "ingest", "admin"] if name == "admin" else ["read", "ingest"] if name == "writer" else ["read"],
            "scopes": [scope, other_scope] if name == "multi" else [other_scope] if name == "other" else [scope],
            "database_sources": ["approved"] if name in {"writer", "admin"} else [],
        })
    policy = {
        "users": users,
        "database_sources": {"approved": {
            **scope, "dsn_env": "TEST_APPROVED_DB", "query": "SELECT id FROM permitted_view", "max_rows": 10,
        }},
    }
    path = tmp_path / "access.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(config, "RAG_API_USERS_FILE", str(path))
    monkeypatch.setenv("TEST_APPROVED_DB", "sqlite:///" + str(tmp_path / "approved.db"))
    monkeypatch.setattr(main, "vector_store", None)
    feedback_store.reset()
    slo_metrics.reset()
    rag._clear_caches()
    yield TestClient(main.app), keys, policy, path
    feedback_store.reset()
    slo_metrics.reset()
    rag._clear_caches()
