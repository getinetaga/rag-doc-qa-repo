# DevOps Plan — RAG Document QA System

## 1. Purpose
This document defines the **DevOps plan** for the RAG Document QA System. It covers source control, branching, CI/CD, environments, deployment, infrastructure, monitoring, security, backup, and operational support.

The goal is to ensure the application is:
- reliable,
- repeatable to build and deploy,
- easy to monitor,
- secure in handling secrets and services,
- maintainable across development and production environments.

---

## 2. Application Summary
The application is a Python-based **Retrieval-Augmented Generation (RAG)** system with:

- **FastAPI** backend — ingestion (`/upload`, `/upload-google-doc`, `/upload-sharepoint`, `/ingest-database`), querying (`/ask`, `/question-domains`), async-job status (`/ingestion-jobs/{id}`), and observability (`/metrics`, `/feedback`, `/feedback/summary`)
- **Streamlit** interfaces (API-backed `streamlit_app.py`, in-process `app/streamlit_demo.py`, metrics dashboard `app/metrics_dashboard.py`)
- **Sentence Transformers** for embeddings
- **FAISS**, **PostgreSQL + pgvector**, or **hybrid** for vector search
- **OpenAI**, **Hugging Face**, or **auto** for answer generation
- an optional **service split** (`app.retrieval_service` :8001, `app.inference_service` :8002) over a shared persistent index
- an in-process **async ingestion queue** for large uploads
- **Docker** / **Docker Compose** containerization support
- **Jenkins** CI pipeline support

### External integrations that need credentials
- **Microsoft Graph** (SharePoint ingestion) — `SHAREPOINT_TENANT_ID` / `SHAREPOINT_CLIENT_ID` / `SHAREPOINT_CLIENT_SECRET` (Entra ID app, `Sites.Read.All` + `Files.Read.All`).
- **SQL databases** (`/ingest-database`) — a read-only DSN, per request or via `DB_INGESTION_DSN`. PostgreSQL and SQLite only.

---

## 3. DevOps Objectives
The DevOps objectives are to:

1. automate build, test, and deployment steps,
2. ensure reproducible environments,
3. provide reliable PostgreSQL + pgvector support,
4. enable fast rollback and recovery,
5. improve visibility through logging and monitoring,
6. protect secrets and service credentials,
7. support future scaling and production readiness.

---

## 4. Source Control Strategy

### Repository
- **GitHub** repository hosts the source code.
- Main application code, tests, Docker config, and CI pipeline definitions are version-controlled.

### Branching Model
Recommended branch strategy:

| Branch | Purpose |
|---|---|
| `main` | Stable production-ready code |
| `develop` | Integration branch for upcoming release |
| `feature/*` | New features or enhancements |
| `bugfix/*` | Defect fixes |
| `hotfix/*` | Urgent production fixes |
| `rag` | Active development/testing branch (current usage) |

### Commit Practices
- Use small, meaningful commits.
- Commit messages should describe the change clearly.

Examples:
- `Add pgvector environment support`
- `Improve answer clarity and deduplicate references`

---

## 5. Environment Strategy

### 5.1 Development
Used by developers locally for feature work and testing.

**Characteristics:**
- local `.env` file
- local PostgreSQL or FAISS backend
- debug logging allowed
- auto-reload enabled

### 5.2 Test / QA
Used for system verification before release.

**Characteristics:**
- isolated database instance
- stable sample test data
- CI-triggered tests
- no production secrets

### 5.3 Staging
Production-like environment for validation.

**Characteristics:**
- containerized deployment
- PostgreSQL + pgvector configured
- near-production settings
- integration with monitoring and alerts

### 5.4 Production
End-user environment.

**Characteristics:**
- secured secrets management
- monitored application and database
- automated deployment or controlled approval flow
- backups and rollback plan

---

## 6. Configuration Management
All runtime configuration should be externalized via environment variables.

### Core Variables
```env
OPENAI_API_KEY=
HUGGINGFACE_API_KEY=
LLM_PROVIDER=openai                 # openai | huggingface | auto
OPENAI_LLM_MODEL=gpt-4o-mini        # LLM_MODEL still accepted as an alias
HUGGINGFACE_LLM_MODEL=google/flan-t5-base
VECTOR_DB_BACKEND=pgvector          # faiss | pgvector | hybrid (auto-pgvector when PGVECTOR_DSN is set)
PGVECTOR_DSN=postgresql://postgres:<password>@localhost:5432/ragdb
PGVECTOR_TABLE_NAME=rag_embeddings
PGVECTOR_PRIMARY_SEARCH=pgvector
```

### Scaling / topology
```env
API_WORKERS=1                       # uvicorn worker count in the container
RETRIEVAL_SERVICE_URL=              # set to route retrieval to app.retrieval_service
INFERENCE_SERVICE_URL=              # set to route generation to app.inference_service
ASYNC_INGESTION_MIN_BYTES=200000    # uploads at/above this size go to the background queue (0 = always)
MAX_UPLOAD_FILE_SIZE_BYTES=209715200
```

> With `VECTOR_DB_BACKEND=faiss`, the index lives in each worker's memory — an upload on one worker is invisible to `/ask` on another. Run a single worker, or use `pgvector` / `hybrid` (and the service split) for multi-worker deployments.

### SharePoint ingestion
```env
SHAREPOINT_TENANT_ID=
SHAREPOINT_CLIENT_ID=
SHAREPOINT_CLIENT_SECRET=
GRAPH_BASE_URL=https://graph.microsoft.com/v1.0     # override for sovereign clouds
GRAPH_AUTHORITY=https://login.microsoftonline.com
```

### Database ingestion
```env
DB_INGESTION_DSN=                   # optional default DSN; postgresql:// or sqlite:/// only
DB_INGESTION_MAX_ROWS=5000
DB_INGESTION_MAX_CELL_CHARS=2000
DB_INGESTION_STATEMENT_TIMEOUT_MS=15000
```

### Observability / SLO targets
```env
SLO_SERVICE_NAME=rag-doc-qa
SLO_AVAILABILITY_TARGET=0.99            # min success rate
SLO_LATENCY_P95_TARGET_SECONDS=3.0      # max p95 request latency
SLO_LATENCY_P99_TARGET_SECONDS=8.0      # max p99 request latency
SLO_RETRIEVAL_QUALITY_TARGET=0.6        # min mean retrieval-hit quality
```

### Best Practices
- never commit real secrets,
- use `.env` only for local development,
- use Jenkins credentials / secret managers for CI and production,
- validate environment variables during startup,
- do not blank a variable in `.env` (`FOO=`) — an empty string counts as "set" and shadows the built-in default.

---

## 7. Build and Packaging Strategy

### Python Environment
- Create a virtual environment (`.venv`)
- Install dependencies from `requirements.txt`

### Containerization
The repository includes a `Dockerfile` (single image, `uvicorn app.main:app` with `--workers ${API_WORKERS}`, default `1`) and a `docker-compose.yml` that runs three containers from that image: `api` (:8000), `retrieval` (:8001), and `inference` (:8002), wired together with `RETRIEVAL_SERVICE_URL` / `INFERENCE_SERVICE_URL`.

Current build flow:
```bash
docker build -t rag-doc-qa:latest .
docker compose up          # 3-service split; expects a reachable pgvector DSN
```

### Recommended Improvements
- add a `.dockerignore` (exclude `.venv`, `__pycache__`, `.git`, caches),
- pin dependency versions where necessary,
- add a non-root container user,
- separate dev and production requirements,
- reduce image size with multi-stage builds if needed.

---

## 8. CI Plan
The application already contains a `Jenkinsfile` for CI.

### CI Pipeline Stages (`Jenkinsfile`)
1. **Setup** — create the virtualenv, upgrade pip, install `requirements.txt`
2. **Lint & Test** — currently runs `pytest` only (the stage name is aspirational; `black` / `isort` / `flake8` / `mypy` are available in `requirements-dev.txt` but not yet wired in)
3. **Build Docker Image** — on Unix agents, or Windows with `DOCKER_ON_WINDOWS=true`
4. **Deploy (Optional)** — placeholder

### Validation Commands
```bash
python -m pytest -q            # 76 tests across 7 files
# aspirational gate, once wired into CI:
black --check . && isort --check-only . && flake8 && mypy app
```

### CI Success Criteria
- all tests pass,
- build completes successfully,
- no critical lint/test failures,
- container image builds without errors.

---

## 9. CD / Deployment Plan

### Deployment Targets

Possible deployment modes:
- local Docker host
- VM-based deployment
- on-prem server
- cloud container platform

### Recommended Deployment Flow
1. Merge approved code into release branch
2. Trigger CI pipeline
3. Run automated tests
4. Build Docker image
5. Deploy to staging
6. Validate staging behavior
7. Promote to production after approval

### Deployment Command Example
```bash
docker run -d -p 8000:8000 --env-file .env rag-doc-qa:latest
```

### Streamlit Deployment
If Streamlit is deployed separately:
```bash
streamlit run streamlit_app.py --server.port 8501
```

---

## 10. Database Operations Plan

### Database Technology
- PostgreSQL
- `pgvector` extension enabled

### Database Responsibilities
- store embeddings and chunk text
- support vector similarity search
- persist retrieval content across sessions

### Initialization
Use:
```bash
psql "$PGVECTOR_DSN" -f scripts/create_pgvector_table.sql
```

### Database Maintenance Tasks
- monitor table growth,
- vacuum/analyze periodically,
- verify indexes remain healthy,
- back up `ragdb` regularly,
- confirm port usage is consistent (`5432`). Posiible ports?


### Backup Strategy
- daily logical backup using `pg_dump`
- weekly restore validation
- retain backups based on retention policy

Example:
```bash
pg_dump -U postgres -d ragdb > ragdb_backup.sql
```

---

## 11. Monitoring and Observability

### Application Monitoring
The app already exposes runtime signals:
- `GET /metrics` — a structured SLO report from `app/slo_metrics.py` (in-memory, per process): a p50/p90/p95/p99 latency distribution, availability (success/error rates), throughput, retrieval-hit quality, and an `slo` block scoring each against a target (`SLO_AVAILABILITY_TARGET`, `SLO_LATENCY_P95_TARGET_SECONDS`, `SLO_LATENCY_P99_TARGET_SECONDS`, `SLO_RETRIEVAL_QUALITY_TARGET`) with attainment, an error-budget figure, and an overall `healthy` / `at_risk` / `breached` status
- `GET /feedback/summary` — thumbs up/down counts and recent corrections (from `app/feedback_store.py`)
- `GET /ingestion-jobs/{job_id}` — status of a queued large-upload job

Also monitor: API uptime, response times, ingestion errors by source, provider failures, and database connectivity.

### Key Health Checks
- `GET /docs` (no dedicated `/health` yet) and `GET /metrics`
- Streamlit UI availability
- PostgreSQL connectivity (for `pgvector` / `hybrid` and for database ingestion)
- Microsoft Graph token acquisition (SharePoint ingestion)

### Logging Requirements
Log:
- request status codes
- document upload events
- retrieval failures
- LLM provider failures
- database connection issues

### Recommended Future Tooling
- Prometheus + Grafana
- ELK / OpenSearch stack
- cloud logging platform
- uptime checks and alerting

---

## 12. Security Plan

### Secrets Management
- never commit API keys,
- use secret storage in CI/CD,
- rotate credentials regularly.

### Access Control
- restrict production DB access,
- separate read/write roles where possible,
- secure admin tools such as pgAdmin.

### Network Security
- expose only required ports,
- avoid public DB exposure,
- use firewall rules or security groups.

### Secure Coding Practices
- validate file uploads,
- sanitize configuration,
- avoid leaking stack traces in UI,
- avoid logging secrets.

---

## 13. Reliability and Recovery

### Failure Scenarios
- invalid LLM API key / quota exceeded
- PostgreSQL unavailable or wrong DB port
- Docker not running
- corrupted upload or unsupported document type
- SharePoint: expired/incorrect `SHAREPOINT_*` credentials, or the app lacks read access to the site
- database ingestion: unreachable DSN, a non-`SELECT` query (rejected), or a query returning no rows
- multi-worker + `faiss` backend: `/ask` hits a worker with no index ("No document uploaded yet.")

### Recovery Plan
| Failure | Recovery Action |
|---|---|
| API key invalid | update environment secret and restart app |
| DB connection failure | verify service, DSN, port, credentials |
| repeated/stale answers | clear vector data and re-upload document |
| deployment failure | rollback to last successful image/commit |
| container crash | restart service and inspect logs |

### Rollback Strategy
- keep previous working Docker image tags,
- keep previous git release tags/commits,
- use Jenkins rollback stage if production deploy fails.

---

## 14. Operational Runbook

### Start Services
```bash
uvicorn app.main:app --reload
streamlit run streamlit_app.py
```

### Verify Health
```bash
curl http://127.0.0.1:8000/docs
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:8501
```

### Verify Database Rows
```sql
SELECT COUNT(*) FROM rag_embeddings;
```

### Troubleshooting Checklist
1. confirm `.env` values
2. verify PostgreSQL is running on the correct port
3. confirm `ragdb` exists
4. verify `pgvector` extension is installed
5. run tests
6. inspect logs for LLM or DB failures

---

## 15. Quality Gates
Before deployment, the following must pass:

- unit/integration tests
- API verification
- UI verification
- database connection verification
- no critical defects
- secrets not exposed in commits

Recommended gate:
```bash
python -m pytest -q
```

---

## 16. Future DevOps Improvements
Recommended enhancements:
- add a dedicated `/health` endpoint (distinct from `/metrics`),
- wire `black` / `isort` / `flake8` / `mypy` into the Jenkins "Lint & Test" stage and add pre-commit hooks,
- ship a `pyproject.toml` so the formatters/linters share one config,
- add a `.dockerignore` and pin the image to a released tag,
- publish the image to a registry and add a smoke-test stage,
- export `/metrics` to Prometheus/Grafana instead of in-process only,
- persist `feedback_store` / `ingestion_jobs` state (currently in-memory) if durability matters,
- pool PostgreSQL connections for the pgvector backend and retrieval service,
- separate staging and production secrets; rotate the SharePoint client secret on a schedule.

---

## 17. Roles and Responsibilities
| Role | Responsibility |
|---|---|
| Developer | code changes, local testing, PR creation |
| QA | validate functionality and regression behavior |
| DevOps Engineer | CI/CD, infra, secrets, monitoring, deployments |
| DBA / Support | PostgreSQL health, backup, restore |
| Product Owner | release approval and acceptance |

---

## 18. Release Readiness Checklist
A release is ready when:
- code is merged and reviewed,
- tests pass,
- Docker image builds successfully,
- database is reachable,
- environment variables are correct,
- rollback plan exists,
- monitoring is active,
- staging sign-off is complete.

---

## 19. Summary
This DevOps plan provides a practical operating model for the RAG Document QA System by defining:
- how code is built,
- how it is tested,
- how it is deployed,
- how PostgreSQL + pgvector is managed,
- how failures are handled,
- and how the system can evolve toward a more production-ready setup.

It supports a reliable, traceable, and maintainable delivery lifecycle for the application.
