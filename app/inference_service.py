"""Dedicated inference service for the RAG application.

This service isolates provider calls from retrieval work. It accepts a
prompt and returns a single generated answer using the configured local or
external LLM provider.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from . import config
from .embeddings import get_model
from .rag import _call_fastest_provider, _call_huggingface, _call_openai

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


class InferenceRequest(BaseModel):
    prompt: str


class InferenceResponse(BaseModel):
    answer: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Inference service starting — provider: %s", getattr(config, "LLM_PROVIDER", "openai"))
    get_model()
    logger.info("Embedding model pre-loaded for inference service.")
    yield
    logger.info("Inference service shutting down.")


app = FastAPI(title="RAG Inference Service", lifespan=lifespan)


@app.post("/generate", response_model=InferenceResponse)
async def generate(req: InferenceRequest):
    if config.LLM_PROVIDER == "huggingface":
        answer = _call_huggingface(config.HUGGINGFACE_LLM_MODEL, req.prompt)
    elif config.LLM_PROVIDER == "auto":
        answer = _call_fastest_provider(req.prompt)
    else:
        answer = _call_openai(config.OPENAI_LLM_MODEL, req.prompt)

    return {"answer": answer}
