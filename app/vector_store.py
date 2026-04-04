"""Configurable vector-store backends for the RAG demo.

The project keeps FAISS as the default in-memory index, and now also
supports `pgvector` on PostgreSQL for persistent storage. A small hybrid
mode is included as well so the app can mirror writes to both backends
while using one of them as the primary search backend.
"""

from __future__ import annotations

import re
from typing import Sequence

import faiss
import numpy as np

from . import config

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _as_float32_array(embeddings) -> np.ndarray:
    """Normalize embeddings to a 2-D float32 NumPy array."""

    arr = np.asarray(embeddings, dtype="float32")
    if arr.size == 0:
        return np.empty((0, 0), dtype="float32")
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    return arr


def _safe_identifier(value: str) -> str:
    """Allow only simple SQL identifiers for table names."""

    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")
    return value


class FaissVectorStore:
    """FAISS-backed in-memory vector store."""

    def __init__(self, dim: int):
        self.dim = int(dim)
        self.index = faiss.IndexFlatL2(self.dim)
        self.texts: list[str] = []

    def add(self, embeddings, texts):
        arr = _as_float32_array(embeddings)
        if arr.size == 0:
            return

        self.index.add(arr)
        self.texts.extend(list(texts))

    def search(self, query_embedding, top_k=5):
        if not self.texts:
            return []

        limit = max(1, min(int(top_k), len(self.texts)))
        q = np.asarray([query_embedding], dtype="float32")
        _, indices = self.index.search(q, limit)
        return [self.texts[i] for i in indices[0] if 0 <= i < len(self.texts)]


class PGVectorStore:
    """PostgreSQL + pgvector-backed persistent vector store."""

    def __init__(self, dim: int, dsn: str | None = None, table_name: str | None = None):
        self.dim = int(dim)
        self.dsn = dsn or getattr(config, "PGVECTOR_DSN", None)
        if not self.dsn:
            raise ValueError(
                "PGVector backend selected, but PGVECTOR_DSN is not configured."
            )

        self.table_name = _safe_identifier(
            table_name or getattr(config, "PGVECTOR_TABLE_NAME", "rag_embeddings")
        )

        try:
            import psycopg
            from pgvector.psycopg import register_vector
        except ImportError as exc:
            raise ImportError(
                "pgvector support requires the 'pgvector' and 'psycopg[binary]' packages."
            ) from exc

        self._conn = psycopg.connect(self.dsn, autocommit=False)
        register_vector(self._conn)
        self._ensure_schema()

    def _ensure_schema(self):
        index_name = _safe_identifier(f"{self.table_name}_embedding_hnsw_idx")
        source_index_name = _safe_identifier(f"{self.table_name}_source_document_idx")

        with self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    id BIGSERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    embedding vector({self.dim}) NOT NULL,
                    source_document TEXT,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {index_name}
                ON {self.table_name} USING hnsw (embedding vector_l2_ops)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {source_index_name}
                ON {self.table_name} (source_document)
                """
            )
        self._conn.commit()

    def add(self, embeddings, texts):
        arr = _as_float32_array(embeddings)
        texts = list(texts)
        if arr.size == 0 or not texts:
            return
        if len(texts) != len(arr):
            raise ValueError("Embeddings and texts must have the same length")

        rows = [(text, arr[i].tolist()) for i, text in enumerate(texts)]
        with self._conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {self.table_name} (text, embedding) VALUES (%s, %s)",
                rows,
            )
        self._conn.commit()

    def search(self, query_embedding, top_k=5):
        limit = max(1, int(top_k))
        query_vector = np.asarray(query_embedding, dtype="float32").tolist()

        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT text
                FROM {self.table_name}
                ORDER BY embedding <-> %s
                LIMIT %s
                """,
                (query_vector, limit),
            )
            return [row[0] for row in cur.fetchall()]

    def close(self):
        if getattr(self, "_conn", None) is not None:
            self._conn.close()


class HybridVectorStore:
    """Mirror writes to multiple backends and search using a primary backend."""

    def __init__(self, stores: Sequence[object], primary_backend: str = "pgvector"):
        self.stores = list(stores)
        if not self.stores:
            raise ValueError("HybridVectorStore requires at least one backend")

        self.primary_backend = primary_backend.lower()
        self._primary_store = self.stores[0]
        for store in self.stores:
            if self.primary_backend in store.__class__.__name__.lower():
                self._primary_store = store
                break

    def add(self, embeddings, texts):
        for store in self.stores:
            store.add(embeddings, texts)

    def search(self, query_embedding, top_k=5):
        return self._primary_store.search(query_embedding, top_k=top_k)

    def close(self):
        for store in self.stores:
            close = getattr(store, "close", None)
            if callable(close):
                close()


class VectorStore:
    """Compatibility wrapper that selects a vector backend at runtime.

    By default this behaves exactly like the original FAISS-backed store.
    Set `VECTOR_DB_BACKEND` to `pgvector` or `hybrid` to opt into the new
    PostgreSQL/pgvector path.
    """

    def __init__(
        self,
        dim: int,
        backend: str | None = None,
        dsn: str | None = None,
        table_name: str | None = None,
    ):
        self.backend = (backend or getattr(config, "VECTOR_DB_BACKEND", "faiss")).lower()

        if self.backend == "faiss":
            self._store = FaissVectorStore(dim)
        elif self.backend == "pgvector":
            self._store = PGVectorStore(dim, dsn=dsn, table_name=table_name)
        elif self.backend == "hybrid":
            primary = getattr(config, "PGVECTOR_PRIMARY_SEARCH", "pgvector")
            self._store = HybridVectorStore(
                [
                    FaissVectorStore(dim),
                    PGVectorStore(dim, dsn=dsn, table_name=table_name),
                ],
                primary_backend=primary,
            )
        else:
            raise ValueError(
                "Unsupported VECTOR_DB_BACKEND. Use 'faiss', 'pgvector', or 'hybrid'."
            )

    def add(self, embeddings, texts):
        return self._store.add(embeddings, texts)

    def search(self, query_embedding, top_k=5):
        return self._store.search(query_embedding, top_k=top_k)

    def close(self):
        close = getattr(self._store, "close", None)
        if callable(close):
            close()

    def __getattr__(self, name):
        return getattr(self._store, name)


def create_vector_store(
    dim: int,
    backend: str | None = None,
    dsn: str | None = None,
    table_name: str | None = None,
) -> VectorStore:
    """Factory helper for callers that prefer explicit construction."""

    return VectorStore(dim=dim, backend=backend, dsn=dsn, table_name=table_name)
