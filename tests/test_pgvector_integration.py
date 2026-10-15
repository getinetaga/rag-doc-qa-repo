"""Opt-in tests requiring an explicitly designated disposable PostgreSQL database."""

import os
import uuid

import pytest

from app.vector_store import PGVectorStore

pytestmark = pytest.mark.skipif(
    not os.getenv("RAG_TEST_PGVECTOR_DSN") or os.getenv("RAG_ALLOW_DATABASE_TESTS") != "1",
    reason="Set RAG_TEST_PGVECTOR_DSN and RAG_ALLOW_DATABASE_TESTS=1 for a disposable test database.",
)


@pytest.fixture
def store():
    table = "rag_test_" + uuid.uuid4().hex
    value = PGVectorStore(2, dsn=os.environ["RAG_TEST_PGVECTOR_DSN"], table_name=table)
    try:
        yield value
    finally:
        with value._conn.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
        value.close()


def test_real_pg_results_scope_distance_and_idle_transaction(store):
    from psycopg.pq import TransactionStatus

    store.add(
        [[0, 0], [3, 4]], ["allowed", "other"],
        source_document="doc", metadata_list=[{"tenant_id": "a"}, {"tenant_id": "b"}],
    )
    results = store.search([0, 0], filters={"tenant_id": "b"})
    assert len(results) == 1
    assert results[0].id.isdigit()
    assert results[0].score == pytest.approx(5.0)
    assert results[0].metadata["tenant_id"] == "b"
    assert results[0].metadata["source_document"] == "doc"
    assert not store.search([0, 0], filters={"tenant_id": "' OR 1=1 --"})
    assert store._conn.info.transaction_status == TransactionStatus.IDLE


def test_real_pg_failed_replacement_preserves_previous_document(store):
    from psycopg.errors import CheckViolation
    from psycopg.pq import TransactionStatus

    scope = {"tenant_id": "a", "collection_id": "p", "document_id": "doc"}
    store.add([[0, 0]], ["old"], source_document="doc", metadata_list=[scope])
    previous = store.search([0, 0], filters=scope)[0]
    with store._conn.cursor() as cursor:
        cursor.execute(f"ALTER TABLE {store.table_name} ADD CHECK (text <> 'reject')")
    with pytest.raises(CheckViolation):
        store.replace([[1, 1]], ["reject"], source_document="doc", metadata_list=[scope], filters=scope)
    assert store.search([0, 0], filters=scope)[0] == previous
    assert store._conn.info.transaction_status == TransactionStatus.IDLE
    store.replace([[1, 1]], ["new"], source_document="doc", metadata_list=[scope], filters=scope)
    assert store.search([0, 0], filters=scope) == ["new"]
