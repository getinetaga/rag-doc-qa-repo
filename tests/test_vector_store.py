import types

import pytest

from app import vector_store


class FakePGVectorStore:
    def __init__(self, dim, dsn=None, table_name=None):
        self.dim = dim
        self.dsn = dsn
        self.table_name = table_name
        self.rows = []

    def add(self, embeddings, texts):
        self.rows.extend(zip(embeddings, texts))

    def search(self, query_embedding, top_k=5):
        return [text for _, text in self.rows[:top_k]] or ["pgvector-result"]


def test_vector_store_supports_backend_override():
    store = vector_store.VectorStore(dim=3, backend="faiss")
    store.add([[0.1, 0.2, 0.3]], ["hello"])

    assert store.search([0.1, 0.2, 0.3], top_k=1) == ["hello"]


def test_vector_store_can_use_pgvector_backend(monkeypatch):
    monkeypatch.setattr(vector_store, "PGVectorStore", FakePGVectorStore, raising=False)

    store = vector_store.VectorStore(dim=3, backend="pgvector")
    store.add([[0.1, 0.2, 0.3]], ["pg doc"])

    assert store.search([0.1, 0.2, 0.3], top_k=1) == ["pg doc"]


def test_vector_store_hybrid_mode_uses_pgvector_as_primary(monkeypatch):
    monkeypatch.setattr(vector_store, "PGVectorStore", FakePGVectorStore, raising=False)
    monkeypatch.setattr(
        vector_store,
        "config",
        types.SimpleNamespace(PGVECTOR_PRIMARY_SEARCH="pgvector"),
        raising=False,
    )

    store = vector_store.VectorStore(dim=3, backend="hybrid")
    store.add([[0.1, 0.2, 0.3]], ["hybrid doc"])

    assert store.search([0.1, 0.2, 0.3], top_k=1) == ["hybrid doc"]


class _RecordingCursor:
    def __init__(self):
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return [("sample doc",)]


class _RecordingConnection:
    def __init__(self):
        self.cursor_obj = _RecordingCursor()

    def cursor(self):
        return self.cursor_obj


def test_pgvector_search_casts_query_to_vector():
    store = vector_store.PGVectorStore.__new__(vector_store.PGVectorStore)
    store.table_name = "rag_embeddings"
    store._conn = _RecordingConnection()

    result = store.search([0.1, 0.2, 0.3], top_k=1)

    assert result == ["sample doc"]
    assert "%s::vector" in store._conn.cursor_obj.sql
    assert store._conn.cursor_obj.params[1] >= 1


def test_safe_identifier_rejects_invalid_names():
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        vector_store._safe_identifier("rag_embeddings;DROP TABLE")


def test_dedupe_texts_preserves_order():
    texts = ["alpha", "beta", "alpha", "gamma", "beta"]

    assert vector_store._dedupe_texts(texts) == ["alpha", "beta", "gamma"]


def test_faiss_vector_store_search_deduplicates_results():
    store = vector_store.FaissVectorStore(dim=2)
    store.add(
        [[0.0, 0.0], [0.0, 0.0], [1.0, 1.0]],
        ["duplicate", "duplicate", "other"],
    )

    results = store.search([0.0, 0.0], top_k=2)

    assert results == ["duplicate", "other"]


def test_create_vector_store_uses_requested_backend():
    store = vector_store.create_vector_store(dim=2, backend="faiss")

    assert isinstance(store, vector_store.VectorStore)
    assert store.backend == "faiss"
