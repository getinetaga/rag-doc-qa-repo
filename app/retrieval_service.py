"""Dedicated retrieval service for the RAG application.

This service isolates embedding + vector search work from the main API.
It is intended to run only with a shared persistent vector backend such as
pgvector or hybrid mode, so multiple API workers or containers can query the
same document index.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from . import config
from .embeddings import embed_text, get_model
from .rag import _rerank_context_chunks
from .vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

vector_store = None


class RetrievalRequest(BaseModel):
    question: str
    tenant_id: str | None = None
    collection_id: str | None = None
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


app = FastAPI(title="RAG Retrieval Service", lifespan=lifespan)


def _ensure_vector_store(dim: int):
    global vector_store
    if vector_store is None:
        vector_store = VectorStore(dim=dim)
    return vector_store


@app.post("/search", response_model=RetrievalResponse)
async def search_context(req: RetrievalRequest):
    query_embedding = embed_text([req.question])[0]
    store = _ensure_vector_store(dim=len(query_embedding))
    filters = {}
    if req.tenant_id:
        filters["tenant_id"] = req.tenant_id
    if req.collection_id:
        filters["collection_id"] = req.collection_id
    if req.document_id:
        filters["document_id"] = req.document_id
    if req.document_date:
        filters["document_date"] = req.document_date
    if req.author:
        filters["author"] = req.author
    if req.tag:
        filters["tag"] = req.tag
    if req.source_system:
        filters["source_system"] = req.source_system

    try:
        candidates = store.search(
            query_embedding,
            req.candidate_pool_size,
            source_document=req.document_id,
            filters=filters or None,
        )
    except TypeError:
        candidates = store.search(query_embedding, req.top_k)

    context_chunks = _rerank_context_chunks(req.question, candidates)[: req.top_k]
    return {"context_chunks": context_chunks}
