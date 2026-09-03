# AI Integration Plan and Implementation — RAG Document QA System

## 1. Purpose
This document defines the **AI integration plan and implementation approach** for the RAG Document QA System.

It explains how artificial intelligence is integrated into the application for:
- document understanding,
- embedding generation,
- semantic retrieval,
- answer generation,
- section-based citation,
- graceful fallback when the external LLM is unavailable.

This plan is based on the current implementation in:
- `app/main.py` — endpoints and the shared indexing path
- `app/ingestion.py` — uploads, Google Docs, SharePoint (Microsoft Graph)
- `app/db_ingestion.py` — read-only SQL row serialization
- `app/chunking.py`
- `app/embeddings.py`
- `app/vector_store.py` — FAISS / pgvector / hybrid
- `app/rag.py` — retrieval, reranking, relevance/grounding gates, caching, provider fallback
- `app/retrieval_service.py`, `app/inference_service.py` — optional split topology
- `app/slo_metrics.py`, `app/feedback_store.py` — observability and feedback
- `streamlit_app.py`, `app/streamlit_demo.py`

---

## 2. AI Integration Goals
The AI layer should enable the application to:

1. extract meaning from uploaded documents,
2. find the most relevant passages for a user question,
3. produce a grounded answer based only on document context,
4. cite the section(s) used in the answer,
5. reduce hallucinations and repeated outputs,
6. fail gracefully when the LLM provider is unavailable.

---

## 3. Current AI Architecture
The application already follows a **Retrieval-Augmented Generation (RAG)** pattern.

### High-Level Flow
1. Content enters through one of the ingestion endpoints — a file upload, a Google Docs URL, a SharePoint file (Microsoft Graph), or the rows of a read-only SQL query — or through Streamlit.
2. The matching extractor produces plain text.
3. The text is split into overlapping chunks with inferred section labels.
4. Each chunk is converted into an embedding vector and tagged with scoping metadata (`tenant_id`, `collection_id`, `document_id`, and optional `document_date` / `author` / `tag` / `source_system`).
5. Embeddings are stored in **FAISS**, **PostgreSQL + pgvector**, or a **hybrid** mirror of both.
6. When the user asks a question, the question is embedded and classified into a `question_domain`.
7. The system retrieves a candidate pool, lexically reranks it, keeps the top `TOP_K`, and applies a lexical relevance gate — if the question and context share too little vocabulary, no LLM call is made.
8. The LLM (OpenAI, Hugging Face, or `auto`) generates a grounded answer; grounding gates then verify the answer is supported and on-topic before it is returned.
9. The answer is returned with a `References:` line for the relevant sections, plus the detected `question_domain`. Responses and retrieval results are cached in memory (30-minute TTL).

Retrieval and generation run in-process by default; setting `RETRIEVAL_SERVICE_URL` / `INFERENCE_SERVICE_URL` routes them to standalone services over a shared persistent index.

---

## 4. AI Components and Their Roles

| Component | File | AI Responsibility |
|---|---|---|
| Ingestion | `app/ingestion.py` | Extract text from uploads (TXT/DOCX/PDF/image OCR), Google Docs, and SharePoint files |
| Database ingestion | `app/db_ingestion.py` | Serialize the rows of a read-only `SELECT` into indexable text |
| Chunking | `app/chunking.py` | Break text into overlapping chunks and infer section labels |
| Embeddings | `app/embeddings.py` | Convert text chunks and questions into dense vectors |
| Vector Store | `app/vector_store.py` | Save and retrieve semantically similar chunks (FAISS / pgvector / hybrid), with metadata filters |
| RAG Logic | `app/rag.py` | Rerank, gate, prompt, call LLMs, verify grounding, format references, cache |
| Question domains | `app/rag.py` | Classify each question into a 20-entry catalog (`/question-domains`) |
| API Layer | `app/main.py` | Expose the ingestion, ask, and observability endpoints |
| Observability | `app/slo_metrics.py`, `app/feedback_store.py` | Latency/error/quality metrics (`/metrics`); thumbs + corrections (`/feedback`) |
| UI | `streamlit_app.py`, `app/streamlit_demo.py` | Let users ingest content and ask questions |

---

## 5. AI Models and Providers

### 5.1 Embedding Model
Current implementation uses:
- **Sentence Transformers**
- model: **`all-MiniLM-L6-v2`**

This model is lightweight, fast, and suitable for semantic search.

### 5.2 LLM Providers
Supported providers:

| Provider | Usage |
|---|---|
| OpenAI | main answer generation path |
| Hugging Face Inference API | alternative provider |

A third value, `auto`, submits the prompt to both providers and returns the first non-empty reply.

Configured through environment variables:

```env
LLM_PROVIDER=openai            # openai | huggingface | auto
OPENAI_LLM_MODEL=gpt-4o-mini   # LLM_MODEL is still accepted as a legacy alias
HUGGINGFACE_LLM_MODEL=google/flan-t5-base
OPENAI_API_KEY=...
HUGGINGFACE_API_KEY=...
```

---

## 6. Retrieval and Context Grounding Strategy
The system should answer **only from the uploaded document**.

### Grounding Rules
- retrieve the top relevant chunks from vector search,
- build the prompt using only retrieved content,
- instruct the LLM to avoid unsupported claims,
- include section references in the final answer,
- deduplicate repeated retrieved chunks,
- clear stale vector data on each new upload.

### Current Strengths
The existing implementation already:
- retrieves a larger candidate pool and **lexically reranks** it before keeping `TOP_K`,
- applies a **lexical relevance gate** that skips the provider call when the question and context do not overlap,
- applies **grounding gates** after generation (`_is_answer_grounded`, `_answer_addresses_question`) that replace an unsupported answer with a fixed "no relevant information" response,
- supports **metadata-scoped retrieval** (tenant / collection / document / date / author / tag / source),
- deduplicates repeated chunks,
- clears old vector data on re-upload,
- appends `References:` lines from section labels,
- caches responses and retrieval results (30-minute TTL, invalidated by the vector store's `revision` counter),
- returns a concise document-grounded fallback sentence if the provider fails.

---

## 7. Detailed Implementation Plan

## Phase 1 — Baseline AI Pipeline
### Objective
Establish a working end-to-end RAG flow.

### Implementation
- extract document text using `ingestion.py`,
- split it using `chunking.py`,
- generate embeddings with `embed_text`,
- store embeddings in `VectorStore`,
- answer via `generate_answer`.

### Deliverables
- `/upload` endpoint working
- `/ask` endpoint working
- Streamlit UI wired to the API

---

## Phase 2 — Persistent Vector Retrieval
### Objective
Move from temporary in-memory retrieval to a persistent and scalable backend.

### Implementation
- enable `pgvector` in PostgreSQL,
- configure:

```env
VECTOR_DB_BACKEND=pgvector
PGVECTOR_DSN=postgresql://postgres:<password>@localhost:5432/ragdb
PGVECTOR_TABLE_NAME=rag_embeddings
PGVECTOR_PRIMARY_SEARCH=pgvector
```

- create the vector table with `scripts/create_pgvector_table.sql`,
- store chunk text and embeddings for retrieval.

### Deliverables
- persistent search results
- database visibility in PostgreSQL / pgAdmin
- reusable document knowledge base

---

## Phase 3 — Answer Quality Improvements
### Objective
Ensure answers are accurate, concise, and not repeated.

### Implementation
- add section labels in chunks,
- remove duplicate retrieved chunks,
- clear previous uploads before indexing a new document,
- add `References:` to the final answer,
- generate a document-based fallback when the external LLM fails.

### Deliverables
- more exact answers
- clear section references
- reduced stale or repeated outputs

---

## Phase 4 — Robust Provider Handling
### Objective
Handle third-party LLM failures gracefully.

### Implementation
- lazy-load the OpenAI client,
- support Hugging Face as an alternative,
- catch provider/network/quota errors,
- return a concise document-grounded fallback answer.

### Benefits
- better user experience
- application remains usable even if the provider is down

---

## Phase 5 — AI Observability and Quality Monitoring
### Objective
Measure and improve answer quality over time.

### Status: partially implemented
- `app/slo_metrics.py` serves a structured SLO report at `GET /metrics`: a p50/p90/p95/p99 latency distribution, availability, throughput, and retrieval-hit quality, each scored against a configurable target (`SLO_*` env vars) with an attainment ratio, an error-budget figure, and an overall `healthy` / `at_risk` / `breached` status.
- `app/feedback_store.py` records thumbs up/down and free-text corrections, at `POST /feedback` and `GET /feedback/summary`.
- `app/metrics_dashboard.py` is a Streamlit Precision@K / Recall@K dashboard with a CI-style quality gate — still driven by synthetic sample data, to be wired to real evaluation output.

### Remaining
Add monitoring for:
- upload success rate,
- percentage of fallback answers,
- frequency of low-quality/empty answers,
- export to an external metrics backend (Prometheus/Grafana) rather than in-memory only.

### Suggested Metrics
| Metric | Purpose |
|---|---|
| Retrieval latency | measure vector search performance |
| LLM latency | measure provider responsiveness |
| Error rate | detect provider or API failures |
| Fallback rate | measure how often external AI fails |
| Citation presence rate | ensure answers include references |

---

## 8. Current Implementation Mapping

### 8.1 `app/embeddings.py`
**Current role:**
- loads the SentenceTransformer lazily, What is lazily?
- caches the model,
- converts chunks/questions into `float32` vectors.

**Why it matters for AI integration:**
- this is the semantic representation layer for retrieval.

### 8.2 `app/vector_store.py`
**Current role:**
- supports `faiss`, `pgvector`, and `hybrid` backends,
- stores embeddings and chunk text,
- performs similarity search,
- removes duplicate retrieval results,
- can clear stale data.

**AI integration value:**
- ensures the LLM receives the right evidence from the document.

### 8.3 `app/rag.py`
**Current role:**
- embeds the user question,
- retrieves relevant chunks,
- builds a grounded prompt,
- sends the prompt to OpenAI or Hugging Face,
- returns a final answer with references,
- uses a concise fallback if the provider fails.

**AI integration value:**
- this is the core orchestration layer.

### 8.4 `app/chunking.py`
**Current role:**
- splits the document into overlapping chunks,
- labels chunks with inferred sections.

**AI integration value:**
- section-aware chunks directly support answer citations.

### 8.5 `app/ingestion.py` and `app/db_ingestion.py`
**Current role:**
- `ingestion.py` extracts text from uploads (PDF/DOCX/TXT/image OCR), Google Docs, and SharePoint files (Microsoft Graph, app-only token cached per client id).
- `db_ingestion.py` runs one read-only `SELECT` (PostgreSQL or SQLite) and serializes each row to a `[<table> N] col: val; …` line; writes are blocked by a read-only connection, a `SELECT`/`WITH`-only filter, and a row cap.

**AI integration value:**
- broadens the evidence base beyond uploaded files while keeping a single downstream chunk → embed → index path and one grounding model.

### 8.6 `app/retrieval_service.py` / `app/inference_service.py`
**Current role:**
- expose `/search` and `/generate`; `rag.py` calls them over HTTP when the corresponding service URL is configured, importing its reranker and provider helpers so behavior stays identical to the monolith.

---

### Already delivered since the original plan
- multi-document / multi-collection retrieval with metadata scoping,
- lexical reranking of retrieved chunks before generation,
- a user feedback loop (`/feedback`) for answer-quality signal,
- question-domain classification on every answer,
- additional ingestion sources (Google Docs, SharePoint, SQL rows),
- async ingestion for large uploads.

### Short-Term Enhancements
1. add a confidence score for each answer,
2. return the top supporting chunks in the UI,
3. expose retrieval scores for debugging,
4. improve prompt engineering for more concise answers,
5. relax the grounding gate for paraphrased/synthesized answers that are still supported.

### Medium-Term Enhancements
1. carry `source_document`, page number, and section ID through to the `References:` line,
2. true hybrid lexical + vector scoring (not just a lexical rerank of vector hits),
3. query rewriting for ambiguous questions,
4. answer summarization and bullet output modes,
5. per-user permission-trimmed retrieval (delegated auth for SharePoint).

### Long-Term Enhancements
1. conversational memory across questions,
2. local/offline LLM support,
3. domain-tuned prompt templates or model fine-tuning,
4. a query-time text-to-SQL path for structured data (today's database ingestion is row serialization only).

---

## 10. AI Integration Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Invalid API key | Answer generation fails | fallback answer and provider error handling |
| Quota exceeded | degraded user experience | graceful fallback and provider switching |
| Weak chunking | poor retrieval | section-aware chunking and overlap |
| Duplicate retrieval results | repeated answers | deduplication in search and answer logic |
| Stale data from previous upload | incorrect answers | clear vector store on re-upload |
| Large documents | slower inference | tune chunk size, overlap, and top-k |
| Missing citations | weak trustworthiness | enforce `References:` in final answer |

---

## 11. Security and Governance for AI Integration

### Required Controls
- do not commit API keys,
- do not log raw secrets,
- restrict network access in production,
- ensure only supported documents are uploaded,
- avoid exposing provider stack traces in the UI.

### Responsible AI Practices
- ground responses in retrieved context,
- return `I don't know.` or a concise fallback when unsupported,
- keep provenance visible through section references,
- minimize hallucinations by prompt restriction.

---

## 12. Testing Plan for AI Integration
The AI integration must be validated through:

### Unit Tests
- embeddings shape and type
- retrieval deduplication
- fallback answer formatting
- section reference extraction

### Integration Tests
- upload → embed → store → retrieve → answer
- each ingestion endpoint (upload / Google Docs / SharePoint / database) reaches the shared indexing path
- SharePoint token caching and share-URL encoding (mocked Graph)
- SQLite row ingestion end to end, plus the read-only SQL statement guards
- relevance-gate and grounding-gate behavior (answer downgraded to "no relevant information")
- response/retrieval cache reuse across repeated questions
- pgvector connectivity
- provider fallback when OpenAI/Hugging Face fails; `auto` mode selection

### System Tests
- Streamlit upload and answer flow
- PostgreSQL persistence visibility
- exact section-based answer response

### Success Criteria
- answers are concise,
- no repeated sections unless relevant,
- references are visible,
- upload and ask flows remain stable,
- fallback remains grounded in the document.

---

## 13. Implementation Checklist

### Completed / Existing
- [x] FastAPI integration (four ingestion endpoints + `/ask`)
- [x] Streamlit integration (API-backed and in-process)
- [x] sentence-transformer embeddings
- [x] FAISS, pgvector, and hybrid vector backends
- [x] Google Docs, SharePoint (Microsoft Graph), and SQL-row ingestion
- [x] async ingestion queue for large uploads (`/ingestion-jobs/{id}`)
- [x] metadata-scoped retrieval (tenant / collection / document / date / author / tag / source)
- [x] lexical reranking + relevance gate + grounding gates
- [x] section references in answers
- [x] response and retrieval caching
- [x] question-domain classification (`/question-domains`)
- [x] `auto` provider mode + document-grounded fallback when the provider fails
- [x] SLO metrics (`/metrics`) and feedback capture (`/feedback`)

### Recommended Next Steps
- [ ] add confidence score in responses
- [ ] carry `source_document` and page metadata into `References:`
- [ ] add a dedicated `/health` endpoint for AI readiness
- [ ] wire the metrics dashboard to real evaluation output
- [ ] export metrics to an external backend (Prometheus/Grafana)
- [ ] per-user permission-trimmed retrieval for SharePoint
- [ ] add local/offline LLM option

---

## 14. Example End-to-End AI Flow
1. User uploads a specification document.
2. The API extracts the text.
3. The system creates labeled chunks such as:
   - `[Section 1: Overview] ...`
   - `[Section 2: Requirements] ...`
4. The embeddings are stored in `rag_embeddings`.
5. The user asks: **"What are the main requirements?"**
6. The app retrieves the most relevant chunks.
7. The AI returns a concise answer such as:

```text
The main requirements include document upload, semantic retrieval, and answer generation.

References: [Section 2: Requirements]
```

---

## 15. Summary
The application already contains a strong foundation for AI integration using a **RAG architecture**.

The current implementation supports:
- semantic retrieval,
- external LLM integration,
- PostgreSQL + pgvector storage,
- section-referenced answers,
- graceful fallback behavior.

This plan documents both the **current AI implementation** and the **next steps** required to improve quality, reliability, and production readiness.
