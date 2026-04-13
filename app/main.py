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
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile

from . import config
from .chunking import chunk_text
from .embeddings import embed_text, get_model
from .ingestion import extract_text
from .rag import generate_answer
from .schemas import AnswerResponse, QuestionRequest
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

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
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

    # Save uploaded file to a local temporary .Where is the file saved? 
    # It is saved in the current working directory with a name like "temp_<original_filename>".
    file_path = f"temp_{file.filename}"
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Build the retrieval index from the uploaded document. 
    # How to access the file? The file is accessed using the `file_path` variable, which points to the temporary file saved on disk.  
    text = extract_text(file_path)
    chunks = chunk_text(text)
    embeddings = embed_text(chunks)

    # Initialize the vector store for the current upload and replace any
    # previous persisted document chunks so answers stay focused and don't repeat.
    vector_store = VectorStore(dim=len(embeddings[0]))
    clear = getattr(vector_store, "clear", None)
    if callable(clear):
        clear()
    vector_store.add(embeddings, chunks)

    # Clean up the temporary file
    os.remove(file_path)

    logger.info(
        "Indexed '%s': %d chunks via '%s' backend.",
        file.filename,
        len(chunks),
        getattr(vector_store, "backend", "faiss"),
    )
    return {"message": "Document processed successfully"}


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
    answer = generate_answer(req.question, vector_store)
    logger.debug("Answer generated (%d chars).", len(answer))
    return {"answer": answer}
