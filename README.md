# Intelligent Document QA System (RAG-Based)

This repository demonstrates a small, modular Retrieval-Augmented
Generation (RAG) pipeline for asking natural-language questions about
uploaded documents (PDF, DOCX, TXT). It includes:

- A FastAPI backend exposing `/upload` and `/ask` endpoints.
- An in-process Streamlit demo for local experimentation.
- Local embeddings via SentenceTransformers and a FAISS vector index.
- Optional `pgvector` / PostgreSQL backend for persistent storage or hybrid mirroring.
- Optional LLM backends: OpenAI (Responses API) or Hugging Face Inference API.
- Lightweight CI pipeline example in `Jenkinsfile`.

---

## Quickstart (local development)

Prerequisites:

- Python 3.10+ (3.12 tested in CI)
- git, Docker (optional for the image build)
- Recommended: create a virtual environment

1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate    # macOS / Linux
.venv\Scripts\activate     # Windows (PowerShell)
```

2. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

3. Configure API keys (optional for LLM features)

Create a `.env` file in the repository root or set environment variables directly. Example `.env`:

```
OPENAI_API_KEY="sk-..."
HUGGINGFACE_API_KEY="hf_..."
LLM_PROVIDER=openai       # or huggingface
LLM_MODEL=gpt-4o-mini     # change to the model you want to use
VECTOR_DB_BACKEND=faiss   # faiss, pgvector, or hybrid
PGVECTOR_DSN=postgresql://postgres:postgres@localhost:5432/ragdb
PGVECTOR_TABLE_NAME=rag_embeddings
```

The project includes a lightweight `.env` loader in [app/config.py](app/config.py) that will populate environment variables if they are not already set. Do NOT commit real secrets.

4. Initialize the pgvector table (optional, only if using `pgvector` or `hybrid`)

```bash
psql "$PGVECTOR_DSN" -f scripts/create_pgvector_table.sql
```

5. Run the FastAPI server

```bash
uvicorn app.main:app --reload
```

API endpoints:

- POST `/upload` — multipart file upload (pdf/docx/txt). Builds an in-memory index.
- POST `/ask` — JSON body `{ "question": "..." }`, returns `{ "answer": "..." }`.

5. (Alternative) Run the Streamlit in-process demo

The repository contains a simple demo UI you can run locally. It runs the pipeline in-process (ingest → index → ask).

Both Streamlit entry points use explicit event handlers to keep session state predictable:
- file-selection change handlers clear stale document/chat state,
- process/submit handlers trigger upload and question requests,
- clear-history handlers reset prior answers without restarting the app.

```bash
streamlit run app/streamlit_demo.py
# or use the root demo: streamlit run streamlit_app.py
```

---

## Running Tests

The project includes a small test suite using `pytest` and `fastapi.testclient`.

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

Notes:
- Tests use `pytest`'s `monkeypatch` to stub out heavy operations (embedding/model calls) so they run quickly.

---

## Project Layout

- `app/` — application modules
	- `main.py` — FastAPI app and endpoints
	- `ingestion.py` — document text extraction helpers (pdf/docx/txt)
	- `chunking.py` — chunk-splitting utilities
	- `embeddings.py` — SentenceTransformers wrapper (lazy, thread-safe)
	- `vector_store.py` — minimal FAISS-backed in-memory store
	- `rag.py` — retrieval + LLM orchestration (OpenAI Responses / HF)
	- `config.py` — environment and configuration helpers
	- `streamlit_demo.py` — in-process demo UI
- `tests/` — pytest suite for API, ingestion, and RAG pipeline
- `requirements.txt` — Python deps
- `Jenkinsfile` — CI pipeline example

---

## CI / Deployment

The included `Jenkinsfile` demonstrates a simple declarative pipeline:
- cross-platform virtualenv creation
- dependency install
- run tests
- optional Docker image build

Customize the pipeline to match your CI/CD environment and secrets handling.

To build the Docker image locally:

```bash
docker build -t rag-doc-qa:latest .
```

---

## Troubleshooting & Notes

- If sentence-transformers downloads the model on first run, it may take time and require network access.
- If you see errors from the OpenAI client such as "Client.init() got an unexpected keyword argument 'proxies'", check the `openai` and `httpx` versions. The repository expects `openai>=1.0.0` and `httpx` compatible with it (e.g., `httpx>=0.23,<1.0`). Adjust versions in your environment if needed.
- For Windows agents, the `Jenkinsfile` branches commands appropriately; ensure Docker is available when enabling the Docker stage.

---

## Contributing

Contributions welcome — please open issues or pull requests. Prefer small, focused changes with tests for new behavior.

---

## License

This repository is provided as an example; add an appropriate license file if you intend to open-source the project.
