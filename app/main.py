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
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import answer_store, config
from .auth import (
    ApiUser, authenticate_before_body, authorize_current_user, authorize_scope, approved_database_source, database_connection,
    get_current_user, load_policy, require_role,
)
from .chunking import chunk_text
from .db_ingestion import extract_database_text
from .embeddings import embed_text, get_model
from .ingestion import _IMAGE_SUFFIXES, _SUPPORTED_SUFFIXES, _extract_google_doc_id, extract_google_doc_text, extract_sharepoint_text, extract_text
from .image_description import DESCRIPTION_WARNING, MAX_IMAGE_BYTES, describe_image, ensure_description_enabled
from .ingestion_errors import IngestionError
from .ingestion_jobs import enqueue_job, ensure_worker_started, get_job
from .rag import generate_answer
from .rag import classify_question_domain, get_question_domain_catalog
from . import slo_metrics
from . import feedback_store
from .schemas import (
    AnswerResponse,
    DatabaseIngestRequest,
    FeedbackRequest,
    FeedbackResponse,
    GoogleDocIngestRequest,
    IngestResponse,
    QuestionDomainCatalogResponse,
    QuestionRequest,
    SharePointIngestRequest,
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
    load_policy()
    if config.API_WORKERS != 1:
        raise RuntimeError("The in-process job queue requires API_WORKERS=1.")
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
            logger.error("Vector store startup initialization failed (%s).", type(exc).__name__)
            raise
    retention_stop = threading.Event()
    retention_worker = None
    if config.ANSWER_RETENTION_DB:
        _maintain_answers()
        retention_worker = threading.Thread(
            target=_answer_maintenance_loop, args=(retention_stop,), daemon=True,
            name="answer-retention",
        )
        retention_worker.start()
    try:
        yield
    finally:
        retention_stop.set()
        if retention_worker is not None:
            retention_worker.join(timeout=10)
    # --- shutdown ---
    logger.info("RAG Document QA API shutting down.")
    if vector_store is not None:
        vector_store.close()
        logger.info("Vector store connection closed.")


# Initialize FastAPI application
app = FastAPI(
    title="RAG Document QA", lifespan=lifespan,
    dependencies=[Depends(get_current_user)],
)
app.middleware("http")(authenticate_before_body)


@app.exception_handler(IngestionError)
async def safe_ingestion_error(request, exc: IngestionError):
    logger.warning("Ingestion rejected (%s).", exc.code)
    return JSONResponse(
        {"detail": exc.public_message, "error_code": exc.code}, status_code=exc.status_code,
    )


@app.get("/ingestion-capabilities")
def ingestion_capabilities():
    return {
        "image_description_enabled": bool(config.IMAGE_DESCRIPTION_ENABLED and config.OPENAI_API_KEY),
        "image_description_provider": "OpenAI",
    }


@app.middleware("http")
async def prevent_answer_caching(request, call_next):
    response = await call_next(request)
    if request.url.path in {"/ask", "/upload", "/answers", "/answers-policy"} or request.url.path.startswith(("/answers/", "/ingestion-jobs/")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response

# Enable CORS for TypeScript frontend and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://localhost:8501",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# A module-level reference to the currently active VectorStore instance. It is
# created when a document is uploaded and kept in module scope for subsequent
# /ask calls. Depending on configuration it can use FAISS, pgvector, or a
# hybrid combination of both.
vector_store = None
vector_store_lock = threading.RLock()
_answer_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_ANSWERS)


@contextmanager
def _retention_snapshot():
    with vector_store_lock:
        store = vector_store
        if (
            not isinstance(store, VectorStore) or store.backend != "faiss"
            or config.RETRIEVAL_SERVICE_URL
        ):
            yield None
            return
        with store.read_snapshot():
            identity = {
                "policy": load_policy().model_dump(mode="json"),
                "index": store.cache_namespace,
                "revision": store.revision,
            }
            yield hashlib.sha256(
                json.dumps(identity, sort_keys=True).encode("utf-8")
            ).hexdigest()


def _maintain_answers():
    try:
        with _retention_snapshot() as stamp:
            answer_store.maintain(stamp)
    except HTTPException:
        # Policy outages must not extend the lifetime of sensitive stored payloads.
        answer_store.maintain(None)
        raise


def _answer_maintenance_loop(stop: threading.Event):
    while not stop.wait(60):
        try:
            _maintain_answers()
        except HTTPException:
            logger.error("Answer retention maintenance failed; operator action required.")


@app.get("/answers-policy")
def answer_retention_policy():
    with _retention_snapshot() as stamp:
        return {
            "enabled": bool(config.ANSWER_RETENTION_DB and stamp),
            "retention_days": config.ANSWER_RETENTION_DAYS,
        }


@app.get("/answers")
def list_saved_answers(
    tenant_id: str = "default", collection_id: str = "default",
    user: ApiUser = Depends(get_current_user),
):
    scope = authorize_scope(user, tenant_id, collection_id)
    with _retention_snapshot() as stamp:
        answer_store.maintain(stamp)
        authorize_current_user(user.user_id, scope.tenant_id, scope.collection_id)
        return answer_store.list_answers(user.user_id, scope.tenant_id, scope.collection_id)


@app.get("/answers/{answer_id}")
def read_saved_answer(answer_id: str, user: ApiUser = Depends(get_current_user)):
    with _retention_snapshot() as stamp:
        answer_store.maintain(stamp)
        record = answer_store.read(answer_id, user.user_id)
        authorize_current_user(user.user_id, record["tenant_id"], record["collection_id"])
        if record["status"] != "available":
            raise HTTPException(410, "Saved answer was redacted because access or sources changed.")
        return {
            key: record[key]
            for key in ("id", "question", "answer", "created_at", "expires_at", "status")
        }


@app.delete("/answers/{answer_id}")
def delete_saved_answer(answer_id: str, user: ApiUser = Depends(get_current_user)):
    # Owners may erase their own retained data even after project access is removed.
    answer_store.delete(answer_id, user.user_id)
    return {"status": "deleted"}


def _resolve_document_id(document_id: str, original_name: str) -> str:
    """Resolve a stable document id when callers pass the default placeholder."""

    cleaned = str(document_id or "").strip()
    if cleaned and cleaned.lower() != "default":
        return cleaned

    if str(original_name).startswith(("http://", "https://", "sharepoint:")):
        google_id = _extract_google_doc_id(str(original_name))
        identity = f"google_docs:{google_id}" if google_id else str(original_name)
        return "source_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    stem = Path(str(original_name or "document")).stem
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_").lower()
    return slug or "document"


def _ensure_vector_store(dim: int):
    """Lazily initialize a shared vector store instance."""

    global vector_store
    with vector_store_lock:
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
    owner_id: str | None = None,
    image_mode: Literal["ocr", "describe"] = "ocr",
):
    """Process an uploaded file and update the scoped vector index."""

    try:
        if owner_id is not None:
            authorize_current_user(owner_id, tenant_id, collection_id, role="ingest")
        if image_mode == "describe":
            if owner_id is None:
                raise HTTPException(403, "Image description requires an authenticated owner.")
            if not _answer_slots.acquire(blocking=False):
                raise IngestionError("image_description_busy")
            try:
                text = describe_image(
                    file_path,
                    before_dispatch=lambda: authorize_current_user(
                        owner_id, tenant_id, collection_id, role="ingest",
                    ),
                )
            finally:
                _answer_slots.release()
        else:
            text = extract_text(file_path)
        result = _index_text_content(
            text=text,
            tenant_id=tenant_id,
            collection_id=collection_id,
            document_id=document_id,
            original_name=original_name,
            document_date=document_date,
            author=author,
            tag=tag,
            source_system=source_system,
            owner_id=owner_id,
            content_kind="ai_image_description" if image_mode == "describe" else None,
        )
        if image_mode == "describe":
            result.update(image_description=text, content_kind="ai_image_description")
        return result
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
    owner_id: str | None = None,
    content_kind: str | None = None,
):
    """Chunk, embed, and index text content in the scoped vector store."""

    effective_document_id = _resolve_document_id(document_id, original_name)

    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("No extractable text content was found.")
    if content_kind == "ai_image_description":
        chunks = [f"{DESCRIPTION_WARNING}\n\n{chunk}" for chunk in chunks]

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
    if content_kind:
        metadata_base["content_kind"] = content_kind
        metadata_base["description_model"] = config.OPENAI_VISION_MODEL
    metadata_list = [dict(metadata_base) for _ in chunks]

    with vector_store_lock:
        if owner_id is not None:
            authorize_current_user(owner_id, tenant_id, collection_id, role="ingest")
        store.replace(
            embeddings,
            chunks,
            source_document=effective_document_id,
            metadata_list=metadata_list,
            filters={
                "tenant_id": tenant_id,
                "collection_id": collection_id,
                "document_id": effective_document_id,
            },
        )

    logger.info(
        "Indexed %d chunks via '%s' backend (tenant=%s collection=%s).",
        len(chunks),
        getattr(store, "backend", "faiss"),
        tenant_id,
        collection_id,
    )

    return {"message": "Document processed successfully", "chunks": len(chunks)}


@app.post("/upload")
def upload_document(
    file: UploadFile = File(...),
    tenant_id: str = Form("default"),
    collection_id: str = Form("default"),
    document_id: str = Form("default"),
    document_date: str | None = Form(None),
    author: str | None = Form(None),
    tag: str | None = Form(None),
    source_system: str | None = Form(None),
    image_mode: Literal["ocr", "describe"] = Form("ocr"),
    user: ApiUser = Depends(get_current_user),
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

    scope = authorize_scope(user, tenant_id, collection_id, role="ingest")
    tenant_id, collection_id = scope.tenant_id, scope.collection_id
    request_started_at = time.monotonic()
    suffix = Path((file.filename or "").replace("\\", "/")).suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise HTTPException(422, "Unsupported file type.")
    if image_mode == "describe":
        if suffix not in _IMAGE_SUFFIXES:
            raise HTTPException(422, "AI visual description is available only for image files.")
        ensure_description_enabled()

    declared_size = int(getattr(file, "size", 0) or 0)
    if declared_size and declared_size > config.MAX_UPLOAD_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large. Maximum allowed size is "
                f"{config.MAX_UPLOAD_FILE_SIZE_BYTES} bytes."
            ),
        )
    if image_mode == "describe" and declared_size > MAX_IMAGE_BYTES:
        raise IngestionError("image_too_large")

    staging = tempfile.NamedTemporaryFile(prefix="rag-upload-", suffix=suffix, delete=False)
    file_path = staging.name
    remove_temp_file = True

    try:
        file_size = 0
        with staging:
            while chunk := file.file.read(64 * 1024):
                file_size += len(chunk)
                if file_size > config.MAX_UPLOAD_FILE_SIZE_BYTES:
                    raise HTTPException(413, "File exceeds the upload size limit.")
                if image_mode == "describe" and file_size > MAX_IMAGE_BYTES:
                    raise IngestionError("image_too_large")
                staging.write(chunk)

        should_queue = config.ASYNC_INGESTION_MIN_BYTES == 0 or file_size >= config.ASYNC_INGESTION_MIN_BYTES

        if should_queue:
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
                job_owner=user.user_id,
                job_scope=(tenant_id, collection_id),
                owner_id=user.user_id,
                image_mode=image_mode,
            )
            remove_temp_file = False
            logger.info(
                "Queued background ingestion (job=%s, size=%d bytes).",
                job_id,
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
            owner_id=user.user_id,
            image_mode=image_mode,
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
def upload_google_doc(req: GoogleDocIngestRequest, user: ApiUser = Depends(get_current_user)):
    """Ingest a Google Doc by URL and index it in the vector store."""

    scope = authorize_scope(user, req.tenant_id, req.collection_id, role="ingest")
    require_role(user, "admin")
    request_started_at = time.monotonic()
    try:
        text = extract_google_doc_text(req.google_doc_url)
        result = _index_text_content(
            text=text,
            tenant_id=scope.tenant_id,
            collection_id=scope.collection_id,
            document_id=req.document_id,
            original_name=req.google_doc_url,
            document_date=req.document_date,
            author=req.author,
            tag=req.tag,
            source_system=req.source_system,
            owner_id=user.user_id,
        )
        slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
        return result
    except Exception:
        slo_metrics.record_request(time.monotonic() - request_started_at, success=False)
        raise


@app.post("/upload-sharepoint", response_model=IngestResponse)
def upload_sharepoint(req: SharePointIngestRequest, user: ApiUser = Depends(get_current_user)):
    """Ingest a SharePoint / OneDrive-for-Business document via Microsoft Graph.

    Accepts either a shareable ``sharepoint_url`` or an ``item_id`` plus
    ``drive_id`` / ``site_id``. The file is downloaded with an app-only Graph
    token, text-extracted, chunked, embedded, and indexed exactly like a direct
    upload. Retrieval is not permission-trimmed per end user — see
    ``app/config.py`` for the auth caveat.
    """

    scope = authorize_scope(user, req.tenant_id, req.collection_id, role="ingest")
    require_role(user, "admin")
    request_started_at = time.monotonic()
    try:
        text = extract_sharepoint_text(
            req.sharepoint_url,
            site_id=req.site_id,
            drive_id=req.drive_id,
            item_id=req.item_id,
        )
        original_name = req.sharepoint_url or f"sharepoint:{req.site_id}:{req.drive_id}:{req.item_id}"
        result = _index_text_content(
            text=text,
            tenant_id=scope.tenant_id,
            collection_id=scope.collection_id,
            document_id=req.document_id,
            original_name=original_name,
            document_date=req.document_date,
            author=req.author,
            tag=req.tag,
            source_system=req.source_system,
            owner_id=user.user_id,
        )
        slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
        return result
    except Exception:
        slo_metrics.record_request(time.monotonic() - request_started_at, success=False)
        raise


@app.post("/ingest-database", response_model=IngestResponse)
def ingest_database(req: DatabaseIngestRequest, user: ApiUser = Depends(get_current_user)):
    """Ingest rows from a SQL database via a single read-only ``SELECT``.

    The source grant, connection environment-variable name and fixed query/table
    come from the server access policy, never from caller-selected SQL or paths.
    """

    scope = authorize_scope(user, req.tenant_id, req.collection_id, role="ingest")
    if not req.source_id:
        raise HTTPException(403, "Use an administrator-approved source_id.")
    source = approved_database_source(user, req.source_id, scope)
    connection = database_connection(source)
    row_limit = min(source.max_rows, config.DB_INGESTION_MAX_ROWS)
    if req.max_rows is not None:
        if req.max_rows < 1:
            raise HTTPException(422, "max_rows must be positive.")
        row_limit = min(row_limit, req.max_rows)
    request_started_at = time.monotonic()
    try:
        text = extract_database_text(
            connection_string=connection,
            query=source.query,
            table=source.table,
            max_rows=row_limit,
        )
        original_name = req.source_id
        result = _index_text_content(
            text=text,
            tenant_id=scope.tenant_id,
            collection_id=scope.collection_id,
            document_id=req.document_id,
            original_name=original_name,
            document_date=req.document_date,
            author=req.author,
            tag=req.tag,
            source_system=req.source_system,
            owner_id=user.user_id,
        )
        slo_metrics.record_request(time.monotonic() - request_started_at, success=True)
        return result
    except Exception:
        slo_metrics.record_request(time.monotonic() - request_started_at, success=False)
        raise


@app.post("/ask", response_model=AnswerResponse)
def ask_question(req: QuestionRequest, user: ApiUser = Depends(get_current_user)):
    """Answer a user question using the currently loaded vector store.

    If no document has been uploaded yet, returns a short message informing the
    caller. Otherwise, it retrieves relevant context from `vector_store`
    and delegates answer generation to `generate_answer`.
    """

    scope = authorize_scope(user, req.tenant_id, req.collection_id)
    retention_stamp = None
    if req.retain_answer:
        if not config.ANSWER_RETENTION_DB:
            raise HTTPException(503, "Private answer storage is not configured.")
        with _retention_snapshot() as retention_stamp:
            if retention_stamp is None:
                raise HTTPException(409, "Answer retention requires local FAISS retrieval.")
            answer_store.maintain(retention_stamp)
    with vector_store_lock:
        store = vector_store
    if store is None:
        return {"answer": "No document uploaded yet."}

    if not _answer_slots.acquire(blocking=False):
        logger.warning("Question rejected: concurrent answer capacity reached.")
        slo_metrics.record_request(0.0, success=False)
        raise HTTPException(
            status_code=503,
            detail="Question capacity reached. Please retry shortly.",
            headers={"Retry-After": "1"},
        )
    logger.info("Question received for an authorized project.")
    try:
        domain = classify_question_domain(req.question)
        answer = generate_answer(
            req.question,
            store,
            tenant_id=scope.tenant_id,
            collection_id=scope.collection_id,
            document_id=req.document_id,
            document_date=req.document_date,
            author=req.author,
            tag=req.tag,
            source_system=req.source_system,
        )
        authorize_current_user(user.user_id, scope.tenant_id, scope.collection_id)
        retained = {}
        if req.retain_answer:
            with _retention_snapshot() as current_stamp:
                if current_stamp is None or current_stamp != retention_stamp:
                    answer_store.maintain(current_stamp)
                    raise HTTPException(409, "Access or sources changed. Ask again before saving.")
                retained = answer_store.save(
                    user.user_id, scope.tenant_id, scope.collection_id,
                    req.question, answer, current_stamp,
                )
    finally:
        _answer_slots.release()
    logger.debug("Answer generated (%d chars).", len(answer))
    return {"answer": answer, "question_domain": domain, **retained}


@app.get("/question-domains", response_model=QuestionDomainCatalogResponse)
async def list_question_domains():
    """Return the question-domain taxonomy supported by this RAG QA system."""

    return {"domains": get_question_domain_catalog()}


@app.get("/ingestion-jobs/{job_id}")
async def get_ingestion_job(job_id: str, user: ApiUser = Depends(get_current_user)):
    job = get_job(job_id)
    if job is None or job.get("owner_id") != user.user_id:
        raise HTTPException(status_code=404, detail="Job not found")
    authorize_scope(
        user, job.get("tenant_id"), job.get("collection_id"),
        role="ingest" if "ingest" in user.roles else "read",
    )
    return {key: value for key, value in job.items() if key != "owner_id"}


@app.get("/metrics")
async def get_metrics(user: ApiUser = Depends(get_current_user)):
    require_role(user, "admin")
    return slo_metrics.snapshot()


@app.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(req: FeedbackRequest, user: ApiUser = Depends(get_current_user)):
    scope = authorize_scope(user, req.tenant_id, req.collection_id)
    entry = {**req.model_dump(), **scope.model_dump(), "owner_id": user.user_id}
    feedback_id = feedback_store.add_feedback(entry)
    return {"feedback_id": feedback_id, "status": "recorded"}


@app.get("/feedback/summary")
async def feedback_summary(user: ApiUser = Depends(get_current_user)):
    require_role(user, "read")
    return feedback_store.summary(owner_id=user.user_id, scopes=user.scopes)


@app.get("/session")
def session(user: ApiUser = Depends(get_current_user)):
    return {
        "user_id": user.user_id,
        "roles": sorted(user.roles),
        "scopes": [scope.model_dump() for scope in user.scopes],
    }
