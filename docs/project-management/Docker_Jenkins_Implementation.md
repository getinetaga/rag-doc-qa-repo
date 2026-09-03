# Docker Container and Jenkins Implementation — RAG Document QA System

## 1. Purpose
This document provides a **detailed and professional implementation guide** for using **Docker** and **Jenkins** with the RAG Document QA System.

It explains how containerization and CI/CD automation support this application in development, testing, staging, and production.

The document is specific to this project’s architecture, which includes:
- FastAPI backend with multi-source ingestion (uploads, Google Docs, SharePoint, SQL rows)
- Streamlit front ends (API-backed, in-process, metrics dashboard)
- Sentence Transformer embeddings
- FAISS / pgvector / hybrid vector backends
- OpenAI / Hugging Face / `auto` integration
- an optional retrieval + inference service split, wired by `docker-compose.yml`

---

## 2. Objectives
The Docker and Jenkins implementation should achieve the following:

1. package the application in a repeatable runtime environment,
2. simplify setup and deployment across machines,
3. automate testing and build validation,
4. reduce configuration inconsistencies,
5. support reliable staging and production release workflows,
6. integrate well with the PostgreSQL + pgvector backend.

---

## 3. Application Context
This application is a Python-based **RAG document QA solution**. All services run from the same image.

| Service | Module | Port | Role |
|---|---|---|---|
| API | `app.main` | 8000 | Ingestion, ask, and observability endpoints |
| Retrieval (optional) | `app.retrieval_service` | 8001 | Embedding + vector search + rerank over a shared index |
| Inference (optional) | `app.inference_service` | 8002 | LLM provider calls |
| Streamlit | `streamlit_app.py` | 8501 | API-backed web interface |

The retrieval and inference services are used only when `RETRIEVAL_SERVICE_URL` / `INFERENCE_SERVICE_URL` are set; `docker-compose.yml` starts all three and wires them together.

Supporting services and integrations:
- PostgreSQL with `pgvector` (persistent / hybrid vector backend, and a `/ingest-database` source)
- optional external LLM provider (OpenAI / Hugging Face)
- Microsoft Graph (SharePoint ingestion) — needs `SHAREPOINT_*` credentials

Because the application depends on Python libraries, environment variables, and database connectivity, **Docker** and **Jenkins** are suitable for ensuring repeatable builds and automated delivery.

---

## 4. Docker Implementation Plan

## 4.1 Purpose of Docker in This Application
Docker is used to:
- standardize the runtime environment,
- eliminate “works on my machine” issues,
- simplify deployment to servers or cloud hosts,
- package the FastAPI service as a portable container image.

---

## 4.2 Current Dockerfile
The current project includes a basic Dockerfile:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV API_WORKERS=1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS}"]
```

### What it does
- uses a slim Python 3.11 base image,
- copies the application into `/app`,
- installs dependencies,
- starts the FastAPI app with `uvicorn`, worker count controlled by `API_WORKERS` (default `1`).

`docker-compose.yml` reuses this image three times, overriding the command to run `app.retrieval_service` and `app.inference_service` alongside `app.main`.

---

## 4.3 Docker Build Process
### Build Command
```bash
docker build -t rag-doc-qa:latest .
```

### Expected Outcome
- a working container image named `rag-doc-qa:latest`
- the API becomes runnable in any Docker-enabled environment

---

## 4.4 Docker Run Configuration
### Example Command
```bash
docker run -d -p 8000:8000 --env-file .env rag-doc-qa:latest
```

### Runtime Requirements
The container needs access to:
- `.env` configuration values,
- PostgreSQL instance on the correct host/port,
- network access to OpenAI or Hugging Face if those providers are used.

---

## 4.5 Environment Variables for Container Runtime
Required runtime variables:

```env
OPENAI_API_KEY=
HUGGINGFACE_API_KEY=
LLM_PROVIDER=openai                 # openai | huggingface | auto
OPENAI_LLM_MODEL=gpt-4o-mini
HUGGINGFACE_LLM_MODEL=google/flan-t5-base
VECTOR_DB_BACKEND=pgvector          # faiss | pgvector | hybrid
PGVECTOR_DSN=postgresql://postgres:<password>@localhost:5432/ragdb
PGVECTOR_TABLE_NAME=rag_embeddings
PGVECTOR_PRIMARY_SEARCH=pgvector
API_WORKERS=1
```

Optional, per feature:

```env
# Service split
RETRIEVAL_SERVICE_URL=http://retrieval:8001
INFERENCE_SERVICE_URL=http://inference:8002

# SharePoint ingestion
SHAREPOINT_TENANT_ID=
SHAREPOINT_CLIENT_ID=
SHAREPOINT_CLIENT_SECRET=

# Database ingestion (postgresql:// or sqlite:/// only)
DB_INGESTION_DSN=
DB_INGESTION_MAX_ROWS=5000
```

### Best Practice
- do not bake secrets into the image,
- inject secrets at runtime (compose `environment:` / Jenkins credentials),
- use separate env files for development, staging, and production,
- with `VECTOR_DB_BACKEND=faiss`, keep `API_WORKERS=1` — each worker holds its own in-memory index.

---

## 4.6 Docker Networking Considerations
If the container uses PostgreSQL on the host machine:
- the DSN may need to reference the host differently than `localhost`, depending on the container environment.

Examples:
- `host.docker.internal` on Windows/macOS Docker Desktop
- service name in Docker Compose or Kubernetes

Example:
```env
PGVECTOR_DSN=postgresql://postgres:<password>@host.docker.internal:5432/ragdb
```

---

## 4.7 Recommended Docker Enhancements
To improve production readiness, the Docker setup should be enhanced with:

1. a `.dockerignore` file,
2. a non-root runtime user,
3. multi-stage build optimization,
4. health checks,
5. separate image tags for each release.

### Example Enhancements
- exclude `.venv`, `__pycache__`, `.git`, test caches
- add:
```dockerfile
HEALTHCHECK CMD curl --fail http://localhost:8000/docs || exit 1
```

---

## 4.8 Streamlit Container Option
If desired, the Streamlit app can be containerized separately.

### Example Command
```bash
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

### Recommendation
For production, consider:
- one container for FastAPI,
- one container for Streamlit,
- one managed PostgreSQL / pgvector service.

---

## 5. Jenkins Implementation Plan

## 5.1 Purpose of Jenkins in This Application
Jenkins is used to automate:
- environment setup,
- dependency installation,
- testing,
- Docker image creation,
- optional deployment steps.

This ensures code is validated consistently whenever changes are made.

---

## 5.2 Current Jenkinsfile Overview
The application already contains a declarative `Jenkinsfile`.

### Current Pipeline Stages
1. **Setup**
2. **Lint & Test**
3. **Build Docker Image**
4. **Deploy (Optional)**

This pipeline supports both Unix and Windows Jenkins agents.

---

## 5.3 Jenkins Setup Stage
### Purpose
Prepare the Python environment.

### Current Actions
- create a virtual environment,
- upgrade `pip`,
- install dependencies from `requirements.txt`.

### Benefit
Provides a clean, reproducible environment on each pipeline run.

---

## 5.4 Jenkins Test Stage
### Purpose
Verify application correctness before deployment.

### Current Validation
```bash
python -m pytest tests/ --maxfail=1 --disable-warnings
```

### Project-Specific Importance
This project depends heavily on regression safety because the current behavior set includes:
- section references and answer deduplication,
- FAISS / pgvector / hybrid backends,
- lexical reranking plus relevance and grounding gates,
- response / retrieval caching,
- Google Docs, SharePoint (Microsoft Graph), and read-only SQL-row ingestion,
- provider fallback and `auto` mode.

Running the 76-test suite in Jenkins ensures those behaviors stay stable.

---

## 5.5 Jenkins Docker Build Stage
### Purpose
Convert validated application code into a deployable container image.

### Current Action
```bash
docker build -t rag-doc-qa:latest .
```

### Benefit
Ensures only tested code is packaged for deployment.

---

## 5.6 Optional Deployment Stage
### Purpose
Provide a place for real deployment commands.

### Current State
The stage is currently a placeholder.

### Recommended Future Actions
- push the Docker image to a registry,
- deploy to a VM/container host,
- deploy to staging first,
- require manual approval before production.

---

## 6. Recommended Jenkins Pipeline for This Application
A mature pipeline for this app should include:

1. **Checkout Code**
2. **Environment Setup**
3. **Dependency Install**
4. **Static Checks / Lint (future)**
5. **Run Tests**
6. **Build Docker Image**
7. **Publish Docker Image**
8. **Deploy to Staging**
9. **Smoke Test**
10. **Manual Approval**
11. **Deploy to Production**

---

## 7. CI/CD Implementation Workflow

### Step 1 — Developer Pushes Code
Code is pushed to GitHub on a working branch such as `rag`, `feature/*`, or `main`.

### Step 2 — Jenkins Trigger
Jenkins job starts automatically or manually.

### Step 3 — Build and Test
Jenkins:
- creates the environment,
- installs dependencies,
- runs `pytest`,
- confirms no blocking failure exists.

### Step 4 — Container Build
If tests pass, Jenkins builds the Docker image.

### Step 5 — Deploy or Promote
If deployment is enabled, Jenkins deploys the approved image to the target environment.

---

## 8. Integration with PostgreSQL + pgvector
Docker and Jenkins must support the database-dependent nature of the app.

### Requirements
- PostgreSQL service must be reachable,
- `pgvector` must be installed,
- `ragdb` must exist,
- environment variables must point to the correct host and port.

### Jenkins Validation Suggestion
Future CI/CD enhancement:
- run a DB connectivity check during staging deploy,
- optionally run:

```bash
psql "$PGVECTOR_DSN" -c "SELECT COUNT(*) FROM rag_embeddings;"
```

---

## 9. Secrets and Credential Management

### Required Secrets
- `OPENAI_API_KEY`
- `HUGGINGFACE_API_KEY`
- PostgreSQL username/password

### Best Practices
- store credentials in Jenkins Credentials Store,
- inject them as environment variables at runtime,
- never hard-code them in `Dockerfile`, `Jenkinsfile`, or source files,
- rotate secrets when needed.

---

## 10. Logging and Monitoring for Docker/Jenkins

### Docker Runtime Monitoring
Monitor:
- container status,
- restart count,
- API health,
- memory/CPU usage,
- DB connection issues.

### Jenkins Monitoring
Monitor:
- pipeline success/failure trend,
- test pass rate,
- build duration,
- deployment frequency,
- rollback frequency.

---

## 11. Operational Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Docker daemon unavailable | build/deploy blocked | verify Docker service on build host |
| wrong DB hostname in container | app cannot connect to pgvector | use env-based DSN and validate host |
| missing secrets in Jenkins | LLM/API failure | use managed credentials |
| untested code deployed | regression in production | enforce CI quality gate |
| large image size | slow build/deploy | optimize Dockerfile and dependencies |
| no rollback path | extended outage | keep versioned image tags |

---

## 12. Recommended Best Practices for This Project

### Docker Best Practices
- use `.dockerignore`
- pin runtime dependencies
- avoid root user in production
- inject secrets externally
- tag images clearly (`rag-doc-qa:v1.0.0`)

### Jenkins Best Practices
- fail fast on test errors
- keep build logs concise and timestamped
- separate build and deploy jobs if needed
- require approval before production release
- archive test results and artifacts

---

## 13. Example Deployment Architecture

### Minimal Deployment
- 1 FastAPI container
- 1 Streamlit process or container
- 1 PostgreSQL + pgvector database

### Recommended Flow
```text
Developer Push -> Jenkins CI -> Pytest -> Docker Build -> Staging Deploy -> Validation -> Production Deploy
```

---

## 14. Future Enhancements
Recommended next steps:
- add a `.dockerignore` and a multi-stage / non-root image,
- add image publishing to Docker Hub or GHCR with released tags,
- add a Jenkins stage for lint (`black`/`isort`/`flake8`/`mypy`) and one for smoke tests,
- add container `HEALTHCHECK` directives,
- add automatic rollback support,
- add a managed PostgreSQL service to the compose file for a true local full stack,
- containerize the Streamlit UI as its own service.

> Docker Compose already exists (`docker-compose.yml`) for the api / retrieval / inference split; it currently expects an external reachable pgvector DSN.

---

## 15. Summary
The Docker and Jenkins implementation for this application provides the foundation for a professional DevOps workflow.

### Docker provides:
- packaging,
- portability,
- consistent runtime behavior.

### Jenkins provides:
- automated testing,
- build validation,
- repeatable release preparation.

Together, they support a reliable delivery model for the RAG Document QA System and prepare it for more robust staging and production deployment in the future.
