"""
Configuration constants for the RAG application.

This module centralizes environment-driven settings and simple constants
used across the app (ingestion, embeddings, chunking, search and LLM).
Keep secrets like `OPENAI_API_KEY` out of source control and set them
via environment variables in production.
"""

import os

# OpenAI API key read from environment. Required for calls to OpenAI APIs.
# Example: set via environment variable: OPENAI_API_KEY="sk-..."
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Embedding model name (for OpenAI embeddings). Note: the repo currently
# uses a local SentenceTransformer for embeddings; if switching to OpenAI
# embeddings, use this value when calling the OpenAI embeddings endpoint.
EMBEDDING_MODEL = "text-embedding-3-small"

# LLM model name used with OpenAI ChatCompletion. Update per your subscription.
LLM_MODEL = "gpt-4o-mini"

# Chunking controls: number of characters per chunk and overlap in characters.
# These are used by `app/chunking.py` to split documents into retrievable pieces.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

# Number of top similar chunks to retrieve from the vector store for context.
TOP_K = 5
