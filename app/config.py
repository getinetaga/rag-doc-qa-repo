"""Configuration and environment helpers for the RAG application.

This module centralizes configuration constants and the minimal logic
required to load local development secrets from a `.env` file. It is
intentionally lightweight and avoids additional dependencies: when a
`.env` file is present it will be read and values will be set into
the process environment only if they are not already defined.

Security note: Do NOT commit real secrets. Keep your `.env` in
`.gitignore` (the project already adds `.env` to ignore).
"""

import os


# OpenAI API key read from environment. Required for calls to OpenAI APIs.
# Example: set via environment variable: OPENAI_API_KEY="sk-..."
def _load_dotenv_if_present():
	"""Lightweight .env loader.

	Behavior:
	- Looks for `.env` in the current working directory and the project
     root (one level above this module).
	- Parses simple `KEY=VALUE` lines, ignoring blank lines and comments.
	- Does not overwrite environment variables that are already set.

	This helper intentionally avoids importing a third-party package such
	as `python-dotenv` to keep the project lightweight for local demos.
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
						# skip empty lines, comments, and malformed lines
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
			# Silent fallback: if reading .env fails, rely on actual environment
			continue


_load_dotenv_if_present()

# Read configuration values from the environment (or .env loaded above).
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Embedding model name (if you switch to OpenAI embeddings instead of the
# local SentenceTransformer this value will be used).
EMBEDDING_MODEL = "text-embedding-3-small"

# LLM model name used with the configured provider. Update as needed.
LLM_MODEL = "gpt-4o-mini"

# Provider for LLMs: 'openai' or 'huggingface' (default: openai)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")

# Optional Hugging Face Inference API key (used when LLM_PROVIDER == 'huggingface')
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# Chunking controls: number of characters per chunk and overlap in characters.
# These are used by `app/chunking.py` to split documents into retrievable pieces.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

# Number of top similar chunks to retrieve from the vector store for context.
TOP_K = 5
