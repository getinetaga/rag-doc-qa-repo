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
import threading
import uuid
import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

import faiss
import numpy as np

from . import config

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class VectorSearchResult:
    """A single vector search result."""

    id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, VectorSearchResult):
            return (
                self.id,
                self.score,
                self.text,
                self.metadata,
            ) == (other.id, other.score, other.text, other.metadata)
        if isinstance(other, str):
            return self.text == other
        return NotImplemented


class VectorStoreBackend(Protocol):
    """Common interface implemented by all vector-store backends."""

    def add(
        self,
        embeddings: Sequence[Sequence[float]],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, Any]] | None = None,
        ids: Sequence[str] | None = None,
    ) -> None:
        ...

    def search(
        self,
        query_embedding: Sequence[float],
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        ...

    def delete(self, ids: Sequence[str]) -> None:
        ...

    def clear(self) -> None:
        ...


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
        self.ids: list[str] = []
        self.vectors: list[list[float]] = []
        self.revision = 0

    def add(
        self,
        embeddings,
        texts,
        source_document: str | None = None,
        metadata_list=None,
        metadatas=None,
        ids: Sequence[str] | None = None,
    ):
        arr = _as_float32_array(embeddings)
        texts_list = list(texts)
        if arr.ndim != 2 or len(arr) != len(texts_list) or (len(arr) and arr.shape[1] != self.dim):
            raise ValueError("Embeddings must match the text count and vector dimension.")
        if not np.isfinite(arr).all():
            raise ValueError("Embeddings must be finite.")
        if not texts_list:
            return
        if metadatas is not None:
            metadata_list = metadatas
        if metadata_list is None:
            metadata_list = [{} for _ in texts_list]
        else:
            metadata_list = list(metadata_list)

        if len(texts_list) != len(metadata_list):
            raise ValueError("texts and metadata_list must have the same length")
        if ids is None:
            ids_list = [uuid.uuid4().hex for _ in texts_list]
        else:
            ids_list = [str(value) for value in ids]
        if len(texts_list) != len(ids_list):
            raise ValueError("texts and ids must have the same length")
        if any(not value for value in ids_list) or len(set(ids_list)) != len(ids_list) or set(ids_list) & set(self.ids):
            raise ValueError("Chunk IDs must be unique.")
        new_metadata = []
        for metadata in metadata_list:
            row_meta = dict(metadata or {})
            if source_document is not None:
                row_meta.setdefault("source_document", source_document)
            new_metadata.append(row_meta)
        new_index = faiss.clone_index(self.index)
        new_index.add(arr)
        self.index = new_index
        self.texts = self.texts + texts_list
        self.ids = self.ids + ids_list
        self.vectors = self.vectors + arr.tolist()
        self.metadata = self.metadata + new_metadata
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
        matched: list[VectorSearchResult] = []
        for rank, i in enumerate(indices[0]):
            if not (0 <= i < len(self.texts)):
                continue
            row_meta = self.metadata[i] if i < len(self.metadata) else {}
            if not self._matches_filters(row_meta, source_document, filters):
                continue
            matched.append(
                VectorSearchResult(
                    id=self.ids[i],
                    score=float(_[0][rank]),
                    text=self.texts[i],
                    metadata=dict(row_meta),
                )
            )

        unique: list[VectorSearchResult] = []
        seen: set[str] = set()
        for result in matched:
            if result.text in seen:
                continue
            seen.add(result.text)
            unique.append(result)
        return unique[:limit]

    def clear(self, source_document: str | None = None, filters: dict | None = None):
        if source_document is None and not filters:
            if not self.texts:
                return
            self.index = faiss.IndexFlatL2(self.dim)
            self.texts = []
            self.metadata = []
            self.ids = []
            self.vectors = []
            self.revision += 1
            return

        original_len = len(self.texts)
        keep_texts = []
        keep_metadata = []
        keep_ids = []
        keep_vectors = []
        for idx, text in enumerate(self.texts):
            row_meta = self.metadata[idx] if idx < len(self.metadata) else {}
            if self._matches_filters(row_meta, source_document, filters):
                continue
            keep_texts.append(text)
            keep_metadata.append(row_meta)
            keep_ids.append(self.ids[idx])
            if idx < len(self.vectors):
                keep_vectors.append(self.vectors[idx])

        new_index = faiss.IndexFlatL2(self.dim)
        if keep_vectors:
            new_index.add(np.asarray(keep_vectors, dtype="float32"))
        self.index = new_index
        self.texts = keep_texts
        self.metadata = keep_metadata
        self.ids = keep_ids
        self.vectors = keep_vectors
        if len(keep_texts) != original_len:
            self.revision += 1

    def delete(self, ids: Sequence[str]) -> None:
        ids_to_delete = {str(value) for value in ids}
        if not ids_to_delete:
            return
        keep = [index for index, item_id in enumerate(self.ids) if item_id not in ids_to_delete]
        if len(keep) == len(self.ids):
            return
        new_index = faiss.IndexFlatL2(self.dim)
        keep_vectors = [self.vectors[index] for index in keep]
        if keep_vectors:
            new_index.add(np.asarray(keep_vectors, dtype="float32"))
        self.index = new_index
        self.texts = [self.texts[index] for index in keep]
        self.metadata = [self.metadata[index] for index in keep]
        self.ids = [self.ids[index] for index in keep]
        self.vectors = keep_vectors
        self.revision += 1

    def replace(self, embeddings, texts, *, source_document, metadata_list, filters):
        staged = copy.copy(self)
        staged.clear(source_document=source_document, filters=filters)
        staged.add(embeddings, texts, source_document=source_document, metadata_list=metadata_list)
        self._publish(staged)

    def _publish(self, staged):
        self.index, self.texts, self.metadata = staged.index, staged.texts, staged.metadata
        self.ids, self.vectors = staged.ids, staged.vectors
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

        self._conn = psycopg.connect(self.dsn, autocommit=True)
        with self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
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
        if arr.ndim != 2 or len(texts) != len(arr) or (len(arr) and arr.shape[1] != self.dim):
            raise ValueError("Embeddings and texts must have the same length")
        if not np.isfinite(arr).all():
            raise ValueError("Embeddings must be finite.")
        if not texts:
            return

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
        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {self.table_name} (text, embedding, source_document, metadata) VALUES (%s, %s, %s, %s::jsonb)",
                    rows,
                )
        self.revision += 1

    def replace(self, embeddings, texts, *, source_document, metadata_list, filters):
        revision = self.revision
        try:
            with self._conn.transaction():
                self.clear(source_document=source_document, filters=filters)
                self.add(embeddings, texts, source_document=source_document, metadata_list=metadata_list)
        except Exception:
            self.revision = revision
            raise
        self.revision = revision + 1

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
                SELECT id, text, metadata, source_document, embedding <-> %s::vector AS distance
                FROM {self.table_name}
                {where_sql}
                ORDER BY distance, id
                LIMIT %s
                """,
                [query_vector, *params, query_limit],
            )
            results = []
            seen = set()
            for row_id, text, metadata, source, distance in cur.fetchall():
                if text in seen:
                    continue
                seen.add(text)
                row_metadata = dict(metadata or {})
                if source is not None:
                    row_metadata.setdefault("source_document", source)
                results.append(VectorSearchResult(
                    id=str(row_id), score=float(distance), text=text, metadata=row_metadata,
                ))
            return results[:limit]

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

        with self._conn.transaction():
            with self._conn.cursor() as cur:
                cur.execute(f"DELETE FROM {self.table_name}{where_sql}", params)
                deleted_rows = cur.rowcount
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

        self.primary_backend = primary_backend.strip().lower()
        if self.primary_backend not in {"faiss", "pgvector"}:
            raise ValueError("The primary backend must be faiss or pgvector.")
        self._primary_store = self.stores[0]
        self.revision = 0
        for store in self.stores:
            if self.primary_backend in store.__class__.__name__.lower():
                self._primary_store = store
                break

    def add(self, embeddings, texts, source_document: str | None = None, metadata_list=None):
        self._write("add", embeddings, texts, source_document=source_document, metadata_list=metadata_list)

    def _write(self, operation, *args, **kwargs):
        staged = []
        persistent = []
        for store in self.stores:
            if isinstance(store, FaissVectorStore):
                candidate = copy.copy(store)
                getattr(candidate, operation)(*args, **kwargs)
                staged.append((store, candidate))
            else:
                persistent.append(store)
        if len(persistent) != 1:
            raise RuntimeError("Mirrored updates require exactly one persistent authority.")
        getattr(persistent[0], operation)(*args, **kwargs)
        for store, candidate in staged:
            store._publish(candidate)
        self.revision += 1

    def replace(self, embeddings, texts, *, source_document, metadata_list, filters):
        self._write(
            "replace", embeddings, texts, source_document=source_document,
            metadata_list=metadata_list, filters=filters,
        )

    def search(self, query_embedding, top_k=5, source_document: str | None = None, filters: dict | None = None):
        return self._primary_store.search(
            query_embedding,
            top_k=top_k,
            source_document=source_document,
            filters=filters,
        )

    def clear(self, source_document: str | None = None, filters: dict | None = None):
        self._write("clear", source_document=source_document, filters=filters)

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

    SUPPORTED_BACKENDS = {"faiss", "pgvector", "hybrid"}

    def __init__(
        self,
        dim: int,
        *,
        backend: str | None = None,
        dsn: str | None = None,
        table_name: str | None = None,
    ):
        if dim <= 0:
            raise ValueError("Vector dimension must be greater than zero.")

        backend_name = (backend or getattr(config, "VECTOR_DB_BACKEND", "faiss")).strip().lower()
        if backend_name not in self.SUPPORTED_BACKENDS:
            supported = ", ".join(sorted(self.SUPPORTED_BACKENDS))
            raise ValueError(
                f"Unsupported vector backend: '{backend_name}'. Supported backends: {supported}"
            )

        self.dim = int(dim)
        self.backend = backend_name
        self.backend_name = backend_name
        self.cache_namespace = uuid.uuid4().hex
        self._lock = threading.RLock()

        if backend_name == "faiss":
            self._store = FaissVectorStore(self.dim)
        elif backend_name == "pgvector":
            self._store = PGVectorStore(self.dim, dsn=dsn, table_name=table_name)
        elif backend_name == "hybrid":
            primary = getattr(config, "PGVECTOR_PRIMARY_SEARCH", "pgvector")
            self._store = HybridVectorStore(
                [
                    FaissVectorStore(self.dim),
                    PGVectorStore(self.dim, dsn=dsn, table_name=table_name),
                ],
                primary_backend=primary,
            )

    @contextmanager
    def read_snapshot(self):
        """Keep local revision, cache lookup, and retrieval consistent."""
        with self._lock:
            yield

    def add(
        self,
        embeddings: Sequence[Sequence[float]],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, Any]] | None = None,
        ids: Sequence[str] | None = None,
        *,
        source_document: str | None = None,
        metadata_list: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        if metadatas is not None and metadata_list is not None:
            raise ValueError("Use either metadatas or metadata_list, not both.")
        metadata_values = metadatas if metadatas is not None else metadata_list
        if metadata_values is not None:
            metadata_values = [dict(metadata or {}) for metadata in metadata_values]
            if source_document is not None:
                for metadata in metadata_values:
                    metadata.setdefault("source_document", source_document)
        texts_list = list(texts)
        logger.info("Adding %d vectors to '%s' backend.", len(texts_list), self.backend)
        add_kwargs = {
            "embeddings": embeddings,
            "texts": texts_list,
            "source_document": source_document,
            "metadata_list": metadata_values,
        }
        if ids is not None:
            if self.backend != "faiss":
                raise NotImplementedError("Explicit chunk IDs are currently supported only by FAISS.")
            add_kwargs["ids"] = ids
        with self._lock:
            self._store.add(**add_kwargs)

    def replace(self, embeddings, texts, *, source_document, metadata_list, filters):
        if not source_document or not filters:
            raise ValueError("Replacement requires an explicit source and scope.")
        with self._lock:
            self._store.replace(
                embeddings, texts, source_document=source_document,
                metadata_list=metadata_list, filters=filters,
            )

    def search(
        self,
        query_embedding: Sequence[float],
        top_k: int = 5,
        source_document: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        _t0 = time.monotonic()
        with self._lock:
            raw_results = self._store.search(
                query_embedding,
                top_k=top_k,
                source_document=source_document,
                filters=filters,
            )
        logger.debug(
            "Vector search returned %d results in %.3fs (backend: %s).",
            len(raw_results), time.monotonic() - _t0, self.backend,
        )
        if any(not isinstance(result, VectorSearchResult) for result in raw_results):
            raise TypeError("Vector backends must return genuine VectorSearchResult records.")
        return raw_results

    def delete(self, ids: Sequence[str]) -> None:
        delete = getattr(self._store, "delete", None)
        if not callable(delete):
            raise NotImplementedError(f"The {self.backend} backend does not support delete.")
        with self._lock:
            delete(ids)

    def clear(self, source_document: str | None = None, filters: dict | None = None):
        clear = getattr(self._store, "clear", None)
        if callable(clear):
            with self._lock:
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
