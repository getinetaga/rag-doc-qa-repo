import types

import pytest

from app import vector_store


class FakePGVectorStore:
    def __init__(self, dim, dsn=None, table_name=None):
        self.dim = dim
        self.dsn = dsn
        self.table_name = table_name
        self.rows = []

    def add(self, embeddings, texts, source_document=None, metadata_list=None):
        self.rows.extend(zip(embeddings, texts))

    def search(self, query_embedding, top_k=5, source_document=None, filters=None):
        texts = [text for _, text in self.rows[:top_k]] or ["pgvector-result"]
        return [
            vector_store.VectorSearchResult(str(index), 0.0, text, {})
            for index, text in enumerate(texts)
        ]


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
        return [(42, "sample doc", {"tenant_id": "tenant-a"}, "document-1", 0.25)]


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
    assert result[0].id == "42"
    assert result[0].score == 0.25
    assert result[0].metadata["tenant_id"] == "tenant-a"
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


def test_faiss_ids_survive_delete_and_never_collide():
    store = vector_store.FaissVectorStore(2)
    store.add([[0, 0], [1, 1], [2, 2]], ["a", "b", "c"])
    first, removed, third = store.ids
    store.delete([removed])
    store.add([[3, 3]], ["d"])
    assert len(set(store.ids)) == 3
    assert store.ids[:2] == [first, third]
    assert removed not in store.ids


@pytest.mark.parametrize("vectors,texts,ids", [
    ([[0, 0]], ["a", "b"], None),
    ([[0, 0, 0]], ["a"], None),
    ([[float("nan"), 0]], ["a"], None),
    ([[0, 0], [1, 1]], ["a", "b"], ["same", "same"]),
])
def test_faiss_rejects_invalid_batches_without_mutation(vectors, texts, ids):
    store = vector_store.FaissVectorStore(2)
    with pytest.raises(ValueError):
        store.add(vectors, texts, ids=ids)
    assert store.texts == []
    assert store.index.ntotal == 0
    assert store.revision == 0


def test_scoped_replacement_preserves_other_tenants_and_rolls_back_failure():
    store = vector_store.VectorStore(2, backend="faiss")
    scope = {"tenant_id": "a", "collection_id": "p", "document_id": "doc"}
    other = {**scope, "tenant_id": "b"}
    store.add([[0, 0], [1, 1]], ["old", "other"], source_document="doc", metadata_list=[scope, other])
    original_ids = list(store.ids)
    revision = store.revision
    with pytest.raises(ValueError):
        store.replace([[0, 0, 0]], ["invalid"], source_document="doc", metadata_list=[scope], filters=scope)
    assert store.texts == ["old", "other"]
    assert store.ids == original_ids
    assert store.revision == revision
    store.replace([[2, 2]], ["new"], source_document="doc", metadata_list=[scope], filters=scope)
    assert store.search([0, 0], filters=scope) == ["new"]
    assert store.search([0, 0], filters=other) == ["other"]
    assert store.ids[0] == original_ids[1]
    store.clear()
    assert store.index.ntotal == 0


def test_mirror_failure_does_not_publish_memory_write(monkeypatch):
    class FailingPG(FakePGVectorStore):
        def add(self, *args, **kwargs):
            raise RuntimeError("Database failed")

    monkeypatch.setattr(vector_store, "PGVectorStore", FailingPG)
    store = vector_store.VectorStore(2, backend="hybrid")
    with pytest.raises(RuntimeError):
        store.add([[0, 0]], ["not published"])
    assert store._store.stores[0].texts == []
    assert store.revision == 0


def test_wrapper_rejects_fabricated_result_contract(monkeypatch):
    store = vector_store.VectorStore(2, backend="faiss")
    monkeypatch.setattr(store._store, "search", lambda *args, **kwargs: ["legacy string"])
    with pytest.raises(TypeError, match="genuine"):
        store.search([0, 0])


def test_mirror_rejects_unknown_primary():
    with pytest.raises(ValueError, match="primary"):
        vector_store.HybridVectorStore([vector_store.FaissVectorStore(2)], primary_backend="unknown")
