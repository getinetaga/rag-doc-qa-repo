
# Intelligent Document QA System (RAG-Based)

## Overview
AI system enabling natural-language queries over PDFs, DOCX, and TXT documents. Uses RAG to retrieve relevant content and generate grounded answers.

## Features
- Multi-document support
- Semantic vector search using FAISS
- LLM-based context-aware responses
- Source citations included
- Modular and scalable architecture

## Tech Stack
- Python, FastAPI, Docker
- Sentence Transformers, FAISS
- OpenAI GPT / LLaMA
- CI/CD: Jenkins

## How to Run
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Testing
```bash
pytest tests/
```

## CI/CD
Automated Docker build and deployment via Jenkinsfile.
