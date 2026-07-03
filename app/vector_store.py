"""Configurable vector-store backends for the RAG demo.

The project keeps FAISS as the default in-memory index, and now also
supports `pgvector` on PostgreSQL for persistent storage. A small hybrid
mode is included as well so the app can mirror writes to both backends
while using one of them as the primary search backend.
"""

from __future__ import annotations

import logging
import json
import re
import time
from typing import Sequence

import faiss
import numpy as np

from . import config

logger = logging.getLogger(__name__)

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


def _dedupe_texts(texts) -> list[str]:
    """Remove duplicate text results while preserving order."""

    unique: list[str] = []
    seen: set[str] = set()
    for text in texts:
        value = str(text)
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


class FaissVectorStore:
    """FAISS-backed in-memory vector store."""

    def __init__(self, dim: int):
        self.dim = int(dim)
        self.index = faiss.IndexFlatL2(self.dim)
        self.texts: list[str] = []
        self.metadata: list[dict] = []
        self.vectors: list[list[float]] = []
        self.revision = 0

    def add(self, embeddings, texts, source_document: str | None = None, metadata_list=None):
        arr = _as_float32_array(embeddings)
        if arr.size == 0:
            return

        texts_list = list(texts)
        if metadata_list is None:
            metadata_list = [{} for _ in texts_list]
        else:
            metadata_list = list(metadata_list)

        if len(texts_list) != len(metadata_list):
            raise ValueError("texts and metadata_list must have the same length")

        self.index.add(arr)
        self.texts.extend(texts_list)
        self.vectors.extend(arr.tolist())
        for metadata in metadata_list:
            row_meta = dict(metadata or {})
            if source_document is not None:
                row_meta.setdefault("source_document", source_document)
            self.metadata.append(row_meta)
        self.revision += 1

    @staticmethod
    def _matches_filters(row_meta: dict, source_document: str | None, filters: dict | None) -> bool:
        if source_document is not None and str(row_meta.get("source_document")) != str(source_document):
            return False

        if filters:
            for key, value in filters.items():
                if str(row_meta.get(key)) != str(value):
                    return False

        return True

    def search(self, query_embedding, top_k=5, source_document: str | None = None, filters: dict | None = None):
        if not self.texts:
            return []

        limit = max(1, min(int(top_k), len(self.texts)))
        search_limit = len(self.texts)
        q = np.asarray([query_embedding], dtype="float32")
        _, indices = self.index.search(q, search_limit)
        matched = []
        for i in indices[0]:
            if not (0 <= i < len(self.texts)):
                continue
            row_meta = self.metadata[i] if i < len(self.metadata) else {}
            if not self._matches_filters(row_meta, source_document, filters):
                continue
            matched.append(self.texts[i])

        return _dedupe_texts(matched)[:limit]

    def clear(self, source_document: str | None = None, filters: dict | None = None):
        if source_document is None and not filters:
            if not self.texts:
                return
            self.index = faiss.IndexFlatL2(self.dim)
            self.texts = []
            self.metadata = []
            self.vectors = []
            self.revision += 1
            return

        original_len = len(self.texts)
        keep_texts = []
        keep_metadata = []
        keep_vectors = []
        for idx, text in enumerate(self.texts):
            row_meta = self.metadata[idx] if idx < len(self.metadata) else {}
            if self._matches_filters(row_meta, source_document, filters):
                continue
            keep_texts.append(text)
            keep_metadata.append(row_meta)
            if idx < len(self.vectors):
                keep_vectors.append(self.vectors[idx])

        self.index = faiss.IndexFlatL2(self.dim)
        self.texts = keep_texts
        self.metadata = keep_metadata
        self.vectors = keep_vectors
        if self.vectors:
            self.index.add(np.asarray(self.vectors, dtype="float32"))
        if len(keep_texts) != original_len:
            self.revision += 1


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
        self.revision = 0

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

    def add(self, embeddings, texts, source_document: str | None = None, metadata_list=None):
        arr = _as_float32_array(embeddings)
        texts = list(texts)
        if arr.size == 0 or not texts:
            return
        if len(texts) != len(arr):
            raise ValueError("Embeddings and texts must have the same length")

        if metadata_list is None:
            metadata_list = [{} for _ in texts]
        else:
            metadata_list = list(metadata_list)
        if len(metadata_list) != len(texts):
            raise ValueError("texts and metadata_list must have the same length")

        rows = [
            (
                text,
                arr[i].tolist(),
                source_document,
                json.dumps(metadata_list[i] or {}),
            )
            for i, text in enumerate(texts)
        ]
        with self._conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {self.table_name} (text, embedding, source_document, metadata) VALUES (%s, %s, %s, %s::jsonb)",
                rows,
            )
        self._conn.commit()
        self.revision += 1

    def search(self, query_embedding, top_k=5, source_document: str | None = None, filters: dict | None = None):
        limit = max(1, int(top_k))
        query_limit = max(limit, limit * 5)
        query_vector = np.asarray(query_embedding, dtype="float32").tolist()

        where_clauses = []
        params: list[object] = []

        if source_document is not None:
            where_clauses.append("source_document = %s")
            params.append(source_document)

        if filters:
            for key, value in filters.items():
                where_clauses.append("metadata ->> %s = %s")
                params.extend([str(key), str(value)])

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT text
                FROM {self.table_name}
                {where_sql}
                ORDER BY embedding <-> %s::vector
                LIMIT %s
                """,
                [*params, query_vector, query_limit],
            )
            rows = [row[0] for row in cur.fetchall()]
            return _dedupe_texts(rows)[:limit]

    def clear(self, source_document: str | None = None, filters: dict | None = None):
        where_clauses = []
        params: list[object] = []

        if source_document is not None:
            where_clauses.append("source_document = %s")
            params.append(source_document)

        if filters:
            for key, value in filters.items():
                where_clauses.append("metadata ->> %s = %s")
                params.extend([str(key), str(value)])

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self.table_name}{where_sql}", params)
            deleted_rows = cur.rowcount
        self._conn.commit()
        if deleted_rows:
            self.revision += 1

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
        self.revision = 0
        for store in self.stores:
            if self.primary_backend in store.__class__.__name__.lower():
                self._primary_store = store
                break

    def add(self, embeddings, texts, source_document: str | None = None, metadata_list=None):
        for store in self.stores:
            store.add(
                embeddings,
                texts,
                source_document=source_document,
                metadata_list=metadata_list,
            )
        self.revision += 1

    def search(self, query_embedding, top_k=5, source_document: str | None = None, filters: dict | None = None):
        return self._primary_store.search(
            query_embedding,
            top_k=top_k,
            source_document=source_document,
            filters=filters,
        )

    def clear(self, source_document: str | None = None, filters: dict | None = None):
        for store in self.stores:
            clear = getattr(store, "clear", None)
            if callable(clear):
                clear(source_document=source_document, filters=filters)
        self.revision += 1

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

    def add(self, embeddings, texts, source_document: str | None = None, metadata_list=None):
        texts_list = list(texts)
        logger.info("Adding %d vectors to '%s' backend.", len(texts_list), self.backend)
        return self._store.add(
            embeddings,
            texts_list,
            source_document=source_document,
            metadata_list=metadata_list,
        )

    def search(self, query_embedding, top_k=5, source_document: str | None = None, filters: dict | None = None):
        _t0 = time.monotonic()
        results = self._store.search(
            query_embedding,
            top_k=top_k,
            source_document=source_document,
            filters=filters,
        )
        logger.debug(
            "Vector search returned %d results in %.3fs (backend: %s).",
            len(results), time.monotonic() - _t0, self.backend,
        )
        return results

    def clear(self, source_document: str | None = None, filters: dict | None = None):
        clear = getattr(self._store, "clear", None)
        if callable(clear):
            clear(source_document=source_document, filters=filters)

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
