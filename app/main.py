"""Simple FastAPI app exposing two endpoints for a RAG (Retrieval-Augmented Generation)
document question-answering pipeline.

Endpoints:
- POST /upload : Accepts a file upload, extracts text, chunks it, embeds chunks and
  stores them in an in-memory vector store for later retrieval.
- POST /ask    : Accepts a question and returns an answer generated using the
  previously built vector store.

This module wires together the smaller pipeline components located in the `app`
package: `ingestion`, `chunking`, `embeddings`, `vector_store`, and `rag`.
"""

import os
import shutil

from fastapi import FastAPI, File, UploadFile

from .chunking import chunk_text
from .embeddings import embed_text
from .ingestion import extract_text
from .rag import generate_answer
from .schemas import AnswerResponse, QuestionRequest
from .vector_store import VectorStore

# Initialize FastAPI application
app = FastAPI(title="RAG Document QA")

# A simple in-memory reference to a VectorStore instance. It is created when
# a document is uploaded and kept in module scope for subsequent /ask calls.
# In a production system this would be replaced with a persistent store or
# a scoped dependency-injected object.
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

    # Initialize vector store with the embedding dimensionality and add data
    vector_store = VectorStore(dim=len(embeddings[0]))
    vector_store.add(embeddings, chunks)

    # Clean up the temporary file
    os.remove(file_path)

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

    answer = generate_answer(req.question, vector_store)
    return {"answer": answer}
