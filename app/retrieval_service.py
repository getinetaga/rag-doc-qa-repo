"""Dedicated retrieval service for the RAG application.

This service isolates embedding + vector search work from the main API.
It is intended to run only with a shared persistent vector backend such as
pgvector or hybrid mode, so multiple API workers or containers can query the
same document index.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from . import config
from .auth import require_service_token
from .embeddings import embed_text, get_model
from .rag import _build_retrieval_filters, _rerank_context_chunks
from .vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

vector_store = None
_store_lock = threading.Lock()


class RetrievalRequest(BaseModel):
    question: str
    tenant_id: str = Field(min_length=1, max_length=128)
    collection_id: str = Field(min_length=1, max_length=128)
    document_id: str | None = None
    document_date: str | None = None
    author: str | None = None
    tag: str | None = None
    source_system: str | None = None
    top_k: int = Field(default=config.TOP_K, ge=1)
    candidate_pool_size: int = Field(default=config.RETRIEVAL_RERANK_POOL_SIZE, ge=1)


class RetrievalResponse(BaseModel):
    context_chunks: list[str]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Retrieval service starting — backend: %s | candidate pool: %s",
        getattr(config, "VECTOR_DB_BACKEND", "faiss"),
        getattr(config, "RETRIEVAL_RERANK_POOL_SIZE", config.TOP_K),
    )
    get_model()
    logger.info("Embedding model pre-loaded for retrieval service.")
    yield
    logger.info("Retrieval service shutting down.")
    if vector_store is not None:
        vector_store.close()


app = FastAPI(title="RAG Retrieval Service", lifespan=lifespan, dependencies=[Depends(require_service_token)])


def _ensure_vector_store(dim: int):
    global vector_store
    with _store_lock:
        if vector_store is None:
            vector_store = VectorStore(dim=dim)
    return vector_store


@app.post("/search", response_model=RetrievalResponse)
def search_context(req: RetrievalRequest):
    from fastapi import HTTPException

    if req.top_k > config.TOP_K or req.candidate_pool_size > config.RETRIEVAL_RERANK_POOL_SIZE:
        raise HTTPException(422, "Requested retrieval limits exceed server bounds.")
    if req.tenant_id.strip().lower() in {"", "default"} or req.collection_id.strip().lower() in {"", "default"}:
        raise HTTPException(422, "An explicit authorized tenant and collection are required.")
    query_embedding = embed_text([req.question])[0]
    store = _ensure_vector_store(dim=len(query_embedding))
    _, _, document_scope, filters = _build_retrieval_filters(
        req.tenant_id, req.collection_id, req.document_id,
        req.document_date, req.author, req.tag, req.source_system,
    )
    candidates = store.search(
        query_embedding, req.candidate_pool_size,
        source_document=document_scope, filters=filters,
    )

    context_chunks = _rerank_context_chunks(req.question, candidates)[: req.top_k]
    return {"context_chunks": context_chunks}
