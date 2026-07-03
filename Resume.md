# [Your Full Name]
[City, Country] | [Phone Number] | [Email Address] | [LinkedIn URL] | [GitHub URL]

## Professional Summary
AI/ML-focused software engineer with hands-on experience building and production-hardening a Retrieval-Augmented Generation (RAG) document Q&A platform using FastAPI, Streamlit, vector search, and modern DevOps workflows. Strong background in backend API design, scalable retrieval/inference architecture, automated testing, and observability. Proven ability to turn roadmap goals into shipped features with measurable reliability and quality outcomes.

## Technical Skills
- Programming: Python, SQL, Bash, PowerShell
- Backend and APIs: FastAPI, Uvicorn, Pydantic
- AI and RAG: Embeddings, vector search (FAISS/pgvector), reranking, prompt orchestration
- Data and Storage: PostgreSQL/pgvector, metadata filtering, JSONB handling
- Frontend: Streamlit
- DevOps and Infrastructure: Docker, Docker Compose, Jenkins, CI pipelines
- Testing and Quality: Pytest, API tests, pipeline tests, configuration/unit tests
- Monitoring and Reliability: SLO metrics (p95 latency, error rate, throughput, retrieval quality), feedback loops

## Project Experience
### RAG Document Q&A Platform | AI Engineering Project
[GitHub Repository URL]

- Designed and implemented an end-to-end RAG pipeline for document ingestion, chunking, embedding, vector indexing, retrieval, and answer generation.
- Built robust FastAPI endpoints for document upload, question answering, ingestion job tracking, metrics reporting, and user feedback capture.
- Added asynchronous ingestion jobs using a task queue pattern to prevent API blocking and improve responsiveness under larger uploads.
- Implemented response caching and retrieval-aware cache keys to reduce duplicate computation and improve repeated-query latency.
- Introduced retrieval reranking and advanced retrieval filters (date, author, tags, source metadata) to improve answer grounding and context relevance.
- Extended platform to support multi-document collections and folder/project-level knowledge scopes.
- Separated retrieval and inference into independently deployable services, enabling clearer scaling boundaries and workload isolation.
- Integrated operational observability with SLO-focused metrics for p95 latency, error rate, throughput, and retrieval hit quality.
- Built a human feedback loop (thumbs up/down and correction capture) to support iterative quality improvement.
- Resolved production issues including upload failures due to metadata serialization mismatches and improved API stability with safer data handling.
- Maintained strong test coverage across API, RAG pipeline, ingestion, vector store, and configuration components; validated changes with full passing test suite (43 tests).

## Selected Achievements
- Shipped multiple roadmap features from concept to tested implementation in a live codebase.
- Improved platform readiness for concurrent usage with worker-based scaling and service decomposition.
- Increased retrieval precision and answer quality through reranking, scoped collections, and metadata filters.
- Strengthened maintainability through modular service design, clear schemas, and comprehensive tests.

## Education
[Degree Title], [Major]  
[University Name], [Graduation Year]

## Certifications (Optional)
- [Relevant Certification, e.g., AWS Cloud Practitioner]
- [Relevant Certification, e.g., Machine Learning Specialization]

## Additional Information
- Open to roles in AI Engineering, Machine Learning Engineering, Backend Engineering, and Platform Engineering.
- Portfolio available with architecture diagrams, technical documentation, and test strategy artifacts.
