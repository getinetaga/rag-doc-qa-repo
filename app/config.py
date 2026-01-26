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
def _load_dotenv_if_present():
	"""Lightweight .env loader: read key=value pairs from a .env file if present
	in the working directory or the project root. This avoids adding an external
	dependency while allowing local development using a .env file.
	"""
	candidates = [
		os.path.join(os.getcwd(), ".env"),
		os.path.join(os.path.dirname(__file__), "..", ".env"),
	]

	for path in candidates:
		try:
			if os.path.exists(path):
				with open(path, "r", encoding="utf-8") as f:
					for raw in f:
						line = raw.strip()
						if not line or line.startswith("#") or "=" not in line:
							continue
						k, v = line.split("=", 1)
						k = k.strip()
						v = v.strip().strip('"').strip("'")
						# Do not overwrite existing environment variables
						if k and os.getenv(k) is None:
							os.environ[k] = v
				break
		except Exception:
			# Fail silently — fallback to existing environment variables
			continue


# Load .env (if present) so subsequent os.getenv calls pick up keys.
_load_dotenv_if_present()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Embedding model name (for OpenAI embeddings). Note: the repo currently
# uses a local SentenceTransformer for embeddings; if switching to OpenAI
# embeddings, use this value when calling the OpenAI embeddings endpoint.
EMBEDDING_MODEL = "text-embedding-3-small"

# LLM model name used with OpenAI ChatCompletion. Update per your subscription.
LLM_MODEL = "gpt-4o-mini"

# Provider for LLMs: 'openai' or 'huggingface'
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

# Optional Hugging Face Inference API key (if using Hugging Face as provider)
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# Chunking controls: number of characters per chunk and overlap in characters.
# These are used by `app/chunking.py` to split documents into retrievable pieces.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

# Number of top similar chunks to retrieve from the vector store for context.
TOP_K = 5
