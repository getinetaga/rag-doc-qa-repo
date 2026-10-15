# API security and reliability operations

The API now requires an individual API key and server-owned tenant/project
grants. There is no anonymous compatibility switch. Hybrid retrieval, agents,
ConPro integration, and a UI redesign are not part of this hardening change.

## Configure users before starting the API

1. Create a private directory outside the repository and Docker build context.
   Only the operator and service account should be able to read/write it.
2. Generate a separate high-entropy key for each user. This example prints a new
   key once for delivery through a secure channel; **do not run it in a recorded
   terminal or paste its output into an issue/chat**:

   ```powershell
   .\.venv\Scripts\python.exe -c "import hashlib,secrets; k=secrets.token_urlsafe(32); print('Personal key:', k); print('SHA-256:', hashlib.sha256(k.encode()).hexdigest())"
   ```

3. Create `C:\RAG-Config\rag-access.json` (or another private external path).
   Replace the placeholder digest below with the generated SHA-256 value.
   **Never store the plaintext key in this file.**

   ```json
   {
     "users": [
       {
         "user_id": "operator-1",
         "key_sha256": "REPLACE_WITH_64_LOWERCASE_HEXADECIMAL_CHARACTERS",
         "roles": ["read", "ingest"],
         "scopes": [
           {"tenant_id": "tenant-a", "collection_id": "project-alpha"}
         ],
         "database_sources": []
       }
     ],
     "database_sources": {}
   }
   ```

4. Set the path and start the existing application with a single API worker:

   ```powershell
   $env:RAG_API_USERS_FILE = 'C:\RAG-Config\rag-access.json'
   $env:API_WORKERS = '1'
   .\.venv\Scripts\python.exe -B -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

No policy, malformed policy, duplicate keys/user IDs, unknown database grants, or
invalid default scopes fail closed. Startup validates the policy before loading
the model; protected requests cannot bypass a missing/invalid policy.

Keys must be randomly generated credentials, not passwords. Requests use:

```text
Authorization: Bearer <personal-api-key>
```

Do not put keys in URLs, browser storage, `VITE_*` variables, source code, logs,
or connection-string examples. Use HTTPS outside loopback and a reverse proxy
with request-body, concurrency, timeout, and rate limits. The application does
not replace those ingress controls or provide a complete abuse-management system.

The access file is reread for requests, so removing a user/key or changing grants
affects subsequent requests without a restart. Publish file updates atomically
to avoid a partially written policy (which intentionally returns 503).
Changing the configured file path requires a process restart. Never reuse a
deleted user ID for a different person: job and feedback ownership use that ID.

## Roles and project selection

Roles are explicit and do not imply each other:

| Role | Permission |
|---|---|
| `read` | Ask questions and submit/read one's own permitted feedback; inspect one's own permitted ingestion jobs. |
| `ingest` | Upload/replace documents within a listed project; inspect one's own jobs; use individually granted database sources. |
| `admin` | Read aggregate service metrics and, together with `ingest`, operate Google Docs/SharePoint connectors. |

An administrator does not receive wildcard document access. Every operation still
requires an exact listed tenant/project grant. An ingest grant allows replacing
documents throughout that project; this is not document-owner or field-level ACL.
Only grant it to users trusted to publish that project's corpus.

`GET /session` returns only the caller's user ID, roles, and project grants.
It never returns key hashes or other users.

Scope fields in requests are selectors, not authority. `"default"`/missing scope
resolves to the user's only project, or to a configured `default_scope`.
For multiple grants, optionally add:

```json
"default_scope": {"tenant_id": "tenant-a", "collection_id": "project-alpha"}
```

It must be one of the user's grants. Without an unambiguous default, callers
must select a specific permitted tenant and collection (422 otherwise).
Cross-scope access returns 403, including attempts to read before any upload.
There is no implicit tenant-wide/cross-project search.

Legacy rows indexed with `"default"` or unknown scope are not automatically
assigned to new users. Review and reingest approved sources into explicit
projects; do not grant access to the entire historical corpus as a shortcut.

The React UI signs in with a personal key, keeps it in memory only, and selects
from server-listed projects. Logout/401 clears private UI state. The HTTP
Streamlit app also accepts a personal key and project selection. The in-process
`streamlit_demo.py` is a trusted local tool that bypasses API authorization; bind
it to `127.0.0.1` and never expose it as a multi-user production endpoint.
Public `/docs`/`openapi.json` describe the API but do not grant data access.

## Approved database sources only

`POST /ingest-database` no longer executes caller-supplied connections, table names,
or SQL, including for admins. Requests use:

```json
{
  "source_id": "policy-register",
  "tenant_id": "tenant-a",
  "collection_id": "project-alpha",
  "max_rows": 100
}
```

An operator defines the fixed projection in the access file:

```json
"database_sources": {
  "policy-register": {
    "tenant_id": "tenant-a",
    "collection_id": "project-alpha",
    "dsn_env": "POLICY_REGISTER_DSN",
    "query": "SELECT id, title, body FROM approved_policy_view",
    "max_rows": 100
  }
}
```

Add `"policy-register"` to the appropriate user's `database_sources` list.
The user also needs `ingest` and the matching project grant. `dsn_env` names a
server environment variable; it does not contain a connection string. Define
exactly one fixed `table` or `query`. Request row limits can lower, not increase,
the configured source/global cap; source limits are at most 5,000 rows.

Use read-only, least-privilege database roles and safe views. If SQLite is
approved, the operator-selected environment variable must refer only to the
intended file. An API user cannot change that path. Nothing is enabled by an
old `DB_INGESTION_DSN` alone.

Google/SharePoint ingestion is admin-only because it uses server-side retrieval
privileges. SharePoint's app-only Graph token still does not represent the end
user's SharePoint ACL. Operators must approve what they publish into each RAG
project, and approve external-provider processing. `LLM_PROVIDER=auto` may send
context to both configured providers.

## Uploads, jobs, feedback, and cache behavior

- Uploads use unique private temporary files, never paths derived from filenames.
  Copying is bounded by actual bytes; unsupported extensions are rejected.
- A successful queue response is pending, not ready. Clients poll the job until
  completed/failed and display a bounded timeout rather than false success.
- The queue is bounded to 128 pending jobs, with up to 1,000 retained job records
  under normal queue operation. A full queue returns 503 and cleans staged files.
- Job lookup requires the submitting user and current project access. Missing or
  foreign jobs return 404; revoked project access is denied. Queued uploads
  recheck the user's current ingest grant before processing/publication.
- Background errors expose a generic error and job ID, not exception contents.
  Feedback summaries are caller-specific and exclude revoked projects.
- FAISS IDs survive deletion; invalid batches do not partially append.
  Replacement stages FAISS state or uses one PostgreSQL transaction.
- Mirrored writes stage memory state before the persistent write, then publish.
  They are not a distributed crash transaction; PG-primary is recommended.
  FAISS-primary mirrors are process-local and need reconstruction on restart.
- Cache keys include all seven filters, store identity, generation, model,
  candidate limits, and ranking/prompt identity. Scope-dropping retries are gone.
- Persistent/mirrored and remote retrieval paths deliberately bypass
  cross-request answer/retrieval caching until durable shared generations exist.
  This trades cache speed for fresh isolated results across processes.

The API uses an in-process job queue: use one API process. `API_WORKERS=1` is
validated and Compose uses one API worker. Do not override the launch command
with multiple workers; environment settings cannot detect every external
process-manager configuration. Jobs/history are not durable across restarts.
No claim of multi-worker job durability or complete production hardening is made.

## Bounded concurrent questions

The RAG pipeline and HTTP response shape are unchanged. The API no longer holds
its global index lock while waiting for an AI provider. Local vector retrieval
and cache-generation selection share the vector store's short read lock; the
retrieved context is then used outside that lock. Embedding also runs outside
the index lock. Existing storage mutation locks and transactional replacement
remain in place.

An in-flight answer may finish using the document version it already retrieved,
even if that document is replaced during generation. Retrieval after publication
uses the new version; an older answer cannot populate the newer version's cache.
Current user permissions are still checked before returning an answer.
Remote retrieval does not hold the local index lock while making its HTTP call.

| Setting | Default | Meaning |
|---|---|---|
| `MAX_CONCURRENT_ANSWERS` | `4` | Maximum active `/ask` operations in this API process, not a user-account limit. |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `30` | Network timeout used by OpenAI, Hugging Face, and internal service clients. |

Both settings must be positive integers and require a process restart to change.
For local PowerShell, set them before the existing authenticated launch command:

```powershell
$env:MAX_CONCURRENT_ANSWERS = '4'
$env:LLM_REQUEST_TIMEOUT_SECONDS = '30'
```

An occupied answer slot is released on success, failure, or a denied final
permission check. At capacity, `/ask` returns **503** with `Retry-After: 1` and
an explicit capacity message instead of adding an application-level answer queue.
Clients should retry later with bounded backoff, not an immediate retry loop.
Overload rejections are logged and counted as failed requests in the SLO metrics.
The React client shows a safe busy/temporarily-unavailable message, keeps the
user signed in, and does not automatically retry or expose raw server errors.

OpenAI client initialization is synchronized and SDK automatic retries are
disabled so hidden retry cycles do not retain slots. The existing grounded
provider-error fallback remains unchanged. In `auto` mode each admitted question
can call both providers, and the existing executor waits for running calls before
releasing the question slot. Four active questions can therefore mean up to eight
provider calls from this API workload.

These limits are not distributed provider quotas or end-to-end cancellation.
Network timeouts apply to individual network operations, not a strict overall
answer deadline. A timed-out remote inference request may continue in the
inference service. Keep internal services private and use ingress rate/body/
connection limits; authenticated requests still use FastAPI's finite thread pool.
Do not raise concurrency without measuring memory, embedding throughput, database
latency, and provider quotas. Continue using **one API worker** until ingestion
jobs and other process-local state have been externalized.

### Small local load measurement

On 2026-10-15, the in-process ASGI test sent 12 authenticated questions in each
mode across two isolated projects, using real FAISS retrieval, fixed test
embeddings, disabled answer/retrieval caches, and a simulated provider taking
100 ms. All 24 responses passed project-specific answer checks.

| Mode | Peak concurrent generations | Total time | Questions/second | Request p95 |
|---|---|---|---|---|
| Serial reference | 1 | 1.409 s | 8.52 | 0.135 s |
| Concurrent | 4 | 0.453 s | 26.48 | 0.154 s |

This run showed about **3.1x higher throughput**, not a production capacity
rating or an improvement in geographic latency. It excludes real model encoding,
AI-provider latency/quotas, PostgreSQL, network distance, and sustained traffic.
The regression asserts overlap, scope isolation, and the configured concurrency
bound, not a machine-dependent throughput threshold.

Reproduce the measurement without contacting a provider or live database:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests\test_concurrency.py -q -s -k concurrency_load
```

The focused concurrency tests live in `tests\test_concurrency.py`; the existing
security policy fixture is shared through `tests\conftest.py`. No new runtime
dependency, service, queue system, or UI redesign is introduced by this step.

## Split services and containers

Configure a distinct random `RAG_SERVICE_TOKEN` of at least 32 characters in API,
retrieval, and inference processes. Never give this credential to browser users.
Internal `/search` and `/generate` require it; personal keys are not service keys.
Retrieval also requires explicit tenant/project scope and server-bounded limits.
The API attaches the service credential to internal requests.

Keep internal services private and use TLS/network isolation across hosts.
Possession of the service token is a privileged backend trust boundary, not a
replacement end-user identity.

Compose requires `RAG_API_USERS_FILE` and `RAG_SERVICE_TOKEN`; it mounts the external
policy as a secret. Configure approved source DSN environment variables explicitly
in the API service if database ingestion is used.

The Docker context is an allowlist of runtime Python, requirements, and SQL scripts.
Local policies, `.env`, private documents, nested repositories, caches, and UI
build-time secrets must not enter the image. No secrets are baked into the image.

## Validation

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q
Set-Location frontend
npm run build
node --test tests\api.test.cjs
```

Tests use fake keys, isolated temporary policies, model/provider stubs, and local
fixtures. Real PostgreSQL tests are opt-in and may create/drop uniquely named
tables and provision the vector extension **only in an explicitly designated
disposable test database**:

```powershell
# Set RAG_TEST_PGVECTOR_DSN through your local secret mechanism; do not print it.
$env:RAG_ALLOW_DATABASE_TESTS = '1'
.\.venv\Scripts\python.exe -B -m pytest tests\test_pgvector_integration.py -q
```

Do not point the test DSN at an existing application database. If these tests are
skipped, report that limitation rather than treating mocks as real-PG validation.

Deployment still requires user provisioning, HTTPS/ingress controls, approved
provider/data policies, operational monitoring, backup/recovery, and backend
integration validation. No live service is restarted or user credential issued
automatically by this code change.
