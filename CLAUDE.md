# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A modular Retrieval-Augmented Generation (RAG) pipeline for question-answering over uploaded
documents (PDF, DOCX, TXT, image OCR) and Google Docs. It ships as a FastAPI service plus an
in-process Streamlit demo, with pluggable vector backends (FAISS / pgvector) and LLM providers
(OpenAI / Hugging Face).

## Commands

Environment (Windows / PowerShell is the primary dev environment):

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt         # runtime deps
pip install -r requirements-dev.txt     # black, isort, flake8, mypy, pytest-cov, pre-commit
```

Run:

```bash
uvicorn app.main:app --reload                 # FastAPI API on :8000
streamlit run app/streamlit_demo.py           # in-process demo UI (also: streamlit run streamlit_app.py)
streamlit run app/metrics_dashboard.py        # retrieval-metrics dashboard (synthetic sample data)
docker compose up                             # 3-service split: api :8000, retrieval :8001, inference :8002
psql "$PGVECTOR_DSN" -f scripts/create_pgvector_table.sql   # provision pgvector table (pgvector/hybrid only)
```

Tests (run with `python -m pytest` so the repo root lands on `sys.path`; `pytest.ini` sets
`testpaths = tests` and `--import-mode=importlib`):

```bash
python -m pytest -q                                              # full suite
python -m pytest tests/test_rag_pipeline.py -q                   # one file
python -m pytest tests/test_api.py::test_upload_and_ask -q       # one test
```

Lint / format / type-check (config lives only in `requirements-dev.txt` pins — no `pyproject.toml`):

```bash
black . && isort . && flake8 && mypy app
```

## Architecture

### Pipeline stages (`app/`)

`ingestion.py` (extract text) → `chunking.py` (fixed-size overlapping chunks) → `embeddings.py`
(SentenceTransformers `all-MiniLM-L6-v2`, 384-dim) → `vector_store.py` (index) → `rag.py`
(retrieve + rerank + generate). `main.py` wires these together behind HTTP endpoints.

`ingestion.extract_text` dispatches on file extension (PDF / DOCX / TXT / image OCR); the
supported set lives in `_SUPPORTED_SUFFIXES`. Remote-source helpers download to a temp file and
delegate to `extract_text`: `extract_google_doc_text` (public export URL) and
`extract_sharepoint_text` (Microsoft Graph, app-only token cached in `_GRAPH_TOKEN_CACHE`;
accepts a shareable URL or `drive_id`/`site_id` + `item_id`).

`db_ingestion.extract_database_text` is a non-file source: it runs one read-only `SELECT`
against PostgreSQL (lazy `psycopg`) or SQLite (stdlib), serializes each row to a
`[<table> N] col: val; col: val` line, and returns that as the document text. The bracket prefix
is the same citation-label convention `rag.py` parses. Writes are blocked three ways: read-only
connection, a `SELECT`/`WITH`-only statement filter (`_validate_select`, fails closed on any
data/DDL keyword anywhere in the string, literals included), and a `LIMIT` + `fetchmany` row cap.

`chunking.chunk_text` prepends a `[Section N]` or inferred-heading label to every chunk. `rag.py`
parses those brackets to build the `References:` line appended to answers, so the label format is a
contract between the two modules.

### Two deployment topologies

1. **Monolith** (default): everything runs in the `app.main` process. `rag.py` calls
   `vector_store.search()` and the LLM provider directly.
2. **Service split**: setting `RETRIEVAL_SERVICE_URL` and/or `INFERENCE_SERVICE_URL` makes `rag.py`
   POST to `app.retrieval_service` (`/search`, :8001) and `app.inference_service` (`/generate`, :8002)
   instead. Those services import helpers straight from `rag.py` (`_rerank_context_chunks`,
   `_call_openai`, etc.) and expect a shared persistent vector backend. `docker-compose.yml` wires
   this topology.

### Vector store abstraction (`vector_store.py`)

`VectorStore` is a runtime-dispatch wrapper over three backends selected by `VECTOR_DB_BACKEND`:

- `FaissVectorStore` — in-memory `IndexFlatL2`, the default.
- `PGVectorStore` — PostgreSQL + pgvector, persistent; auto-creates its table/HNSW index.
- `HybridVectorStore` — mirrors writes to both, searches one primary (`PGVECTOR_PRIMARY_SEARCH`).

`VECTOR_DB_BACKEND` defaults to `pgvector` when `PGVECTOR_DSN` is set, otherwise `faiss`. All
backends expose `add / search / clear / close` and a monotonic `revision` counter that `rag.py`
folds into its cache keys so an index update invalidates cached answers.

### Request scoping / multi-tenancy

Every `/upload` and `/ask` call carries `tenant_id`, `collection_id`, `document_id` plus optional
`document_date`, `author`, `tag`, `source_system`. On ingest these become per-chunk metadata; on
ask they become equality filters passed into `search()`. The sentinel value `"default"` is
normalized to `None` (no filter) in both `main.py` and `rag.py`.

### Answer generation (`rag.generate_answer`)

Response cache → embed question → retrieve a candidate pool of `RETRIEVAL_RERANK_POOL_SIZE` →
lexical `_rerank_context_chunks` → keep `TOP_K` → **lexical relevance gate** (`_has_relevant_context`;
if question/context term overlap is too weak the provider is never called and
`NO_RELEVANT_INFO_RESPONSE` is returned) → grounded prompt → provider call → **grounding gates**
(`_is_answer_grounded`, `_answer_addresses_question`; either can downgrade the answer to
`NO_RELEVANT_INFO_RESPONSE`) → append `References:`. On provider exception,
`_provider_error_answer` falls back to the best-matching sentence from the retrieved context.
Answers beginning with `EXTERNAL_RESPONSE_PREFIX` (`"External response:"`) or `"External knowledge:"`
bypass the grounding and reference steps. In-memory response and retrieval caches
(`_RESPONSE_CACHE`, `_RETRIEVAL_CACHE`, 30-min TTL) are reset via `rag._clear_caches()`.

### LLM providers

`LLM_PROVIDER` = `openai` (Responses API, `client.responses.create`) | `huggingface` (Inference
API over `requests`) | `auto` (`_call_fastest_provider` races both in threads, first non-empty
response wins). The OpenAI client is constructed lazily so a missing key does not break import.

### Endpoints (`app/main.py`)

`/upload`, `/upload-google-doc`, `/upload-sharepoint`, `/ingest-database`, `/ask`,
`/question-domains`, `/ingestion-jobs/{job_id}`, `/metrics`, `/feedback`, `/feedback/summary`.

- **SharePoint ingestion**: `/upload-sharepoint` pulls a file through Microsoft Graph using an
  app-only (client-credentials) token — set `SHAREPOINT_TENANT_ID` / `SHAREPOINT_CLIENT_ID` /
  `SHAREPOINT_CLIENT_SECRET` (Entra ID app with `Sites.Read.All` + `Files.Read.All`). No new
  dependency — token and download go over `requests`. Because the token is app-only, retrieval is
  **not** permission-trimmed per end user; add delegated auth for that. `SharePointIngestRequest`
  has a `model_validator` requiring a locator, so a missing URL/id is a 422, not a 500.
- **Database ingestion**: `/ingest-database` takes `table` XOR `query` plus a `connection_string`
  (or falls back to `DB_INGESTION_DSN`); scheme must be `postgresql` / `postgres` / `sqlite`.
  Tunables: `DB_INGESTION_MAX_ROWS` (5000), `DB_INGESTION_MAX_CELL_CHARS` (2000),
  `DB_INGESTION_STATEMENT_TIMEOUT_MS` (15000, Postgres only). `DatabaseIngestRequest`'s
  `model_validator` enforces the table/query XOR at 422. This is row-serialization only — there is
  no text-to-SQL / query-time DB path.

- **Async ingestion**: uploads ≥ `ASYNC_INGESTION_MIN_BYTES` (200 KB; `0` = always async) are
  handed to the in-process thread queue in `ingestion_jobs.py`, which returns a `job_id` to poll.
  The queue is deliberately swappable for Celery/RQ later without changing the API contract.
- **Observability**: `slo_metrics.py` turns in-memory request samples into a structured SLO
  report at `/metrics` — a p50/p90/p95/p99 latency distribution, availability, throughput,
  retrieval-hit quality, and each of those scored against an env-overridable target (`SLO_*`)
  with a per-objective attainment ratio, an error-budget figure, and an overall
  `healthy`/`at_risk`/`breached` status. `feedback_store.py` keeps thumbs + free-text corrections
  at `/feedback/summary`.
- **Question domains**: `rag.classify_question_domain` is a heuristic keyword classifier mapping a
  question into the 20-entry `QUESTION_DOMAIN_CATALOG`; the result rides on every `/ask` response.

### Shared process state

`main.vector_store` is a module-level singleton guarded by `vector_store_lock` (an `RLock` also
held around `generate_answer`). The embedding model in `embeddings.py` is a lock-guarded
singleton, pre-warmed in each service's `lifespan` startup.

### Configuration (`app/config.py`)

A dependency-free `.env` loader runs at import: it reads `./.env` and `<repo>/.env`, parses
`KEY=VALUE`, and **never overrides an already-set environment variable**. All tunables
(`CHUNK_SIZE`, `TOP_K`, `EMBEDDING_DIM`, backend/provider/model names, service URLs, size caps,
`SHAREPOINT_*` / `GRAPH_*`, `DB_INGESTION_*`) are plain module constants read from the
environment here. Note: a
variable set to an empty string (`FOO=` in `.env`) counts as "set", so it shadows the
`os.getenv(..., default)` fallback — leave a key out entirely rather than blank it.

## Testing conventions

- Tests use `fastapi.testclient.TestClient` + `pytest`'s `monkeypatch` to stub every heavy or
  networked dependency (`extract_text`, `chunk_text`, `embed_text`, `VectorStore`,
  `generate_answer`, and the provider client factories). No test downloads a model or hits a network.
- Patch the name on the **module that uses it** (`monkeypatch.setattr(main, "embed_text", ...)`),
  not on its defining module.
- `tests/test_api.py::setup_function` resets `main.vector_store`, `slo_metrics.reset()`, and
  `feedback_store.reset()`. `tests/test_rag_pipeline.py` has an autouse fixture calling
  `rag._clear_caches()`. Any new test that touches module singletons or the rag caches must reset
  them the same way, since that state persists across tests in a process.

## Gotchas

- **Stale copies**: `rag-doc-qa-repo/` and `rag-doc-qa-repo-clone/` are old nested checkouts.
  Ignore them; the live code is `app/` at the repo root.
- **`prototypes/ui/`** is a standalone TypeScript / Vite / React frontend with its own
  `package.json` and `node_modules` — not part of the Python service. `main.py`'s CORS allow-list
  (`localhost:5173/5174/3000`) exists for it.
- Active git branch is `rag` (not `main` / `master`). Remote is
  `github.com/getinetaga/rag-doc-qa-repo`.
- Image ingestion (`ingestion.extract_image`) needs a system Tesseract install for `pytesseract`.
- `app/metrics_dashboard.py` renders **synthetic** Precision@K / Recall@K data; wire in real
  evaluation output before relying on its quality gate.
