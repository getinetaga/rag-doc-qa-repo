# Intelligent Document QA System (RAG-Based)

This repository demonstrates a small, modular Retrieval-Augmented
Generation (RAG) pipeline for asking natural-language questions about
content from many sources:

- **Direct uploads** — PDF, DOCX, TXT, and image OCR.
- **Opt-in AI image descriptions** — OpenAI visual interpretations, clearly
  marked unverified; separate from local OCR and disabled by default.
- **Google Docs** — fetched by shared URL.
- **SharePoint / OneDrive-for-Business** — fetched through Microsoft Graph.
- **SQL databases** — rows from a read-only `SELECT` (PostgreSQL or SQLite),
  serialized to text.

It includes:

- A FastAPI backend exposing `/upload`, `/upload-google-doc`, `/upload-sharepoint`,
  `/ingest-database`, `/ask`, and observability endpoints (`/metrics`, `/feedback`).
- An in-process Streamlit demo for local experimentation.
- Local embeddings via SentenceTransformers and a FAISS vector index.
- Optional `pgvector` / PostgreSQL backend for persistent storage or hybrid mirroring.
- Optional LLM backends: OpenAI (Responses API) or Hugging Face Inference API.
- Lightweight CI pipeline example in `Jenkinsfile`.

---

## Security and reliability setup

The API requires **per-user API keys and server-configured tenant/project grants**.
Configure the external `RAG_API_USERS_FILE` policy before starting the server.
There is no anonymous fallback. See [Security and reliability operations](docs/SECURITY_AND_RELIABILITY.md)
for key provisioning, roles, approved database sources, client sign-in, deployment
restrictions, and verification. Existing design reports describe historical
behavior; this operational guide describes the hardening changes.

Optional **private saved answers** are separate from caches/audit: explicit
opt-in, owner-only reads with current permissions, up to 30-day retention, and
whole-answer redaction on observed policy/index changes. Configure private
`ANSWER_RETENTION_DB` storage outside the repository; currently local FAISS only.
See the operational guide's **Private answer retention** section.

For photographs/diagrams, an operator can enable `IMAGE_DESCRIPTION_ENABLED=true`
and select `OPENAI_VISION_MODEL=gpt-4o-mini` with the existing `OPENAI_API_KEY`.
After choosing an image in the React app, select **AI visual description
(OpenAI)** before processing. This explicitly sends the selected image to OpenAI;
only use approved images. Tesseract is not required for that mode.
The description is shown immediately and indexed as unverified AI-derived text.
This does not add reliable engineering drawing/CAD/BIM understanding.
See **Image processing modes** in the operational guide for limits and privacy.

Uploads use private staging and scoped replacement. Jobs/feedback are access
controlled, and unsafe scope-dropping retrieval retries have been removed.
Hybrid retrieval is **not** implemented or enabled by these changes.

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

3. Configure personal API access (required) and provider keys (optional for LLM features)

First provision the external access policy described above and set
`RAG_API_USERS_FILE`. Use one API worker while jobs remain process-local.

Create a `.env` file in the repository root or set environment variables directly. Example `.env`:

```
OPENAI_API_KEY="sk-..."
HUGGINGFACE_API_KEY="hf_..."
LLM_PROVIDER=openai       # or huggingface
LLM_MODEL=gpt-4o-mini     # change to the model you want to use
VECTOR_DB_BACKEND=faiss   # faiss, pgvector, or hybrid
PGVECTOR_DSN=postgresql://postgres:postgres@localhost:5432/ragdb
PGVECTOR_TABLE_NAME=rag_embeddings

# SharePoint ingestion (/upload-sharepoint) — Entra ID app, app-only token:
SHAREPOINT_TENANT_ID=...
SHAREPOINT_CLIENT_ID=...
SHAREPOINT_CLIENT_SECRET=...

# Database ingestion uses approved source IDs; configure DSNs only on the server:
DB_INGESTION_DSN=postgresql://readonly:...@localhost:5432/appdb
DB_INGESTION_MAX_ROWS=5000
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

- POST `/upload` — multipart file upload (pdf/docx/txt/images). Builds an in-memory index.
- POST `/upload-google-doc` — admin+ingest only; Google Docs URL to fetch and index text.
- POST `/upload-sharepoint` — JSON body with a SharePoint file URL (or `drive_id`/`site_id` +
  `item_id`); admin+ingest only. Requires the `SHAREPOINT_*` env vars.
- POST `/ingest-database` — JSON body with an authorized `source_id`; connection,
  query/table, and maximum row count are defined by the operator, not the caller.
- POST `/ask` — JSON body `{ "question": "..." }`, returns `{ "answer": "..." }`.
- GET `/metrics`, POST `/feedback`, GET `/feedback/summary`, GET `/question-domains`,
  GET `/ingestion-jobs/{job_id}` — observability and async-ingestion status.

All ingestion endpoints accept the same optional scoping fields (`tenant_id`, `collection_id`,
`document_id`, `document_date`, `author`, `tag`, `source_system`).
Tenant/project selectors must match server grants; they do not establish access.
Use `Authorization: Bearer <personal-api-key>`. `GET /session` lists the caller's
permitted projects. Metrics are admin-only; job access and feedback are private.

6. Run the front end (production UI)

The production UI is a React + Vite + TypeScript app in [`frontend/`](frontend/) that talks to the
FastAPI backend.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173  (npm run build for a production bundle)
```

7. (Alternative) Run a Streamlit demo

`streamlit_demo.py` runs the pipeline in-process for trusted local experiments;
it bypasses API authentication. `streamlit_app.py` is the HTTP client and signs
in with a personal API key.

Both Streamlit entry points use explicit event handlers to keep session state predictable:
- file-selection change handlers clear stale document/chat state,
- process/submit handlers trigger upload and question requests,
- clear-history handlers reset prior answers without restarting the app.

```bash
streamlit run app/streamlit_demo.py --server.address 127.0.0.1
# or use the authenticated HTTP client:
streamlit run app/streamlit_app.py --server.address 127.0.0.1
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
	- `ingestion.py` — text extraction for uploads (pdf/docx/txt/image OCR), Google Docs, and
	  SharePoint files (Microsoft Graph, app-only token)
	- `db_ingestion.py` — SQL row-serialization ingestion (read-only `SELECT` → text; PostgreSQL / SQLite)
	- `chunking.py` — chunk-splitting utilities
	- `embeddings.py` — SentenceTransformers wrapper (lazy, thread-safe)
	- `vector_store.py` — FAISS / pgvector / hybrid vector store behind one wrapper
	- `rag.py` — retrieval + rerank + grounded LLM orchestration (OpenAI Responses / HF)
	- `retrieval_service.py`, `inference_service.py` — optional standalone services for the split topology
	- `slo_metrics.py`, `feedback_store.py`, `ingestion_jobs.py` — metrics, feedback, async-ingest queue
	- `config.py` — environment and configuration helpers
	- `streamlit_demo.py` — in-process demo UI
- `frontend/` — production UI (React + Vite + TypeScript); `npm run dev` / `npm run build`
- `docs/` — project documentation
	- `architecture.md` — architecture and flow details
	- `projectOverview.md` — consolidated project overview
	- `project-management/` — governance and implementation docs (test plan, DevOps, quality, AI integration)
- `tests/` — pytest suite for API, ingestion, database ingestion, vector store, and RAG pipeline
- `samples/` — sample input artifacts for experiments and local runs
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
