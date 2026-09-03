# Intelligent Document Question Answering System (RAG-Based)

## Table of Contents
1. [Project Overview](#project-overview)
2. [Overall Project Approach](#overall-project-approach)
3. [System Architecture](#system-architecture)
4. [Technology Stack](#technology-stack)
5. [DevOps and Delivery Approach](#devops-and-delivery-approach)
6. [Testing Strategy](#testing-strategy)
7. [Test Cases and Tests Performed](#test-cases-and-tests-performed)
8. [Test Reports and Outcomes](#test-reports-and-outcomes)
9. [How to Run](#how-to-run)

## Project Overview
This project delivers an AI-powered document question answering platform using Retrieval-Augmented Generation (RAG). Users bring content from several sources — direct uploads (PDF, DOCX, TXT, image files), shared Google Docs, SharePoint / OneDrive-for-Business files (via Microsoft Graph), and rows returned by a read-only SQL query (PostgreSQL or SQLite) — then ask natural-language questions. The platform retrieves semantically relevant context from indexed content and generates grounded answers.

The implementation supports local and API-driven workflows:
- FastAPI backend for upload and question answering endpoints.
- Streamlit user interfaces for interactive testing and demonstrations.
- Pluggable LLM providers and vector-store backends for flexibility.

## Overall Project Approach
The project follows a modular, API-first, and testable engineering approach:

1. Problem decomposition:
- Separate concerns into ingestion, chunking, embeddings, retrieval, generation, and interface layers.

2. Grounded-answer design:
- Use retrieval before generation so responses are based on document context instead of model-only memory.

3. Backend-first reliability:
- Implement core capabilities in FastAPI endpoints (`/upload`, `/upload-google-doc`, `/upload-sharepoint`, `/ingest-database`, `/ask`) and reuse them from frontend handlers. All ingestion endpoints funnel into one chunk → embed → index path and share the same tenant/collection/document scoping fields.

4. Incremental quality gates:
- Validate behavior with unit and API tests during development and CI execution.

5. Deployment readiness:
- Package the service with Docker and automate build-and-test in Jenkins for repeatable releases.

## System Architecture
The architecture uses a staged RAG pipeline with clear module boundaries:

1. Ingestion layer:
- Extract text from PDF, DOCX, TXT, and image documents (OCR).
- Fetch and extract plain text from shared Google Docs URLs.
- Download and extract SharePoint / OneDrive-for-Business files through Microsoft Graph using an app-only (client-credentials) token (`app/ingestion.py`).
- Serialize the rows of a single read-only `SELECT` (PostgreSQL or SQLite) into text, with writes blocked by a read-only connection, a `SELECT`/`WITH`-only statement filter, and a row cap (`app/db_ingestion.py`). This is row serialization only — there is no query-time text-to-SQL path.

2. Chunking layer:
- Split extracted text into overlapping chunks for better retrieval relevance.

3. Embedding layer:
- Convert text chunks and user questions into dense vectors using sentence-transformer embeddings.

4. Vector storage and retrieval layer:
- Store vectors in FAISS (default) and retrieve top-K nearest chunks for a query.

5. Generation layer:
- Build a prompt from retrieved chunks and call configured LLM provider to produce the final answer.

6. Interface layer:
- FastAPI endpoints expose programmatic access.
- Streamlit event handlers coordinate upload, ask, and clear actions with stable UI state.

Reference architecture details are documented in [docs/architecture.md](docs/architecture.md).

## Technology Stack
The stack is selected to balance local simplicity and production extensibility.

Backend and API:
- Python 3.10+
- FastAPI
- Uvicorn

RAG and AI:
- SentenceTransformers (embedding generation)
- FAISS (in-memory vector similarity search)
- OpenAI Responses API (optional provider)
- Hugging Face Inference API (optional provider)

Multimodal and external ingestion:
- Pillow + pytesseract (image OCR)
- requests (Google Docs text export fetch; Microsoft Graph token + SharePoint file download)
- psycopg / stdlib sqlite3 (read-only SQL row ingestion — no new dependency)

Frontend and interaction:
- Streamlit

Data and storage options:
- FAISS default in-memory index
- Optional PostgreSQL + pgvector integration

Testing and quality:
- Pytest
- FastAPI TestClient
- Monkeypatch-based isolation for external model calls

DevOps and packaging:
- Docker
- Jenkins Declarative Pipeline
- Requirements files for runtime and development dependencies

## DevOps and Delivery Approach
The project applies practical DevOps foundations for reproducible builds and quality checks:

1. Version-controlled automation:
- `Jenkinsfile` defines CI stages for environment setup, dependency installation, test execution, and optional Docker build.

2. Containerization:
- `Dockerfile` packages the service with dependencies for consistent run behavior across environments.

3. Environment configuration:
- Config is loaded via environment variables and optional `.env` for local development.
- Secrets such as API keys remain outside source-controlled code.

4. Cross-platform support:
- Scripts and pipeline configuration support Windows and Linux workflows.

5. Release confidence:
- Test execution is a required validation gate before artifact creation.

## Testing Strategy
Testing is designed to validate behavior at module and API levels while minimizing flaky external dependencies:

1. Unit testing:
- Validate ingestion, chunking, configuration logic, and vector-store behavior.

2. API testing:
- Validate FastAPI endpoint contracts for `/upload`, `/upload-google-doc`, `/upload-sharepoint`, `/ingest-database`, and `/ask`.

3. Pipeline testing:
- Validate retrieval-to-generation orchestration and error handling.

4. Controlled external dependency behavior:
- Use monkeypatching/stubs to isolate model and network calls.

5. Regression readiness:
- Maintain focused tests for core path stability as features evolve.

## Test Cases and Tests Performed
The current repository includes tests under `tests/` covering key scenarios.

Document ingestion and parsing:
- [tests/test_ingestion.py](tests/test_ingestion.py): validates supported file handling, Google Docs URL extraction, and SharePoint/Graph fetch behavior (token caching, share-URL encoding, unsupported types).
- [tests/test_db_ingestion.py](tests/test_db_ingestion.py): validates SQLite row serialization end to end plus the read-only statement guards (SELECT-only, single-statement, row cap, scheme allowlist).

Chunking behavior:
- [tests/test_chunking.py](tests/test_chunking.py): validates chunk generation and overlap logic.

Configuration behavior:
- [tests/test_config.py](tests/test_config.py): validates environment-driven configuration defaults and overrides.

Vector retrieval behavior:
- [tests/test_vector_store.py](tests/test_vector_store.py): validates vector insertion and similarity search responses.

API contract behavior:
- [tests/test_api.py](tests/test_api.py): validates the upload / Google Docs / SharePoint / database-ingestion / ask endpoints, request/response shape, validation errors (422), and service interactions.

RAG orchestration:
- [tests/test_rag_pipeline.py](tests/test_rag_pipeline.py): validates retrieval plus answer-generation flow and boundary conditions.

## Test Reports and Outcomes
Latest local verification (from repository context):
- Command: `python -m pytest -q`
- Result: 76 tests passed with exit code `0`.

Quality interpretation:
- Core modules and endpoint behavior are validated by automated checks.
- RAG pipeline logic has baseline regression coverage.
- External AI dependencies are tested in a controlled way to keep CI reliable.

Recommended report enhancements for future iterations:
- Add coverage measurement (`pytest --cov`) and publish a coverage summary in CI.
- Add structured JUnit XML output from pytest for Jenkins trend visualization.
- Add performance sanity checks (ingestion time, query latency) for release criteria.

## How to Run
Run backend API:

```bash
uvicorn app.main:app --reload
```

Run Streamlit UI:

```bash
streamlit run streamlit_app.py
```

Run automated tests:

```bash
python -m pytest -q
```
