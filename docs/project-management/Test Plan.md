# Test Plan — RAG Document QA System

## 1. Purpose
This document describes the testing approach for the RAG Document QA System: what is
tested, how, at which level, and what "passing" means before a release.

It reflects the current implementation — four ingestion sources, three vector
backends, three LLM provider modes, an optional service split, and the retrieval
reranking / grounding-gate / caching behavior in `app/rag.py`.

---

## 2. Scope

### In scope
- FastAPI endpoint contracts: `/upload`, `/upload-google-doc`, `/upload-sharepoint`,
  `/ingest-database`, `/ask`, `/question-domains`, `/ingestion-jobs/{job_id}`,
  `/metrics`, `/feedback`, `/feedback/summary`.
- Text extraction per source: PDF, DOCX, TXT, image OCR, Google Docs, SharePoint
  (Microsoft Graph), and read-only SQL rows.
- Chunking and section-label inference.
- Embedding shape/type and lazy model loading.
- Vector store behavior for FAISS (pgvector/hybrid covered by unit-level fakes).
- RAG orchestration: candidate-pool retrieval, lexical rerank, the relevance gate,
  the grounding gates, `References:` assembly, provider fallback, `auto` mode, and
  the response/retrieval caches.
- Request validation (missing SharePoint locator, database `table` XOR `query`) →
  HTTP 422.
- Metadata scoping (tenant / collection / document filters).
- Configuration loading from `.env`.

### Out of scope (current suite)
- Live PostgreSQL + pgvector / hybrid integration (only fakes are exercised).
- The service-split HTTP paths (`RETRIEVAL_SERVICE_URL` / `INFERENCE_SERVICE_URL`).
- Concurrency behavior of the shared `vector_store` lock.
- Real network calls to OpenAI / Hugging Face / Microsoft Graph.
- Load, performance, and UI automation.

---

## 3. Test Levels

| Level | What it checks | Tooling |
|---|---|---|
| Unit | One module in isolation (chunking, embeddings shape, config loader, SQL guards, URL encoders) | `pytest` |
| Integration | Endpoint → shared indexing path → retrieval → answer, with heavy deps stubbed | `pytest` + `fastapi.testclient` + `monkeypatch` |
| System (manual) | Streamlit flows, live pgvector persistence, real provider calls | manual walkthrough |

All automated tests are hermetic: `monkeypatch` replaces `extract_text`,
`chunk_text`, `embed_text`, `VectorStore`, `generate_answer`, and the provider
client factories, so no test downloads a model or opens a socket. SharePoint tests
stub `requests`; database tests use a real temporary SQLite file.

---

## 4. Automated Test Inventory

`python -m pytest -q` → **76 tests, 7 files**.

| File | Tests | Coverage |
|---|---|---|
| `tests/test_api.py` | 17 | Every endpoint; upload → ask smoke; async-queue path; Google Docs / SharePoint / database ingestion; advanced retrieval filters; feedback capture + summary; question-domain response; 422 validation cases |
| `tests/test_ingestion.py` | 14 | TXT/DOCX/PDF extraction, encoding fallback, unsupported extension, missing file; Google Docs URL parsing; SharePoint share-URL encoding, token caching, missing-credential and unsupported-type errors |
| `tests/test_db_ingestion.py` | 16 | SQLite table + query round-trips; row cap; env-DSN fallback; empty-result error; `_validate_select` (non-SELECT, multi-statement, embedded write keyword); `_validate_identifier`; `_build_effective_query`; scheme allowlist |
| `tests/test_rag_pipeline.py` | 15 | HF and OpenAI generation; provider-error fallback; section-reference append; dedupe; irrelevant-context short-circuit; ungrounded-output block; partial-overlap rejection; rerank ordering; response cache reuse; retrieval cache reuse; collection scope; advanced metadata filters |
| `tests/test_vector_store.py` | 8 | Backend override; FAISS add/search/dedupe; pgvector via fake; hybrid primary selection; `%s::vector` cast; identifier rejection; `_dedupe_texts` |
| `tests/test_chunking.py` | 4 | Overlap, section-label inference, boundary conditions |
| `tests/test_config.py` | 2 | `.env` loading from CWD; no override of an already-set variable |

---

## 5. Representative Test Cases

| ID | Scenario | Expected |
|---|---|---|
| TC-01 | `POST /ask` with nothing indexed | 200, `"No document uploaded yet."`, `question_domain` present |
| TC-02 | `POST /upload` small text file | 200, `"Document processed successfully"`, prior scope cleared |
| TC-03 | `POST /upload` ≥ `ASYNC_INGESTION_MIN_BYTES` | 200, `status: "queued"`, `job_id`; `/ingestion-jobs/{id}` returns status |
| TC-04 | `POST /upload` unsupported extension | `ValueError("Unsupported file type")` propagates (documented gap: surfaces as 500) |
| TC-05 | `POST /upload-google-doc` valid URL | 200, chunk count returned |
| TC-06 | `POST /upload-sharepoint` with no locator | 422 (schema `model_validator`) |
| TC-07 | `POST /upload-sharepoint` valid URL (mocked Graph) | 200; Graph token fetched once and cached |
| TC-08 | `POST /ingest-database` with both `table` and `query` | 422 |
| TC-09 | `extract_database_text` on a non-SELECT query | `ValueError`, provider never invoked |
| TC-10 | `extract_database_text` SQLite table | rows serialized as `[<table> N] col: val; …`, row cap honored |
| TC-11 | `/ask` where retrieved context shares no terms with the question | fixed "no relevant information" response, no LLM call |
| TC-12 | LLM returns an answer not supported by context | grounding gate replaces it with the fixed response |
| TC-13 | Same question asked twice | second answer served from the response cache (no re-embed, no re-search, no provider call) |
| TC-14 | Provider raises (quota/network) | document-grounded fallback sentence, still with `References:` when labels exist |
| TC-15 | `/ask` with `collection_id` set | retrieval `filters` carry the collection; other collections not matched |
| TC-16 | `POST /feedback` with rating `"maybe"` | 422; valid up/down recorded and reflected in `/feedback/summary` |

---

## 6. Entry / Exit Criteria

### Entry
- Code compiles and imports (`python -c "import app.main"`).
- Dependencies installed from `requirements.txt` (+ `requirements-dev.txt` for lint/type checks).

### Exit (release gate)
- `python -m pytest -q` — all tests pass, exit code 0.
- No open Critical or High defect (see severity table in
  `Software_Quality_Management.md`).
- New or changed pipeline behavior has a matching test.
- Docs updated for any new endpoint, config variable, or ingestion source.
- For a pgvector/hybrid deployment: manual confirmation that rows land in
  `rag_embeddings` and `/ask` returns grounded answers.

---

## 7. Regression Focus Areas
Changes near these have historically broken behavior — always re-run the full suite:

- chunk label format (`[Section N]`) — it is a contract between `chunking.py` and
  `rag.py`'s reference extraction,
- the relevance and grounding gates — easy to make too strict (drops good answers)
  or too loose (lets hallucinations through),
- cache keys in `rag.py` — must include the vector store `revision` and the active
  provider/model so a re-index or a config change invalidates stale answers,
- the SQL `_validate_select` filter — must keep failing closed,
- the `"default"` → `None` scope normalization in `main.py` and `rag.py`.

---

## 8. Known Gaps and Recommended Additions
- Tests for the pgvector and hybrid backends against a real database.
- Tests for the retrieval/inference service HTTP contract.
- A concurrency test for `vector_store_lock` under parallel `/ask`.
- Coverage measurement (`pytest --cov`) and JUnit XML output for CI trends.
- Wiring `black` / `isort` / `flake8` / `mypy` into the Jenkins "Lint & Test" stage.
- A negative test asserting the desired 4xx (not 500) for unsupported upload types.
