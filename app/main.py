"""Simple FastAPI app exposing two endpoints for a RAG (Retrieval-Augmented Generation)
document question-answering pipeline.

Endpoints:
- POST /upload : Accepts a file upload, extracts text, chunks it, embeds chunks and
  stores them in the configured vector store for later retrieval.
- POST /ask    : Accepts a question and returns an answer generated using the
  previously built vector store.

This module wires together the smaller pipeline components located in the `app`
package: `ingestion`, `chunking`, `embeddings`, `vector_store`, and `rag`.
"""

import logging
import os
import re
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from . import config
from .chunking import chunk_text
from .embeddings import embed_text, get_model
from .ingestion import extract_google_doc_text, extract_text
from .ingestion_jobs import enqueue_job, ensure_worker_started, get_job
from .rag import generate_answer
from .rag import classify_question_domain, get_question_domain_catalog
from . import slo_metrics
from . import feedback_store
from .schemas import (
    AnswerResponse,
    FeedbackRequest,
    FeedbackResponse,
    GoogleDocIngestRequest,
    IngestResponse,
    QuestionDomainCatalogResponse,
    QuestionRequest,
)
from .vector_store import VectorStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle event handlers.

    Startup:
    - Logs the active LLM provider and vector-backend configuration.
    - Pre-warms the SentenceTransformer embedding model so the first
      /upload request is not delayed by a cold-start model load.

    Shutdown:
    - Closes any open vector-store database connections (e.g., pgvector).
    """
    # --- startup ---
    logger.info(
        "RAG Document QA API starting up — LLM provider: %s | vector backend: %s",
        getattr(config, "LLM_PROVIDER", "openai"),
        getattr(config, "VECTOR_DB_BACKEND", "faiss"),
    )
    get_model()
    logger.info("Embedding model pre-loaded and ready.")
    ensure_worker_started()

    global vector_store
    if vector_store is None:
        try:
            vector_store = VectorStore(dim=getattr(config, "EMBEDDING_DIM", 384))
            logger.info("Shared vector store initialized at startup.")
        except Exception as exc:
            logger.warning("Vector store startup initialization deferred: %s", exc)
    yield
    # --- shutdown ---
    logger.info("RAG Document QA API shutting down.")
    if vector_store is not None:
        vector_store.close()
        logger.info("Vector store connection closed.")


# Initialize FastAPI application
app = FastAPI(title="RAG Document QA", lifespan=lifespan)

# A module-level reference to the currently active VectorStore instance. It is
# created when a document is uploaded and kept in module scope for subsequent
# /ask calls. Depending on configuration it can use FAISS, pgvector, or a
# hybrid combination of both.
vector_store = None
vector_store_lock = threading.RLock()


def _resolve_document_id(document_id: str, original_name: str) -> str:
    """Resolve a stable document id when callers pass the default placeholder."""

    cleaned = str(document_id or "").strip()
    if cleaned and cleaned.lower() != "default":
        return cleaned

    stem = Path(str(original_name or "document")).stem
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_").lower()
    return slug or "document"


def _ensure_vector_store(dim: int):
    """Lazily initialize a shared vector store instance."""

    global vector_store
    if vector_store is None:
        vector_store = VectorStore(dim=dim)
    return vector_store


def _process_upload_job(
    file_path: str,
    tenant_id: str,
    collection_id: str,
    document_id: str,
    original_name: str,
    document_date: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    source_system: str | None = None,
):
    """Process an uploaded file and update the scoped vector index."""

    try:
        text = extract_text(file_path)
        return _index_text_content(
            text=text,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            original_name=original_name,
            document_date=document_date,
            author=author,
            tag=tag,
            source_system=source_system,
        )
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


def _index_text_content(
    text: str,
    tenant_id: str,
    collection_id: str,
    document_id: str,
    original_name: str,
    document_date: str | None = None,
    author: str | None = None,
    tag: str | None = None,
    source_system: str | None = None,
):
    """Chunk, embed, and index text content in the scoped vector store."""

    effective_document_id = _resolve_document_id(document_id, original_name)

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("No extractable text content was found.")

    embeddings = embed_text(chunks)

    store = _ensure_vector_store(dim=len(embeddings[0]))
    metadata_base = {
        "tenant_id": tenant_id,
        "collection_id": collection_id,
        "document_id": effective_document_id,
    }
    if document_date:
        metadata_base["document_date"] = document_date
    if author:
        metadata_base["author"] = author
    if tag:
        metadata_base["tag"] = tag
    if source_system:
        metadata_base["source_system"] = source_system
    metadata_list = [dict(metadata_base) for _ in chunks]

    with vector_store_lock:
        clear = getattr(store, "clear", None)
        if callable(clear):
            clear(
                source_document=effective_document_id,
                filters={
                    "tenant_id": tenant_id,
                    "collection_id": collection_id,
                    "document_id": effective_document_id,
                },
            )

        store.add(
            embeddings,
            chunks,
            source_document=effective_document_id,
            metadata_list=metadata_list,
        )

    logger.info(
        "Indexed '%s': %d chunks via '%s' backend (tenant=%s collection=%s document=%s).",
        original_name,
        len(chunks),
        getattr(store, "backend", "faiss"),
        tenant_id,
        collection_id,
        effective_document_id,
    )

    return {"message": "Document processed successfully", "chunks": len(chunks)}


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Form("default"),
    collection_id: str = Form("default"),
    document_id: str = Form("default"),
    document_date: str | None = Form(None),
    author: str | None = Form(None),
    tag: str | None = Form(None),
    source_system: str | None = Form(None),
):
    """Upload and process a document.

    Steps:
    1. Save the uploaded file temporarily to disk.
    2. Extract text from the file using `extract_text`.
    3. Chunk the extracted text with `chunk_text`.
    4. Convert chunks to embeddings via `embed_text`.
    5. Create a `VectorStore` and add embeddings + chunks for retrieval.
    6. Remove the temporary file and return a success message.

    The function stores the created `VectorStore` in the module-level
    `vector_store` so the `/ask` endpoint can use it.
    """

    global vector_store

    logger.info("Upload request received: %s", file.filename)
    request_started_at = time.monotonic()

    # Save uploaded file to a temporary local path.
    file_path = f"temp_{file.filename}"
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    remove_temp_file = True

    try:
        try:
            file_size = int(getattr(file, "size", 0) or os.path.getsize(file_path))
        except OSError:
            file_size = 0

        should_queue = config.ASYNC_INGESTION_MIN_BYTES == 0 or file_size >= config.ASYNC_INGESTION_MIN_BYTES

        if should_queue:
            remove_temp_file = False
            job_id = enqueue_job(
                _process_upload_job,
                file_path,
                tenant_id,
                collection_id,
                document_id,
                file.filename,
                document_date,
                author,
                tag,
                source_system,
            )
            logger.info(
                "Queued '%s' for background ingestion (job=%s, tenant=%s collection=%s document=%s, size=%d bytes).",
                file.filename,
                job_id,
                tenant_id,
                collection_id,
                document_id,
                file_size,
            )
            response = {
                "message": "Document processing started in the background",
                "job_id": job_id,
                "status": "queued",
            }
            slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
            return response

        result = _process_upload_job(
            file_path,
            tenant_id,
            collection_id,
            document_id,
            file.filename,
            document_date,
            author,
            tag,
            source_system,
        )
        slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
        return result
    except Exception:
        slo_metrics.record_request(time.monotonic() - request_started_at, success=False)
        raise
    finally:
        if remove_temp_file and os.path.exists(file_path):
            os.remove(file_path)


@app.post("/upload-google-doc", response_model=IngestResponse)
async def upload_google_doc(req: GoogleDocIngestRequest):
    """Ingest a Google Doc by URL and index it in the vector store."""

    request_started_at = time.monotonic()
    try:
        text = extract_google_doc_text(req.google_doc_url)
        result = _index_text_content(
            text=text,
            tenant_id=req.tenant_id,
            collection_id=req.collection_id,
            document_id=req.document_id,
            original_name=req.google_doc_url,
            document_date=req.document_date,
            author=req.author,
            tag=req.tag,
            source_system=req.source_system,
        )
        slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
        return result
    except Exception:
        slo_metrics.record_request(time.monotonic() - request_started_at, success=False)
        raise


@app.post("/ask", response_model=AnswerResponse)
async def ask_question(req: QuestionRequest):
    """Answer a user question using the currently loaded vector store.

    If no document has been uploaded yet, returns a short message informing the
    caller. Otherwise, it retrieves relevant context from `vector_store`
    and delegates answer generation to `generate_answer`.
    """

    if not vector_store:
        return {"answer": "No document uploaded yet."}

    logger.info("Question received: %s", req.question)
    domain = classify_question_domain(req.question)
    with vector_store_lock:
        answer = generate_answer(
            req.question,
            vector_store,
            tenant_id=req.tenant_id,
            collection_id=req.collection_id,
            document_id=req.document_id,
            document_date=req.document_date,
            author=req.author,
            tag=req.tag,
            source_system=req.source_system,
        )
    logger.debug("Answer generated (%d chars).", len(answer))
    return {"answer": answer, "question_domain": domain}


@app.get("/question-domains", response_model=QuestionDomainCatalogResponse)
async def list_question_domains():
    """Return the question-domain taxonomy supported by this RAG QA system."""

    return {"domains": get_question_domain_catalog()}


@app.get("/ingestion-jobs/{job_id}")
async def get_ingestion_job(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/metrics")
async def get_metrics():
    return slo_metrics.snapshot()


@app.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest):
    feedback_id = feedback_store.add_feedback(req.model_dump())
    return {"feedback_id": feedback_id, "status": "recorded"}


@app.get("/feedback/summary")
async def feedback_summary():
    return feedback_store.summary()
