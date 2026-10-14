# RAG Codebase Analysis

Analysis date: 2026-10-14.

## 1. Scope, method, and limitations

This report describes the existing working-tree implementation, not a proposed
replacement. The live application is in `app\` and `frontend\`. Existing source
code, UI, configuration, and deployment files were not modified. The repository
already had staged moves and unstaged changes, including a vector-store refactor;
those changes were preserved and are included in this analysis.

Evidence consists of direct source inspection, inspection of all seven existing
test modules, an isolated execution of the existing tests, a frontend TypeScript
check, and six deterministic synthetic correctness probes. References such as
`app\rag.py:634-698` identify working-tree line ranges at analysis time.

The root `.env` exists, but its contents were deliberately not inspected. Secret
values, passwords, connection strings, private document contents, and personal
documents are not included here. Initial configuration imports during analysis
were prevented from loading the root `.env`; external HTTP was blocked during
the test run.

There were no unreadable application source files in the inspected scope.
Important boundaries and missing items:

- `rag-doc-qa-repo\`, `rag-doc-qa-repo-clone\`, and `prototypes\` are not present as
  nested directories in this checkout, despite historical references to them.
- No `.github\workflows\` directory, `.dockerignore`, `pyproject.toml`, frontend
  test script, or live evaluation dataset/runner was found in the application
  and deployment scope inspected.
- `docs\personal\` and scratch files were excluded from content inspection.
  `docs\frontend-migration\` is historical documentation, not runtime evidence.
- No live PostgreSQL schema, database permissions, Graph tenant configuration,
  deployed ingress/authentication, provider account, or actual model output was
  inspected. The database schema below is the schema defined by the code.
- No Docker deployment, browser execution, real model download, external
  inference call, real PDF corpus evaluation, or OCR execution was performed.
- `pytesseract` is declared but not installed in the selected virtual environment.
  `tesseract` was not found on the command PATH; an installation outside PATH was
  not investigated.
- `pytest-cov` is declared in development dependencies but not installed in the
  selected environment. No numeric line/branch coverage percentage is claimed.

## 2. Executive assessment

The application is a modular Python RAG backend with a React production client
and two Streamlit demo paths. It implements local SentenceTransformer embeddings,
FAISS or PostgreSQL/pgvector storage, dense candidate retrieval, lexical
reranking, a grounded prompt, external LLM calls, heuristic answer checks,
section-label references, in-process caching, async upload jobs, metrics, and
feedback.

It is not yet a production-safe multi-user system. The browser login is a demo
identity mechanism, not server authentication. Client-supplied tenant filters
are not an authorization boundary. Several correctness and deployment gaps
remain even though all existing tests pass.

Highest-priority findings:

1. Retrieval cache keys omit advanced metadata filters.
2. Caches do not distinguish independent stores, and process-local revisions do
   not detect another worker's persistent-index updates.
3. Direct-upload clients treat queued ingestion as completed ingestion.
4. Document IDs can collide, causing scoped replacement of unrelated documents.
5. Server authentication, connector authorization, safe upload staging, and
   Docker context exclusions need attention before wider exposure.
6. Citation strings do not preserve reliable document/page/chunk provenance.

These are recommendations for review only. No improvements have been implemented.

## 3. Architecture and repository inventory

### 3.1 Runtime topology

```text
React browser client                    Streamlit HTTP demo
frontend\src\main.tsx                    app\streamlit_app.py
          |                                       |
          +---------------- HTTP -----------------+
                              |
                        app\main.py
                              |
    extract text -> chunk -> embed -> scoped clear/add -> vector store
                              |
                  question -> app\rag.py
                              |
             dense search -> lexical rerank -> relevance gate
                              |
           prompt -> provider -> answer checks -> text references

Optional service split:
app\rag.py -> app\retrieval_service.py /search
app\rag.py -> app\inference_service.py /generate

Separate in-process demo:
app\streamlit_demo.py -> pipeline helpers directly
```

The split is activated by `RETRIEVAL_SERVICE_URL` and
`INFERENCE_SERVICE_URL`, independently. Remote retrieval uses its own embedding
model and store instance; remote inference uses the same provider helpers as the
monolith. No broker, distributed cache, database container, or production
frontend-serving service is defined in Compose.

### 3.2 Files and responsibilities

| Location | Actual responsibility |
|---|---|
| `app\main.py` | FastAPI API, lifespan, CORS, scoped ingestion, shared vector-store lock, metrics/feedback routes. |
| `app\schemas.py` | Pydantic request/response models and SharePoint/database locator validation. |
| `app\ingestion.py` | PDF/DOCX/TXT/image extraction; Google Docs text export; Microsoft Graph token/download helpers. |
| `app\db_ingestion.py` | Read-oriented SQL row serialization using SQLite or PostgreSQL; not text-to-SQL. |
| `app\chunking.py` | Character-window chunking and inferred/fallback bracket labels. |
| `app\embeddings.py` | Lazy, lock-protected SentenceTransformer singleton and batched encoding. |
| `app\vector_store.py` | `VectorSearchResult`, protocol, FAISS, pgvector, mirrored hybrid backend, compatibility wrapper/factory. |
| `app\rag.py` | Providers, caches, filters, lexical reranking/gates, prompt, domain classifier, references, fallback answers. |
| `app\retrieval_service.py` | Independent FastAPI `/search` service. |
| `app\inference_service.py` | Independent FastAPI `/generate` service. |
| `app\ingestion_jobs.py` | Single daemon-thread queue and in-memory job states. |
| `app\slo_metrics.py` | Process-local request/quality samples and SLO snapshots. |
| `app\feedback_store.py` | Process-local bounded feedback deque and aggregate corrections. |
| `app\streamlit_demo.py` | Pipeline executed directly inside Streamlit; local session history. |
| `app\streamlit_app.py` | Streamlit client calling the main API over HTTP. |
| `app\metrics_dashboard.py` | Streamlit visualization of hardcoded synthetic retrieval metrics. |
| `frontend\index.html`, `frontend\src\main.tsx` | Vite HTML entry and React root; render `frontend\RAGQAApp.tsx`. |
| `frontend\RAGQAApp.tsx` | Active client: login state, file/SharePoint ingestion, scoped asking, history, `/docs` polling. |
| `frontend\src\auth.ts`, `LoginScreen.tsx` | Client-only demo login, generated user IDs, localStorage sessions. |
| `frontend\src\services.ts`, `types.ts` | Separate typed API service and models; not used for HTTP by the rendered component. |
| `frontend\src\constants.ts`, `styles.ts`, `utils.ts`, `hooks.ts` | Styling/constants/utilities and partly unused reusable behavior. |
| `frontend\package.json`, `package-lock.json` | Frontend manifest and dependency lockfile. |
| `frontend\tsconfig.json`, `vite.config.ts` | Strict TypeScript/noEmit and Vite dev configuration. |
| `frontend\start-dev.ps1`, `start-dev.sh` | Developer startup wrappers; probe `/docs`, then start Vite. |
| `tests\` | Seven Python test modules; details in section 11. |
| `scripts\create_pgvector_table.sql` | Manual provisioning of the default pgvector schema/indexes. |
| `scripts\generate_mermaid.ps1`, `generate_mermaid.sh` | Documentation diagram utilities, not pipeline stages. |
| `scripts\build_capstone_presentation.py` | Presentation utility; uses a hardcoded historical external checkout path, not a runtime entry point. |
| `Dockerfile`, `docker-compose.yml`, `Jenkinsfile` | Container image, three-service example, and Jenkins test/build example. |
| `requirements.txt`, `requirements-dev.txt`, `pytest.ini` | Dependencies and pytest discovery/import mode. |
| `README.md`, `CLAUDE.md`, `docs\` | Setup/guidance/documentation; claims were checked against source rather than assumed correct. |
| `samples\test_doc.txt` | Sample document; not a labeled retrieval-evaluation corpus. |

### 3.3 Entry points

Commands below describe existing entry points, not services started for this
analysis. Use the virtual environment's executables when appropriate.

| Purpose | Existing command |
|---|---|
| Main API | `uvicorn app.main:app --reload` |
| Retrieval service | `uvicorn app.retrieval_service:app --port 8001` |
| Inference service | `uvicorn app.inference_service:app --port 8002` |
| Production-client development | Run `npm run dev` from `frontend\`. |
| Frontend bundle | Run `npm run build` from `frontend\`; invokes `tsc && vite build`. |
| In-process demo | `streamlit run app\streamlit_demo.py` |
| HTTP demo | `streamlit run app\streamlit_app.py` |
| Synthetic dashboard | `streamlit run app\metrics_dashboard.py` |
| Split containers | `docker compose up` |
| Tests | `python -m pytest -q` |

Main lifespan preloads the embedding model, starts the job worker, and attempts
vector-store construction. Store initialization errors are logged and deferred,
not treated as startup failure (`app\main.py:57-90`). Retrieval preloads the model
but lazily constructs the store (`app\retrieval_service.py:49-70`). Inference also
preloads the embedding model even though its generation route does not use it
(`app\inference_service.py:35-56`).

## 4. Technologies and dependencies

These technologies are verified through imports and implementations, not inferred
from documentation:

| Area | Actual implementation |
|---|---|
| API | FastAPI, Uvicorn, Pydantic v2, multipart uploads. |
| Production client | React 18, TypeScript, Vite; inline fetch in the active component. |
| Demo clients | Streamlit; Matplotlib for the synthetic dashboard. |
| Parsing | pdfplumber, python-docx, plain file reading, Pillow/pytesseract for image OCR. |
| Embeddings | SentenceTransformers `all-MiniLM-L6-v2`, NumPy float32 arrays. |
| Vector backends | FAISS `IndexFlatL2`; PostgreSQL/pgvector via psycopg; mirrored hybrid wrapper. |
| SQL ingestion | SQLite standard library or PostgreSQL psycopg. |
| Generation | OpenAI Responses API or Hugging Face HTTP Inference API; optional provider race. |
| Remote sources | Requests HTTP client; Google export and Microsoft Graph app-only OAuth. |
| Testing | pytest, FastAPI TestClient, monkeypatch; real temporary SQLite tests. |
| Deployment example | Docker/Compose and Jenkins. No verified Kubernetes/Redis/Celery implementation. |

`requirements.txt:1-20` declares FastAPI 0.127.1, Uvicorn 0.40.0,
python-multipart 0.0.22, Pydantic 2.12.5, FAISS 1.13.2, pdfplumber 0.11.9,
python-docx 1.2.0, and NumPy 2.4.1. OpenAI, HTTPX, pgvector, psycopg,
SentenceTransformers, python-pptx, Pillow, pytesseract, Streamlit, Matplotlib,
Requests, and pytest use version ranges rather than exact pins.

`requirements-dev.txt:1-6` declares Black, isort, flake8, pytest-cov, pre-commit,
and mypy. Declaring these tools is not evidence that CI runs them: the Jenkins
"Lint & Test" stage only runs pytest (`Jenkinsfile:35-46`).

The selected local virtual environment used Python 3.14.3. Installed package
metadata includes OpenAI 1.109.1, pgvector 0.4.2, psycopg 3.3.3,
SentenceTransformers 5.3.0, Streamlit 1.55.0, and pytest 9.0.2. These observations
do not imply clean installation on other Python versions. The Docker base is
Python 3.11 (`Dockerfile:2`); no clean container build was validated.

There is a frontend lockfile, but no corresponding comprehensive Python lockfile
was found. `python-pptx` supports the presentation script, not document ingestion;
PPTX upload parsing is not implemented.

## 5. Configuration: what is actually configurable

`app\config.py:18-55` reads a `.env` in the current directory or repository root,
uses the first existing readable candidate, and never replaces an already-set
environment variable. Read failures are silently ignored. Parsing is simple:
it is not a complete dotenv parser and does not remove inline comments.
An empty existing variable also suppresses defaults based on `os.getenv`.

| Variables/constants | Source behavior/default |
|---|---|
| `OPENAI_API_KEY` | Environment credential; lazy client creation. Value not inspected. |
| `HUGGINGFACE_API_KEY`, `HF_TOKEN`, `HUGGINGFACEHUB_API_TOKEN` | Credential aliases; first nonempty value wins. |
| `LLM_PROVIDER` | Environment; default `openai`; `huggingface` and `auto` have explicit branches. Other strings fall through to OpenAI rather than being rejected. |
| `OPENAI_LLM_MODEL` | Environment, then `LLM_MODEL`, then `gpt-4o-mini`. |
| `HUGGINGFACE_LLM_MODEL` | Environment, then `LLM_MODEL`, then `google/flan-t5-base`. |
| `LLM_MODEL` | Provider-dependent compatibility alias. |
| `EMBEDDING_MODEL` | Fixed `text-embedding-3-small`; unused by the actual local embedding helper. |
| `EMBEDDING_DIM` | Environment; default 384. Does not switch or resize the actual SentenceTransformer model. |
| `_MODEL_NAME` in `embeddings.py` | Fixed `all-MiniLM-L6-v2`; this is the model actually loaded. |
| `CHUNK_SIZE`, `CHUNK_OVERLAP` | Fixed Python values 800 and 100 characters; not environment overrides. |
| `TOP_K` | Fixed Python value 5; a Compose `TOP_K` variable does not change this constant. |
| `RETRIEVAL_RERANK_POOL_SIZE` | Environment; computed default 15 with the current `TOP_K`. Compose gives retrieval a default of 20. |
| `API_WORKERS` | Environment constant default 1; Docker/Compose shell commands actually control Uvicorn worker count. Compose defaults to 4 API workers. |
| `RETRIEVAL_SERVICE_URL`, `INFERENCE_SERVICE_URL` | Empty by default; nonempty selects the corresponding remote service path. |
| `ASYNC_INGESTION_MIN_BYTES` | Environment; default 200,000 bytes; 0 means always queue direct uploads. |
| `MAX_UPLOAD_FILE_SIZE_BYTES` | Environment; default 209,715,200 bytes (200 MiB). |
| `VECTOR_DB_BACKEND` | Environment; defaults to pgvector when a nonempty `PGVECTOR_DSN` exists, otherwise FAISS. |
| `PGVECTOR_DSN`, `PGVECTOR_TABLE_NAME` | Persistent connection setting and table identifier; default table `rag_embeddings`. No connection value included here. |
| `PGVECTOR_PRIMARY_SEARCH` | Environment; default pgvector for mirrored hybrid mode. |
| `SHAREPOINT_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET` | Graph app-only credentials, with corresponding `AZURE_*` aliases. Values not inspected. |
| `GRAPH_BASE_URL`, `GRAPH_AUTHORITY` | Environment; default public Microsoft Graph v1.0 and Microsoft identity endpoints. |
| `SHAREPOINT_MAX_DOWNLOAD_BYTES` | Environment; default 200 MiB; checked against Graph-declared size only. |
| `DB_INGESTION_DSN` | Default SQL source if no request connection is supplied. Value not inspected. |
| `DB_INGESTION_MAX_ROWS` | Environment default 5,000; request `max_rows` overrides it, with no configured maximum enforced. |
| `DB_INGESTION_MAX_CELL_CHARS` | Environment default 2,000 per serialized cell. |
| `DB_INGESTION_STATEMENT_TIMEOUT_MS` | Environment default 15,000; set in the PostgreSQL ingestion path only. |
| `SLO_SERVICE_NAME` | Read directly in `slo_metrics.py`; default `rag-doc-qa`. |
| `SLO_AVAILABILITY_TARGET` | Default 0.99. |
| `SLO_LATENCY_P95_TARGET_SECONDS`, `SLO_LATENCY_P99_TARGET_SECONDS` | Defaults 3 and 8 seconds. |
| `SLO_RETRIEVAL_QUALITY_TARGET` | Default 0.6 for a lexical-overlap proxy, not labeled retrieval accuracy. |
| Cache controls in `rag.py` | Fixed 1,800-second TTL, 256 answer entries, 512 retrieval entries. |
| `frontend\.env.example` `VITE_*` variables | Document intended settings; active API URL/timeouts are hardcoded. No application reading of these named settings was found. |

Evidence: `app\config.py:60-166`, `app\embeddings.py:19-50`,
`app\slo_metrics.py:35-39`, `app\rag.py:47-52`,
`frontend\RAGQAApp.tsx:22,116-128,194-198,294-304`,
`frontend\src\constants.ts:11-28`, and `docker-compose.yml`.

## 6. Ingestion, parsing, and indexing

### 6.1 Direct file ingestion

`upload_document` accepts file plus scoping metadata
(`app\main.py:242-355`). It checks declared size, writes to
`temp_<client filename>` in the current working directory, checks actual size,
then either processes synchronously or enqueues `_process_upload_job`.

`_process_upload_job` delegates extraction/indexing and deletes the staged file
in `finally` (`app\main.py:142-170`). The outer upload route also performs cleanup
for synchronous/error paths. Initial file copying occurs before that protected
cleanup block.

`extract_text` dispatches by extension, not MIME/content signature:

| Format | Parser and actual limitations |
|---|---|
| PDF | `extract_pdf` joins pdfplumber page text and skips empty pages. Page numbers and layout are not preserved; there is no scanned-PDF OCR fallback. |
| DOCX | `extract_docx` joins nonempty paragraphs. No explicit table/header/footer extraction. |
| TXT | `extract_txt` tries UTF-8 then Latin-1. Latin-1 can decode arbitrary bytes without proving the file is meaningful text. |
| Images | `extract_image` converts to RGB and calls pytesseract. System Tesseract is an additional dependency; no explicit OCR timeout or extracted-text bound. |
| Other formats | `ValueError`; `.pptx`, `.xlsx`, `.csv`, `.html`, and archives are not implemented upload parsers. |

Supported image suffixes are PNG/JPG/JPEG/BMP/TIFF/TIF/WebP/GIF.
Evidence: `app\ingestion.py:32-156`.

### 6.2 Google Docs

`extract_google_doc_text` derives a document ID, requests Google's plain-text
export, checks HTTP status and nonempty text, and returns a string
(`app\ingestion.py:159-198`). This is public/shared-link export, not Google OAuth
or Google Drive synchronization. It does not create a temporary file.

The host check is substring-based rather than exact. The path-based ID regex is
restricted, but the query `id` fallback is not equivalently constrained.
The actual fetch URL is constructed for Google; this is not evidence of an
arbitrary-host Google URL fetch. No download byte cap is implemented.

`upload_google_doc` indexes the result through `_index_text_content`; it is
synchronous regardless of remote size (`app\main.py:358-380`).

### 6.3 SharePoint / OneDrive for Business

`SharePointIngestRequest._require_locator` requires either a sharing URL or
`item_id` plus drive/site ID (`app\schemas.py:79-106`).
`_get_graph_token` uses OAuth client credentials and caches tokens under a
client-ID key, refreshing a minute early (`app\ingestion.py:205-267`).

`extract_sharepoint_text` resolves Graph metadata, checks supported filename
extension and declared size, downloads content with redirects allowed, writes
a uniquely named temporary file, delegates to `extract_text`, and cleans up
(`app\ingestion.py:281-366`). The downloaded response is buffered in memory; the
actual received byte count is not checked against the configured cap.

Access is app-only. There is no per-user delegated token or ACL trimming before
indexing/retrieval. Alternate cloud endpoints are configurable, but token scope
is hardcoded to the public Graph audience. Actual alternate-cloud compatibility
was not verified.

### 6.4 SQL ingestion

`DatabaseIngestRequest` requires exactly one of table/query.
`extract_database_text` accepts PostgreSQL/Postgres/SQLite schemes and serializes
the selected result (`app\schemas.py:109-132`,
`app\db_ingestion.py:181-242`).

Controls already present:

- Table identifiers are restricted to simple optionally schema-qualified names.
- Query must start with SELECT/WITH, contain no extra semicolon, no listed
  mutation/DDL keyword, and no INTO.
- Table queries receive LIMIT; custom queries are wrapped and limited.
- SQLite is opened with `mode=ro`; PostgreSQL sets a statement timeout and
  attempts `conn.read_only = True`.
- Fetching and each cell's rendered character length are capped.

Important caveats: the keyword filter also rejects legitimate literals/comments
containing forbidden words. PostgreSQL uses autocommit, and errors setting
read-only are swallowed; the source does not prove a fail-closed read-only
session under all driver/database conditions. This needs a live PostgreSQL
integration test and least-privilege database role, not trust in a keyword
filter. SELECT-accessible functions and data access still require authorization.

Rows become `[<table> N] column: value; ...`, or `[row N]` for custom queries.
This is ingestion-time row serialization, not natural-language SQL generation
or query-time database answering (`app\db_ingestion.py:53-178`).

The SQL LIMIT means the subsequent `fetchmany(max_rows + 1)` generally cannot
observe the extra row intended to indicate truncation. A row cap may silently
omit records without a useful truncation indicator.

### 6.5 Shared indexing path and metadata

`_index_text_content` resolves document identity, chunks, rejects empty chunk
lists, embeds all chunks, initializes the store, creates metadata, and performs
scoped clear followed by add under `vector_store_lock`
(`app\main.py:173-239`).

Per-chunk metadata:

| Field | Current representation |
|---|---|
| `tenant_id`, `collection_id`, `document_id` | Caller-supplied strings/defaults; document ID derived if placeholder. |
| `document_date`, `author`, `tag`, `source_system` | Optional strings copied to each chunk if truthy. |
| `source_document` | Set to effective document ID by the vector wrapper/backend. |

The original filename/URL is used for identity derivation and logging, but is not
reliably stored as independent provenance. No ingestion version, content hash,
page/offset range, tokenizer/model version, ACL, or document registry is added.
Dates/tags are equality-filter strings, not parsed date ranges or tag arrays.

Re-ingesting the same scoped ID deletes prior chunks before inserting new ones.
Clear/add are separate operations/commits, not one atomic replace transaction.
The process lock does not synchronize separate processes or services.

`_resolve_document_id` uses a sanitized lowercase filename stem
(`app\main.py:121-130`). This is not globally unique. Two Google edit URLs resolve
to `edit`; two PDF/TXT files with the same stem share a default identity.
The frontend uses the text before the first dot, unlike Python's final-suffix
stem, increasing collisions for versioned filenames
(`frontend\src\utils.ts:18-50`).

## 7. Chunking, embeddings, vector schema, and search

### 7.1 Chunking

`chunk_text` takes 800-character windows with a 100-character overlap. It strips
each window and prefixes an inferred heading or `[Section N]`
(`app\chunking.py:17-72`).

Headings are heuristically detected among the first five nonempty lines using
section/chapter/part/appendix prefixes, numbered headings, uppercase, or title
case. This is not paragraph-aware/token-aware chunking, nor a document structure
parser. Windows can split words, sentences, rows, and tables.

The added label makes returned strings longer than the documented nominal
`CHUNK_SIZE` maximum. Labels are inferred independently per window and are not
stable source offsets. Existing SQL row labels can become nested behind
`[Section N]`; final reference extraction sees only the outer label.

Only overlap >= size is explicitly rejected. Negative values/other invalid
chunk settings are not comprehensively validated.

### 7.2 Embeddings

`get_model` loads `SentenceTransformer("all-MiniLM-L6-v2")` once per process with
a loading lock (`app\embeddings.py:19-50`). `embed_text` validates string inputs
and encodes in batches of 32 by default, returning float32 arrays
(`app\embeddings.py:55-93`).

The intended model dimension is 384. Explicit normalization, token-limit
management, query/document-specific encoding, embedding version storage, and
an ingestion embedding cache are not implemented. `EMBEDDING_DIM` can diverge
from the actual model if changed independently.

The model initialization lock protects construction, not every encoding call.
Main `/ask` is serialized by the larger API lock, but background ingestion and
other entry points have different concurrency boundaries.

### 7.3 Backends and actual result shape

| Backend | Search/storage implementation | Important distinction |
|---|---|---|
| `FaissVectorStore` | In-memory `IndexFlatL2`; parallel text, metadata, ID, and vector lists; searches all vectors before filtering/deduping. | Structured results with genuine FAISS squared-L2 distances; lower is better. No disk persistence or shared-worker state. |
| `PGVectorStore` | One psycopg connection; vector `<->` L2 ordering; SQL equality predicates and overfetch by 5x before text dedupe. | Backend itself selects only text and returns strings, not actual row IDs, distances, or metadata. |
| `HybridVectorStore` | Sequentially mirrors clear/add to both FAISS and pgvector; searches one configured primary. | Not BM25+dense hybrid retrieval, reciprocal-rank fusion, or failover search. Partial write failure can desynchronize stores. |
| `VectorStore` | Selects backend, exposes compatibility signatures, wraps strings as `VectorSearchResult`. | pgvector string results get positional synthetic IDs, score 0.0, empty metadata. These are not trustworthy source IDs or confidence. |

Evidence: `app\vector_store.py:29-75,111-260,263-464,467-599`.

The in-progress refactor is incomplete across backends: protocol `delete` and
custom IDs are implemented for FAISS but not pgvector/hybrid. Passing custom IDs
to unsupported backends can fail; the wrapper raises `NotImplementedError` for
unsupported delete. FAISS-generated IDs use current list length, which reuses
existing IDs after a partial deletion.

FAISS add validates text/metadata/ID lengths but not embedding/text row-count
equality before adding to the index. No comprehensive finite-value, dimension,
or duplicate-ID contract is enforced across all backends.

RAG immediately converts results back to text in `_dedupe_chunks`, discarding
structured scores and metadata (`app\rag.py:474-486`). Identical text from
different documents can be deduplicated without retaining all source identities.

### 7.4 Code-defined PostgreSQL schema

Default table: `rag_embeddings`; configurable through `PGVECTOR_TABLE_NAME`.

| Column | Defined type/default |
|---|---|
| `id` | `BIGSERIAL PRIMARY KEY` |
| `text` | `TEXT NOT NULL` |
| `embedding` | `vector(dim) NOT NULL`; manual script uses 384. |
| `source_document` | `TEXT`, nullable |
| `metadata` | `JSONB NOT NULL DEFAULT '{}'` |
| `created_at` | `TIMESTAMPTZ NOT NULL DEFAULT NOW()` |

Indexes: HNSW on embedding with `vector_l2_ops`, and a B-tree on
`source_document`. No tenant/collection/document JSON-expression indexes, GIN
metadata index, uniqueness constraint for document versions/chunks, or row-level
security policy is defined.

Evidence: `app\vector_store.py:291-321` and
`scripts\create_pgvector_table.sql:3-21`.

`register_vector` is called before `_ensure_schema` creates the extension.
Consequently the advertised automatic extension provisioning can fail on a
database where the vector type is not already installed. The manual script can
pre-provision it; actual first-run behavior was not tested against PostgreSQL.

Search uses the same non-autocommit connection without an explicit search commit,
and failure paths do not explicitly roll back/reconnect. Idle transactions,
aborted-transaction recovery, and concurrent service access need integration
validation. No schema migration mechanism is implemented.

## 8. Retrieval, reranking, prompting, and response generation

### 8.1 End-to-end answer path

1. `/ask` validates `QuestionRequest`. If there is no store object, it returns
   `No document uploaded yet.`; startup normally creates an empty store, so an
   empty running index can instead reach the no-relevant-information path.
2. The API logs the question, classifies its domain, and holds
   `vector_store_lock` throughout `generate_answer`
   (`app\main.py:458-485`).
3. `generate_answer` builds normalized scope/equality filters and checks the
   answer cache (`app\rag.py:903-959`).
4. On a miss, it embeds the question. Local retrieval checks its cache and
   searches a candidate pool; remote retrieval POSTs the question and filters
   to `/search`, which embeds the question again.
5. `_rerank_context_chunks` deduplicates text and sorts on lexical term overlap,
   with small heading/prefix bonuses, then keeps `TOP_K`
   (`app\rag.py:489-513,634-698`).
6. Retrieval quality records the best lexical query/context overlap ratio.
   Empty or lexically irrelevant context returns the fixed
   `NO_RELEVANT_INFO_RESPONSE` without calling a provider
   (`app\rag.py:763-819,975-987`).
7. The prompt contains `CTX-001`, `CTX-002`, etc., source text, and the current
   question. It requests context-only reasoning, uncertainty, citations,
   rejection of document instructions, and a final References line
   (`app\rag.py:989-1040`).
8. `_generate_from_prompt` chooses remote inference or the configured local
   provider (`app\rag.py:701-713`).
9. Successful output is checked for question-term overlap. Fact-style domains
   also receive the answer/context overlap check; nine synthesis-style domains
   skip that stronger check. A leading `External response:` bypasses both.
10. Section references are appended unless a References marker already exists.
    The final string is cached; the main API returns `answer` plus
    `question_domain`.
11. Caught provider failures log a warning and select the best lexical context
    sentence. `_finalize_answer` applies checks/references to that fallback,
    which is also cached (`app\rag.py:851-900,1048-1076`).

There is no server conversation memory or history in `QuestionRequest`.
The clients display old messages, but subsequent requests contain only the new
question/scoping. A `conversational_followup` classification is not evidence that
prior-turn context is actually supplied.

### 8.2 Reranking and grounding: implemented, but heuristic

The reranker is lexical, not a cross-encoder or learned ranking model. There is
no BM25 index, retrieval fusion, semantic relevance threshold, MMR, neighboring
chunk expansion, or evidence-aware context-budget selection.

Question/answer terms use an ASCII-oriented regex, stopword removal, and minimum
length filters. Relevance typically requires two query terms or one sufficiently
specific term for short queries. Grounding checks require limited term overlap
and a 40% answer-term coverage ratio; they do not validate truth, numerical
consistency, entailment, or each claim's citation.

The catalog contains **19**, not 20, domain entries. Its classifier uses ordered
substring rules, so overlapping rules can classify a question unexpectedly
(`app\rag.py:105-309`). Catalog descriptions such as metadata questions, page
citations, and follow-ups describe aspirations/evaluation categories, not
guarantees of source metadata access, page preservation, or conversational memory.

### 8.3 LLM integrations

| Mode | Actual code path |
|---|---|
| OpenAI | Lazy singleton client; `client.responses.create(model=..., input=prompt, temperature=0)`; output text preferred. No app-specific max-output or explicit timeout setting in this helper. |
| Hugging Face | Requests POST to the model inference endpoint; timeout 30 seconds, `max_new_tokens=512`, `return_full_text=False`, `wait_for_model=True`; strips echoed prompt for common response shapes. |
| Auto | ThreadPoolExecutor starts both providers; chooses first nonempty success, cancels pending futures when possible. |
| Remote inference | Requests POST to `/generate` with prompt and default 30-second service timeout. |

Evidence: `app\rag.py:312-441,623-631,701-713`,
`app\inference_service.py:47-56`.

The provider race uses a context-managed executor. Returning from it still waits
for running futures during shutdown, so canceling a running slow request does not
ensure first-completed latency. It also submits source context to both providers,
which affects cost and data-governance scope.

Unexpected provider response shapes may be stringified into answer-shaped
content; an empty Hugging Face list can raise an uncaught IndexError.
No application retry/backoff/circuit-breaker policy is implemented, although SDK
defaults may provide some behavior. Provider availability and the Hugging Face
endpoint/model compatibility were not verified with live calls.

### 8.4 Citations

`_extract_section_references` recognizes only a leading bracket label.
`_append_references` lists the labels of all retained chunks, not specifically the
evidence supporting each generated claim (`app\rag.py:444-471`).

Consequences:

- Page numbers, original document identity, chunk offsets, and actual DB row IDs
  are not carried through a reliable structured response.
- Multiple documents can each have `[Section 1]`, making references ambiguous.
- `CTX-###` values are prompt-local positions and can change between queries.
  They are not persistent chunk IDs despite the prompt calling them stable.
- A provider's existing `References:` string is accepted without validating its
  cited labels or membership in the retrieved context.
- Nested serialized row labels are not the labels finally extracted.
- `AnswerResponse` has no `sources`/`citations`/confidence structure; the active
  React client displays answer text rather than a validated citation view.

The prompt requests `External knowledge:`, but the implemented special bypass
recognizes `External response:`. Mixed external/grounded content is not parsed or
enforced as distinct sections. There is no explicit request flag authorizing an
external-response bypass.

### 8.5 Caches

Caches are process-global OrderedDicts with lock-protected LRU updates and TTL.
Answer keys include revision, provider/model settings, TOP_K, core scope,
advanced metadata values, and normalized question.

Local retrieval keys include revision, provider/model settings, TOP_K, core
scope, candidate-pool size, and a four-decimal rounded embedding signature.
They **omit document_date, author, tag, and source_system** even though search
uses those filters (`app\rag.py:537-620,672-696`).

Neither key includes store identity, index namespace, or a shared persistent
revision. New stores with the same revision can reuse another store's cached
data. Writes in another API worker do not increment the local store object's
revision; remote retrieval still sits behind an API-side answer cache keyed on
that local revision. In-process Streamlit sessions are particularly sensitive
because their independent stores share the module caches.

The broad `except TypeError` compatibility search retry drops source/metadata
filters in both local RAG and retrieval service. This must not be used as an
authorization fallback, and it can hide TypeErrors from inside a backend rather
than only signature incompatibility.

## 9. API contract, errors, logging, and operational state

### 9.1 Main application routes

| Method/endpoint | Handler/model | Actual response/behavior |
|---|---|---|
| POST `/upload` | `upload_document`; multipart file/metadata | Sync: `{message, chunks}`. Async: `{message, job_id, status: queued}`. Both return 200; no explicit response model. Oversize can return 413. |
| POST `/upload-google-doc` | `upload_google_doc`, `GoogleDocIngestRequest` | `IngestResponse`: message/chunks. Synchronous. |
| POST `/upload-sharepoint` | `upload_sharepoint`, `SharePointIngestRequest` | `IngestResponse`; missing locator is 422. Synchronous. |
| POST `/ingest-database` | `ingest_database`, `DatabaseIngestRequest` | `IngestResponse`; source XOR violation is 422. Synchronous. |
| POST `/ask` | `ask_question`, `QuestionRequest` | `AnswerResponse`: answer and nullable question_domain. No structured source list. |
| GET `/question-domains` | `list_question_domains` | Catalog of 19 domain objects. |
| GET `/ingestion-jobs/{job_id}` | `get_ingestion_job` | Process-local job record; 404 if absent in that process. |
| GET `/metrics` | `get_metrics` | SLO snapshot from current process only. |
| POST `/feedback` | `submit_feedback`, `FeedbackRequest` | Feedback ID/status; rating constrained to up/down, invalid values 422. |
| GET `/feedback/summary` | `feedback_summary` | Aggregate ratings and recent corrections, without tenant filtering. |

Evidence: `app\main.py:242-516`, `app\schemas.py:19-149`.

### 9.2 Service and framework routes

`app\retrieval_service.py:31-104` defines POST `/search`: question plus scope,
advanced filters, top_k and candidate_pool_size; response `context_chunks:
list[str]`. Counts have minimum 1 but no maximum.

`app\inference_service.py:27-56` defines POST `/generate`: prompt string; response
answer string. No prompt-length cap or authentication dependency is implemented.

FastAPI defaults provide `/docs`, `/redoc`, and `/openapi.json` on these apps.
No custom `/health`, `/ready`, authentication/login API, document-list/delete
endpoint, or source-view endpoint is defined. `/docs` returning 200 does not
verify model/provider/vector-store readiness.

### 9.3 Error handling and logging

Existing useful behavior: extraction/embedding failures propagate; file jobs
clean up in `finally`; missing jobs get 404; schema validators yield 422; remote
HTTP status is checked; provider failures are logged before extractive fallback.

Gaps:

- Most ingestion ValueErrors/parser/network failures are re-raised without a
  consistent client-error mapping. Unsupported uploads become unhandled server
  errors; the existing API test expects a propagated ValueError.
- Empty/oversized questions and metadata strings have no substantive length
  constraints in `QuestionRequest`; connector errors are not normalized.
- Initial direct file copy is outside route cleanup/metric protection.
- Jobs store raw `str(exc)` for polling without a sanitization policy or logging
  traceback. Job status is not scoped to a caller.
- `.env` read failures and PostgreSQL read-only-setting failures are silent.
- Provider fallback is returned as normal answer text without a generation-mode
  or degraded-status field; it can remain cached after provider recovery.
- Embedding/retrieval exceptions occur outside the provider catch and are not
  consistently recorded as failed ask requests.

`logging.basicConfig` uses INFO-level timestamp/name/level/message in the main
and service modules. Extraction and indexing log names/counts, main logs full
questions, Graph logs a resource URL, and provider failures log exception text.
No structured request IDs, centralized redaction, trace propagation, or audited
access event model is implemented.

### 9.4 Jobs, feedback, and metrics

`ingestion_jobs.py` has one unbounded Queue, one daemon worker, and an unbounded
job-status dict per process. States are queued/running/completed/failed with
timestamps and result/error (`app\ingestion_jobs.py:17-79`).
There is no durable storage, bounded backlog, retry/cancellation policy, status
expiry, tenant ownership, graceful worker drain, or inter-worker job lookup.

Feedback is a 5,000-entry in-memory deque with process-local integer IDs
(`app\feedback_store.py:9-56`). It does not update retrieval, prompts, or model
behavior. Corrections can be read through an unscoped summary.

Metrics retain 1,024 latency/quality samples, cumulative process counters,
percentiles, uptime-average throughput, error budget, and four objectives
(`app\slo_metrics.py:32-287`). Not every endpoint is instrumented, and queued
upload success measures acceptance rather than later job completion.
The retrieval quality signal is lexical overlap, not Precision@K/Recall@K.

With the default availability target, `_objective` labels even 100% availability
`at_risk`: the "met" threshold is target * 1.05, which exceeds 1.0 for a 0.99
target. Healthy traffic therefore cannot clear that objective as currently coded.

`app\metrics_dashboard.py:25-106` uses hardcoded precision/recall/top-k values.
Its Streamlit success/error display is not connected to evaluation artifacts or
Jenkins and does not fail a CI build.

## 10. Frontend, duplicate behavior, and deployment

### 10.1 Active React client

`frontend\src\main.tsx:1-9` renders `RAGQAApp`.
The active component supports direct files and SharePoint links, scoped to a
client-generated user ID. It does not expose Google Docs, SQL ingestion,
feedback, advanced metadata filters, or the domain catalog in the inspected UI.

`auth.ts` accepts any valid-email demo login meeting its local checks, generates
an ID from email, and saves the identity in localStorage for 24 hours
(`frontend\src\auth.ts:20-119`). LoginScreen validates a password locally but
passes only email to its callback; the active app passes a fixed demo password
to `loginUser` (`frontend\src\LoginScreen.tsx:120-159`, `frontend\RAGQAApp.tsx:137-147`).
No server authentication token is issued or verified.

After any successful upload HTTP status, `handleProcessDocument` marks the
document ready without reading/polling the async response
(`frontend\RAGQAApp.tsx:177-224`). The HTTP Streamlit demo has the same problem
(`app\streamlit_app.py:97-128`). A queued or later-failed file can appear ready.

Document/question errors are shown to the user; SharePoint success uses a
JSON-parse fallback to an empty object. On direct upload failure, already-ready
document state is not consistently invalidated. UI file/URL selection and
in-flight request state need browser tests; no request-version cancellation
mechanism is present.

### 10.2 Duplicated and incomplete integration surfaces

- Active component inline fetch duplicates `ApiService` without using it.
- Health-check logic duplicates `useApiHealth`, probes documentation rather than
  readiness, and runs every five seconds.
- `UploadResponse` requires `status`/`document_id`, but actual sync API returns
  message/chunks; it lacks a discriminated queued-job shape
  (`frontend\src\types.ts:35-42`).
- `AskResponse` lists optional references/timing fields the backend does not
  emit, and omits `question_domain` (`frontend\src\types.ts:63-71`).
- `ApiService.getDocs` requests `/docs` HTML and attempts JSON decoding
  (`frontend\src\services.ts:206-223`).
- File validators and reusable hooks exist but are not wired into the active
  upload flow. Most intended `VITE_*` configuration is not consumed.
- Demo ingestion duplicates chunk/embed/store logic instead of sharing API
  indexing behavior. It supplies no per-chunk scope/provenance metadata and,
  when configured for pgvector, operates on the shared persistent table.
- The in-process demo's direct-file temporary cleanup is only on its success
  path, unlike `_process_upload_job`'s finally cleanup
  (`app\streamlit_demo.py:115-146`).
- The Streamlit HTTP demo interpolates returned answers into
  `unsafe_allow_html=True`; untrusted answer markup is not escaped
  (`app\streamlit_app.py:252-264`). Browser/Streamlit exploitability was not tested.
  React's current text rendering does not use that same raw-HTML path.

These inconsistencies can be corrected incrementally without redesigning the UI.

### 10.3 Deployment gaps

`docker-compose.yml` defines API/retrieval/inference with worker defaults 4/2/2.
It defaults to pgvector but supplies no PostgreSQL container or usable database
configuration on its own. There are no healthchecks or readiness conditions;
`depends_on` only defines startup ordering.

Selecting FAISS for the split setup leaves separate in-memory indexes in the
API and retrieval service. Even a multi-worker monolith with FAISS does not share
uploaded documents across workers. Persistent storage is necessary for this
deployment pattern, but process-local jobs/caches/metrics remain inconsistent.

Docker installs Python dependencies then `COPY . .`, runs with the base image's
default user, and does not install system Tesseract. Without `.dockerignore`,
local `.env`, `.git`, virtualenvs, node_modules, and unrelated documents can enter
the build context/image. Git ignore rules do not exclude Docker build input.
The image does not build or serve the React bundle (`Dockerfile:1-8`).

`Jenkinsfile` installs runtime requirements, runs pytest, optionally builds an
image, and leaves deployment as an echo placeholder. It does not perform actual
linting, frontend checks, coverage enforcement, or retrieval evaluation.

## 11. Existing tests and missing coverage

### 11.1 Verified validation results

| Validation | Result | What it establishes |
|---|---|---|
| Existing Python suite | **76 passed** | Existing assertions pass with local isolated filesystem, FAISS-safe defaults, external HTTP blocked, and no real model/provider calls. |
| Frontend TypeScript | **Passed** | `node .\frontend\node_modules\typescript\bin\tsc --noEmit --project .\frontend\tsconfig.json` accepts the current frontend. |
| Six synthetic probes | **All six reproduced the predicted gaps** | Specific behaviors listed in section 11.3; not full integration/security exploit tests. |
| Coverage percentage | Not measured | pytest-cov is unavailable; no dependencies were installed just for this analysis. |
| Provider/PostgreSQL/Docker/browser/OCR | Not run | No claim of production readiness or live retrieval accuracy. |

The standard test command is `python -m pytest -q`; `pytest.ini:1-3` restricts
discovery to `tests` and enables importlib mode.

For this analysis, pytest was invoked through a Python wrapper using the
existing `.venv` interpreter with `-B`, absolute test path, repository rootdir,
and `-p no:cacheprovider`. It ran in a temporary directory rather than the
repository because an existing mocked-queue test leaves `temp_big-doc.txt`.
Root dotenv loading was disabled for initial imports, remote service URLs were
empty, and unmocked Requests session HTTP was blocked. Test-created dotenv files
still exercised the configuration tests. Temporary test staging was cleaned up.
The first invocation's tests passed but its wrapper encountered a Windows
cleanup error from retaining the temporary cwd; cwd restoration was corrected
and the complete suite was rerun successfully with exit code 0.

### 11.2 Test inventory and gaps

| Module | Test functions | Covered behavior | Important missing coverage |
|---|---:|---|---|
| `tests\test_api.py` | 17 | No-store answer; mocked upload/ask; enqueue contract; unsupported extension; job response; metrics shape; feedback; metadata forwarding; remote-source handlers; locator/XOR validation; default multi-file IDs; domain response/catalog. | Real startup/shutdown; real worker execution/failure; job ownership/404 across processes; byte boundaries and copy failures; filename collisions; authenticated isolation; atomic replacement; actual retrieval/provider failures; async-client readiness. |
| `tests\test_chunking.py` | 4 | Heading, fallback/numbered labels, invalid overlap. | Exact overlap/window content and returned-length contract; empty/Unicode/negative parameters; source offsets; SQL row labels; paragraph/table preservation. |
| `tests\test_config.py` | 2 | dotenv loading and no environment overwrite. | Empty variables, inline comments, malformed numeric values, unreadable files, all defaults, model/backend validation, configuration reload effects. |
| `tests\test_db_ingestion.py` | 16 | Real temporary SQLite table/query reads; row limit; cell truncation; identifier/statement guards; empty result; DSN fallback. | PostgreSQL read-only enforcement/timeouts; database-role isolation; allowed source paths/hosts; request row cap ceiling; true truncation reporting; platform-specific SQLite path parsing. |
| `tests\test_ingestion.py` | 14 | TXT/DOCX; mocked PDF; missing/unsupported files; Latin-1; mocked Google export; Graph encoding/token cache; mocked SharePoint text download/unsupported type/locator. | Real/scanned PDF and tables; OCR; parser limits; Google byte cap/ID variants; Graph refresh/expiry/error shapes; actual download cap; redirects; alternate clouds; temporary cleanup on failures. |
| `tests\test_rag_pipeline.py` | 15 | Mocked OpenAI/HF; provider fallback; section references; irrelevant/ungrounded text; external prefix; lexical rank; response/retrieval cache reuse; scope/filter forwarding. | Cross-filter/store cache isolation; TTL/eviction/revision update; multi-worker invalidation; remote services; provider race latency; unexpected shapes; synthesis hallucinations; numeric/citation validation; multilingual/synonym retrieval. |
| `tests\test_vector_store.py` | 8 | FAISS selection/dedupe; mocked pgvector/hybrid; captured pgvector cast SQL; identifier/dedupe helpers; factory. | Real pgvector provisioning/search/index behavior; transaction recovery; backend result parity; genuine result IDs/scores/metadata; dimensions/count mismatch; FAISS deletion/ID reuse; mirrored-write failures; scoped persistence. |

Tests generally patch dependencies on the importing/using module. API
`setup_function` resets store/metrics/feedback, and a RAG autouse fixture clears
caches. API fake `generate_answer` tests do not run the true answer pipeline.
Vector result equality with strings allows old text assertions to pass without
checking structured result fidelity.

No dedicated test modules cover embedding helper behavior, retrieval/inference
service lifespans/routes, ingestion worker behavior, detailed SLO calculations,
or Streamlit/React browser flows. No labeled end-to-end evaluation measures
retrieval recall, answer correctness, citation fidelity, or abstention quality.

### 11.3 Deterministically reproduced gaps

All probes used synthetic data and mocked generation/embeddings where needed;
they did not mutate application files or contact a service.

| ID | Probe | Observed result | Evidence |
|---|---|---|---|
| C1 | Same embedding/core scope, first tag alpha then tag beta. | One vector search; beta request reused alpha text. | `app\rag.py:672-696` |
| C2 | Two independent revision-1 stores; identical Widget question, one blue source and one red source. | Second store was never searched; first store's answer was returned. | `app\rag.py:542-552,946-959` |
| C3 | FAISS add three rows; delete middle ID; add a row. | Generated IDs became `0, 2, 2`. | `app\vector_store.py:146-155,244-260` |
| C4 | Resolve two distinct Google document `/edit` URLs with default document ID. | Both identities were `edit`. | `app\main.py:121-130,366-373` |
| C5 | Serialize one labeled database row, chunk, extract final reference labels. | Reference was `Section 1`, not the row label. | `app\db_ingestion.py:102-122`, `app\chunking.py:63-69`, `app\rag.py:444-455` |
| C6 | Score 1.0 availability against the default 0.99 target. | Objective status was `at_risk`. | `app\slo_metrics.py:143-149` |

## 12. Security and reliability findings

This is the security portion of a broader codebase assessment, not a penetration
test or a dependency-CVE audit. "Source verified" means the relevant mechanism
is present/absent in the inspected source; actual exploitation, deployed
reachability, and surrounding controls are not assumed.

| ID | Priority | Finding and impact | Evidence / verification |
|---|---|---|---|
| S1 | High | No server authentication/authorization. Caller-controlled tenant scope can query or replace another scope; default removes retrieval scope filtering. Demo browser identity is forgeable and CORS is not access control. | Source verified: `app\main.py:95-116,173-239,458-516`, `app\rag.py:528-595`, `frontend\src\auth.ts:75-109`. Exposure depends on deployment. |
| S2 | High | SQL ingestion accepts caller-selected source connection/table/query with server-local SQLite paths and no host/path/table allowlist. Read-only is not authorization to disclose/index data; request max_rows is unbounded above. | Source verified: `app\schemas.py:109-132`, `app\db_ingestion.py:125-242`. No private database accessed during analysis. |
| S3 | High | App-only SharePoint access lacks per-user ACL trimming. An exposed route can index files the application can access into caller-chosen scopes. | Source verified: `app\ingestion.py:217-267,281-366`, `app\main.py:383-418`. Actual Graph grants not inspected. |
| S4 | High | Filename-derived upload staging is neither unique nor safely isolated. Same-name concurrent uploads overwrite/delete each other's file; path manipulation risk depends on filesystem layout. | Source verified: `app\main.py:282-285,307-319,349-355`. No path-traversal exploit attempted. |
| S5 | High | Missing Docker exclusions can embed secrets/unrelated files in build context/image. | `.dockerignore` absent; `Dockerfile:6` copies the entire context. No actual image or secret content inspected. |
| S6 | High | Advanced-filter cache mismatch and independent-store cache reuse can return data from the wrong intended source. Tenant/collection values are in keys, but advanced filters and store identity are not. | Confirmed C1/C2; `app\rag.py:542-552,672-696,946-959`. |
| S7 | Medium | Jobs and feedback summaries are not caller/tenant scoped. Polling returns raw exception text; correction summaries include question/correction content. | `app\ingestion_jobs.py:43-49,76-79`, `app\feedback_store.py:26-49`, `app\main.py:495-516`. |
| S8 | Medium | Resource controls are incomplete: unbounded queue/status history; unbounded question/prompt/candidate counts; remote download/extracted-text limits incomplete. | `app\ingestion_jobs.py:17-18`, `app\schemas.py:19-33`, `app\retrieval_service.py:31-42`, `app\ingestion.py:159-180,327-351`. |
| S9 | Medium | Prompt-only injection defenses, external-prefix bypass, synthesis grounding skip, and unvalidated references cannot guarantee grounded answers. | `app\rag.py:92-102,989-1040,1051-1065`. No adversarial live LLM test. |
| S10 | Medium | Full questions, filenames, Graph resource URLs, and provider exceptions can disclose sensitive context in logs. Raw HTML answer interpolation is a separate demo-client risk. | `app\main.py:269,470`, `app\ingestion.py:324`, `app\rag.py:1068-1072`, `app\streamlit_app.py:261`. Exploitability of HTML was not tested. |
| R1 | High | Local queue/status and cache revisions are incompatible with reliable multi-worker behavior. Jobs can poll as 404 on another worker; persistent writes need shared invalidation. | `app\ingestion_jobs.py`, `app\rag.py:542-552`, `docker-compose.yml:6-8`. Source-level deployment consequence, not a load test. |
| R2 | High | UI says ready after queued upload; users may ask before ingestion or after a background failure. | `frontend\RAGQAApp.tsx:194-211`, `app\streamlit_app.py:113-120`, `app\main.py:329-336`. |
| R3 | High | Scoped clear/add replacement is non-atomic; colliding IDs can replace unrelated documents; mirrored failures can split backend state. | C4 plus `app\main.py:209-227`, `app\vector_store.py:323-353,389-413,435-461`. |
| R4 | Medium | Partial structured-result refactor loses PG identity/metadata/distances, lacks backend delete/custom-ID parity, and reuses FAISS IDs. | C3 plus `app\vector_store.py:355-387,509-535,564-575`. |
| R5 | Medium | Parser/data quality loss and ambiguous citations: scanned PDF pages, DOCX tables, row identity, repeated section labels. | C5 plus `app\ingestion.py:81-106`, `app\rag.py:444-486`. |
| R6 | Medium | PostgreSQL first-use/transaction recovery/read-only behavior is under-tested; readiness can report available despite failed store setup. | `app\vector_store.py:287-289,355-416`, `app\db_ingestion.py:163-174`, `app\main.py:79-84`. Needs live integration confirmation. |
| R7 | Medium | Metrics can mislead: only selected paths instrumented, queue completion omitted, lexical proxy called quality, default availability never met. | C6 plus `app\slo_metrics.py:86-165`, `app\rag.py:958-984,1066-1076`. |

Existing positive controls include size checks on direct uploads, constrained
table identifiers, parameterized vector filters, HTTP status/timeout checks for
Requests calls, a SQLite read-only URI, file cleanup in the main upload job and
SharePoint helper, typed locator validation, bounded answer/retrieval caches,
and a prompt instruction not to follow source-document commands. These are
useful but do not replace authorization or complete resource controls.

## 13. Performance bottlenecks and scaling constraints

These are code-derived risks, not measured throughput claims.

| Bottleneck | Why it matters | Evidence |
|---|---|---|
| Blocking operations inside async routes | File copy, parsing, model encode, Requests, psycopg, and provider calls execute synchronously on the route's event-loop thread. Queuing only moves direct-upload processing after staging. | `app\main.py:243-355,359-485`, `app\retrieval_service.py:74-104`, `app\inference_service.py:48-56`. |
| Lock around the whole answer path | Slow inference holds the same lock needed for indexing; within one process asks serialize and can delay queued-job writes. | `app\main.py:209-227,472-483`. |
| FAISS searches the entire corpus | Exact flat search and requesting every vector increases result processing/sorting and filtering cost as corpus grows. | `app\vector_store.py:180-185`. |
| Index rebuild and redundant vector memory | Scoped deletion reconstructs FAISS; vectors are also retained as Python lists alongside the native index and metadata. | `app\vector_store.py:119-123,156,208-260`. |
| PostgreSQL filters lack dedicated metadata indexes | Tenant/collection/tag selection and selective ANN recall may degrade as corpus grows; query plans need measurement. | `app\vector_store.py:291-321,360-387`. |
| Duplicated remote query encoding | API embeds before remote `/search`, and retrieval service embeds again. | `app\rag.py:963,656-672`, `app\retrieval_service.py:75`. |
| Model per worker/service | API, retrieval, and even inference startup each load a local model; Compose worker counts multiply startup and memory. | Service lifespans; `docker-compose.yml`. |
| Provider race waits for slow work | Executor context shutdown can erase the intended first-completed latency benefit; both calls incur cost. | `app\rag.py:417-435`. |
| Whole remote downloads and full text/chunk batches | Download/parse/index staging can hold multiple copies of content; no extracted-text/token budget. | `app\ingestion.py:351-355`, `app\main.py:188-207`. |
| Single non-durable ingestion worker | Large documents cause head-of-line blocking; no backlog cap or persisted progress. | `app\ingestion_jobs.py:31-72`. |

## 14. Incremental improvements for review

The proposals below preserve the existing architecture and UI. API extensions
should be additive where possible; intentional behavior changes should be
explicitly approved and tested. Larger infrastructure changes are deferred
until local correctness is established.

### 14.1 First: correctness and safe local operation

| Proposal | Targeted scope | Acceptance criteria |
|---|---|---|
| Fix cache identity and filter completeness | Shared cache-key helper for all search filters and explicit store/index namespace; model/prompt/settings identity where relevant. | Regression tests for each advanced filter and two equal-revision stores; TTL/eviction/revision tests; no cross-source answer reuse. |
| Stabilize document/chunk identity | Source-aware IDs for Google/Graph/files; versioned content identity; consistent filename stem behavior; return effective document ID. | Different Google Docs and multi-dot filenames cannot replace one another unintentionally; intentional re-upload still replaces only its own scope. |
| Complete async upload contract | Typed sync/queued/error responses; poll existing job endpoint in current clients; retain current visual layout. | Queued is not displayed as completed; completed enables asking; failed/404/timeout is surfaced; tests cover the configured byte threshold and 0 mode. |
| Safely stage uploads | Unique temporary files with preserved supported suffix, bounded copy, extension validation, cleanup covering copy/enqueue failure. | Concurrent same-name uploads remain independent; all failure paths clean only their own file; cap is enforced while receiving/copying rather than only afterward. |
| Standardize client error handling | Map invalid type/empty text/locator/query errors to repository-consistent 4xx; preserve sanitized operational 5xx with logs. | No unsupported/empty input produces an unexplained 500; real unexpected errors remain visible rather than silently defaulting to success. |
| Complete vector result contract | Genuine PG row ID/text/distance/metadata; immutable unique FAISS IDs; validate arrays/counts/dimensions; explicit backend feature support. | Backend contract tests assert fields, identity uniqueness after deletion, distance semantics, mismatch failures, and supported delete/custom-ID behavior. |
| Make scoped replacement safe | Transactional PG replacement and safe mirrored-write failure policy, without changing backend selection. | Failed insertion preserves the prior indexed document; retries are idempotent; duplicate scope updates have defined behavior. |

### 14.2 Before wider access: security controls

| Proposal | Targeted scope | Acceptance criteria |
|---|---|---|
| Enforce authenticated identity and scope | Backend authentication dependency and authorized server-derived tenant/collection; protect jobs, feedback, and service routes. Keep demo mode explicit/local. | An authenticated caller cannot read/overwrite another tenant, use missing/default scope to bypass isolation, or access another caller's job/corrections. |
| Restrict connectors | Approved SQL source profiles, allowed tables/query policy, restricted SQLite roots and PostgreSQL destinations; enforce a configured maximum row budget. | Disallowed sources/paths/tables are rejected before connection; caller cannot raise cap arbitrarily; source errors are sanitized. |
| Prove read-only DB access | Least-privilege role plus explicit read-only transaction/session setup and integration tests; never silently accept failed enforcement. | PostgreSQL integration proves read-only status and rejects mutation through relevant query/function paths; timeout tests pass. |
| Respect SharePoint permissions | Authorized connector use; minimally scoped application grants or delegated permission mapping; preserve allowed principals with indexed chunks. | Users retrieve only approved source content, including after caching; ACL changes have a defined reindex/invalidation path. |
| Exclude build secrets and unnecessary files | `.dockerignore`, non-root runtime where feasible, explicit runtime secret injection, OCR system dependency if enabled. | Build context/image excludes `.env`, `.git`, environments, node_modules, and unrelated documents; selected OCR deployment can execute its parser. |
| Bound and sanitize external/untrusted data | Streaming byte caps, extracted-text/image limits, exact URL validation, question/prompt/candidate caps, safe output/log handling. | Oversized/unsupported inputs fail predictably; raw untrusted answer HTML is not inserted; logs and job errors pass redaction tests. |
| Tighten grounding boundaries | Explicitly authorize external mode, align prefix/section semantics, validate citations, test malicious source instructions and unsupported claims. | Default document-only mode cannot bypass checks with a leading prefix; each returned source refers to retained authorized evidence. |

### 14.3 Retrieval accuracy and citations

First establish a representative labeled benchmark, then tune rather than
assuming a larger model or new backend will improve quality.

1. Preserve parser provenance: PDF page numbers, DOCX paragraph/table positions,
   SQL primary-key/row identity, original source ID/URL, and chunk offsets.
   Maintain current parsers initially; add format-specific enhancements under
   tests.
2. Introduce paragraph/sentence/token-aware boundaries incrementally, retaining
   overlap and backward-compatible labels. Record tokenizer/embedding model
   version; test multilingual text, long tables, abbreviations, and numbers.
3. Keep dense retrieval and the existing lexical reranker as the baseline.
   Evaluate lexical+dense fusion or a cross-encoder behind an explicit setting;
   do not relabel mirrored FAISS/PG storage as hybrid search.
4. Keep structured retrieval results through ranking and prompting. Return an
   additive `sources` list with genuine document/chunk IDs, page/offset, snippet,
   and distance semantics; do not present raw L2 distance as answer confidence.
5. Validate model-emitted CTX citations against the prompt mapping, and return
   only actual supporting sources. Avoid accepting arbitrary References text.
6. Evaluate relevance/abstention on synonym-heavy, short, multilingual, numerical,
   and synthesis questions before weakening lexical gates. Domain classification
   should not exempt a response from evidence quality requirements.
7. Add metadata to the prompt only when authorized and relevant. Decide
   explicitly whether conversational follow-ups should remain unsupported or
   receive bounded, scoped prior-turn context; do not infer it from UI history.

### 14.4 Evaluation and operational reliability

- Build a small versioned, non-sensitive evaluation corpus with queries,
  relevant document/chunk IDs, supported facts, and expected abstentions.
- Measure Recall@K, Precision@K, MRR/nDCG where applicable, factual/numeric
  correctness, citation validity/coverage, abstention precision/recall, latency,
  and cost. Separate deterministic regression tests from optional provider tests.
- Wire real evaluation artifacts into the existing dashboard. Only then add a
  CI quality gate with documented thresholds and a true nonzero failure status.
- Add request-wide metrics middleware, separate ingestion acceptance/completion
  and provider success/degraded fallback, and repair the bounded-rate SLO
  threshold. Test percentile math and error-budget semantics.
- For immediate local reliability, use one API worker with FAISS/process-local
  jobs. Before multi-worker deployment, provide durable/shared jobs, scoped
  status, bounded queues/retention, and persistent-index cache invalidation.
- Add small `/health` and `/ready` endpoints; readiness should check only the
  dependencies needed for the selected topology. Do not equate `/docs` with
  data/provider readiness.

### 14.5 Performance and maintainability

- Move blocking pipeline/network work off async event loops and narrow the store
  lock to safe mutation/snapshot boundaries; preserve metadata isolation under
  concurrent reads/replacements.
- Avoid API-side duplicate embeddings when remote retrieval handles encoding,
  and avoid embedding-model preload in generation-only inference workers.
- Benchmark selective FAISS retrieval and PG query plans before choosing more
  indexing infrastructure. Add metadata indexes based on measured filter use.
- Use bounded batching/streaming where supported and define a prompt token budget.
  Make provider timeouts/retry/backoff and auto-mode loser behavior explicit.
- Reuse the existing typed frontend API layer after correcting its response
  models; wire intended environment settings without changing the layout.
  Generate/check client contracts against FastAPI OpenAPI where practical.
- Consolidate shared indexing logic for demos carefully; retain explicit
  distinction between demo session state and persistent shared storage.
- Validate configuration on startup, remove or clarify unused embedding
  constants, and choose dependency bounds that actually support used APIs.
- Add Python/frontend lint/type/test checks to existing CI incrementally.
  Stop tracking bytecode in a separately approved housekeeping change; ignored
  generated files already tracked by Git do not disappear automatically.

## 15. Recommended review order

Approve and implement a small first batch: cache isolation, collision-resistant
document/FAISS IDs, safe upload staging, and correct queued-upload handling,
with focused regression tests. Separately approve authentication/connector/build
controls before making the service available beyond trusted local use.

Next, preserve structured source provenance and establish a measured retrieval
benchmark. Only after that should ranking/chunking changes and performance
tuning be enabled and evaluated.

The existing FastAPI/React/Streamlit/backend choices can remain in place.
No replacement application, architecture redesign, UI redesign, source fix,
dependency installation, or commit was performed for this report.
