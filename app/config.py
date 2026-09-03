"""Configuration and environment helpers for the RAG application.

This module centralizes configuration constants and the minimal logic
required to load local development secrets from a `.env` file. It is
intentionally lightweight and avoids additional dependencies: when a
`.env` file is present it will be read and values will be set into
the process environment only if they are not already defined.

Security note: Do NOT commit real secrets. Keep your `.env` in
`.gitignore` (the project already adds `.env` to ignore).
"""

import os #OS module is used for environment variable access and file path handling.


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
						k, v = line.split("=", 1)# Split only on the first '=' to allow values with '=' in them
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

# Provider for LLMs: 'openai', 'huggingface', or 'auto' (default: openai)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()

# Optional Hugging Face Inference API key (used when LLM_PROVIDER == 'huggingface')
HUGGINGFACE_API_KEY = (
	os.getenv("HUGGINGFACE_API_KEY")
	or os.getenv("HF_TOKEN")
	or os.getenv("HUGGINGFACEHUB_API_TOKEN")
)

# Provider-specific model names.
# LLM_MODEL remains as backward-compatible alias and provider-specific default.
OPENAI_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", os.getenv("LLM_MODEL", "gpt-4o-mini"))
HUGGINGFACE_LLM_MODEL = os.getenv(
	"HUGGINGFACE_LLM_MODEL", os.getenv("LLM_MODEL", "google/flan-t5-base")
)

if LLM_PROVIDER == "huggingface":
	LLM_MODEL = HUGGINGFACE_LLM_MODEL
else:
	LLM_MODEL = OPENAI_LLM_MODEL

# Embedding vector size used by local sentence-transformers model.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))

# Chunking controls: number of characters per chunk and overlap in characters.
# These are used by `app/chunking.py` to split documents into retrievable pieces.
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100

# Number of top similar chunks to retrieve from the vector store for context.
TOP_K = 5

# Number of candidate chunks to fetch before reranking. The reranker keeps
# the best TOP_K chunks after reordering by question/context relevance.
RETRIEVAL_RERANK_POOL_SIZE = int(os.getenv("RETRIEVAL_RERANK_POOL_SIZE", str(max(TOP_K * 3, TOP_K + 5))))

# Horizontal scaling / service isolation controls.
# API_WORKERS governs the FastAPI worker count in containerized deployments.
# The optional service URLs let the API route retrieval and inference to
# dedicated services backed by a shared persistent vector store.
API_WORKERS = int(os.getenv("API_WORKERS", "1"))
RETRIEVAL_SERVICE_URL = os.getenv("RETRIEVAL_SERVICE_URL", "").rstrip("/")
INFERENCE_SERVICE_URL = os.getenv("INFERENCE_SERVICE_URL", "").rstrip("/")

# Large uploads are pushed into an asynchronous background job when they
# exceed this size (in bytes). Set to 0 to process all uploads asynchronously.
ASYNC_INGESTION_MIN_BYTES = int(os.getenv("ASYNC_INGESTION_MIN_BYTES", "200000"))

# Hard upload size cap in bytes (default: 200 MiB).
MAX_UPLOAD_FILE_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_FILE_SIZE_BYTES", "209715200"))

# Vector database backend selection.
# Supported values: 'faiss', 'pgvector', or 'hybrid'.
# Default behavior: prefer persistent pgvector when a DSN is configured,
# otherwise fall back to local in-memory FAISS.
_default_vector_backend = "pgvector" if os.getenv("PGVECTOR_DSN") else "faiss"
VECTOR_DB_BACKEND = os.getenv("VECTOR_DB_BACKEND", _default_vector_backend).lower()

# PostgreSQL / pgvector settings used when VECTOR_DB_BACKEND is 'pgvector'
# or 'hybrid'. Example:
#   PGVECTOR_DSN=postgresql://postgres:postgres@localhost:5432/ragdb
PGVECTOR_DSN = os.getenv("PGVECTOR_DSN")
PGVECTOR_TABLE_NAME = os.getenv("PGVECTOR_TABLE_NAME", "rag_embeddings")
PGVECTOR_PRIMARY_SEARCH = os.getenv("PGVECTOR_PRIMARY_SEARCH", "pgvector").lower()

# Microsoft Graph / SharePoint ingestion.
# Uses the app-only (client-credentials) OAuth2 flow: register an Entra ID
# application, grant it the application permissions Sites.Read.All and
# Files.Read.All, and record admin consent. Because the token is app-only,
# retrieval is NOT permission-trimmed per end user — the app can read every
# site it has been granted. Add delegated auth if per-user access control is
# required.
SHAREPOINT_TENANT_ID = os.getenv("SHAREPOINT_TENANT_ID") or os.getenv("AZURE_TENANT_ID")
SHAREPOINT_CLIENT_ID = os.getenv("SHAREPOINT_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
SHAREPOINT_CLIENT_SECRET = (
    os.getenv("SHAREPOINT_CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET")
)

# Graph endpoints are overridable for sovereign/national clouds.
GRAPH_BASE_URL = os.getenv("GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0").rstrip("/")
GRAPH_AUTHORITY = os.getenv("GRAPH_AUTHORITY", "https://login.microsoftonline.com").rstrip("/")

# Hard cap on a single SharePoint download (default: 200 MiB), mirroring
# MAX_UPLOAD_FILE_SIZE_BYTES for direct uploads.
SHAREPOINT_MAX_DOWNLOAD_BYTES = int(
    os.getenv("SHAREPOINT_MAX_DOWNLOAD_BYTES", str(209715200))
)

# Database (SQL) row-serialization ingestion (/ingest-database).
# Runs a single read-only SELECT against the target database and turns each
# returned row into a line of text that is then chunked, embedded, and indexed
# like any other document. Only the 'postgresql' / 'postgres' and 'sqlite'
# connection schemes are accepted. A request may carry its own
# connection_string; when it does not, DB_INGESTION_DSN is used.
DB_INGESTION_DSN = os.getenv("DB_INGESTION_DSN")
DB_INGESTION_MAX_ROWS = int(os.getenv("DB_INGESTION_MAX_ROWS", "5000"))
DB_INGESTION_MAX_CELL_CHARS = int(os.getenv("DB_INGESTION_MAX_CELL_CHARS", "2000"))
DB_INGESTION_STATEMENT_TIMEOUT_MS = int(
    os.getenv("DB_INGESTION_STATEMENT_TIMEOUT_MS", "15000")
)
