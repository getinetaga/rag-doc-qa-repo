# FastAPI App

from fastapi import FastAPI, UploadFile, File
import shutil
import os

from .ingestion import extract_text
from .chunking import chunk_text
from .embeddings import embed_text
from .vector_store import VectorStore
from .rag import generate_answer
from .schemas import QuestionRequest, AnswerResponse

app = FastAPI(title="RAG Document QA")

vector_store = None

@app.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    global vector_store

    file_path = f"temp_{file.filename}"
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    text = extract_text(file_path)
    chunks = chunk_text(text)
    embeddings = embed_text(chunks)

    vector_store = VectorStore(dim=len(embeddings[0]))
    vector_store.add(embeddings, chunks)

    os.remove(file_path)

    return {"message": "Document processed successfully"}

@app.post("/ask", response_model=AnswerResponse)
async def ask_question(req: QuestionRequest):
    if not vector_store:
        return {"answer": "No document uploaded yet."}

    answer = generate_answer(req.question, vector_store)
    return {"answer": answer}
