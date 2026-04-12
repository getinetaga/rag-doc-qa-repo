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

- **FastAPI** backend for `/upload` and `/ask`
- **Streamlit** web interface
- **Sentence Transformers** for embeddings
- **FAISS** or **PostgreSQL + pgvector** for vector search
- **OpenAI** or **Hugging Face** for answer generation
- **Docker** containerization support
- **Jenkins** CI pipeline support

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

### Required Variables
```env
OPENAI_API_KEY=
HUGGINGFACE_API_KEY=
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
VECTOR_DB_BACKEND=pgvector
PGVECTOR_DSN=postgresql://postgres:<password>@localhost:5432/ragdb
PGVECTOR_TABLE_NAME=rag_embeddings
PGVECTOR_PRIMARY_SEARCH=pgvector
```

### Best Practices
- never commit real secrets,
- use `.env` only for local development,
- use Jenkins credentials / secret managers for CI and production,
- validate environment variables during startup.

---

## 7. Build and Packaging Strategy

### Python Environment
- Create a virtual environment (`.venv`)
- Install dependencies from `requirements.txt`

### Containerization
The repository already includes a `Dockerfile`.

Current build flow:
```bash
docker build -t rag-doc-qa:latest .
```

### Recommended Improvements
- pin dependency versions where necessary,
- add a non-root container user,
- separate dev and production requirements,
- reduce image size with multi-stage builds if needed.

---

## 8. CI Plan
The application already contains a `Jenkinsfile` for CI.

### CI Pipeline Stages
1. **Checkout Source**
2. **Create Virtual Environment**
3. **Install Dependencies**
4. **Run Tests**
5. **Build Docker Image**
6. **Publish Artifacts (optional)**
7. **Deploy to target environment (optional/manual approval)**

### Validation Commands
```bash
python -m pytest -q
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
- confirm port usage is consistent (`5432`).

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
Monitor:
- API uptime
- response times
- upload errors
- answer generation failures
- database connectivity

### Key Health Checks
- `GET /docs` or a dedicated `/health` endpoint
- Streamlit UI availability
- PostgreSQL connectivity

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
- invalid LLM API key
- quota exceeded
- PostgreSQL unavailable
- wrong DB port selected
- Docker not running
- corrupted upload or unsupported document

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
- add a dedicated `/health` endpoint,
- add linting and formatting checks in CI,
- add pre-commit hooks,
- automate database migrations,
- deploy via Docker Compose or Kubernetes,
- add centralized monitoring and alerting,
- add artifact versioning and image tags,
- separate staging and production secrets.

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
