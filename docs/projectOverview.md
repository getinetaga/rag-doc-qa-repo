# Intelligent Document Question Answering System (RAG-Based)

## Overview
An AI-powered system that enables users to upload documents and ask natural-language questions. The system uses Retrieval-Augmented Generation (RAG) to retrieve relevant content and generate accurate, grounded answers.

## Features
- PDF, DOCX, and TXT document support
- Semantic search using vector embeddings
- Context-aware LLM responses
- Source-grounded answers
- Callback-based Streamlit event handlers for upload, submit, and clear actions
- Scalable backend architecture

## Tech Stack
- Python, FastAPI
- FAISS Vector Database
- Sentence Transformers
- OpenAI / LLM APIs
- Docker

## Use Cases
- Enterprise knowledge search
- Legal document analysis
- HR policy Q&A
- Customer support automation

## Architecture
See system architecture diagram in `/docs`

## Frontend Event Handlers
- `on_change` resets document and chat state when the selected file changes.
- Process handlers send the selected file to the FastAPI `/upload` endpoint.
- Form submit handlers send questions to `/ask` and support Enter-to-submit behavior.
- Clear handlers remove prior question history without restarting the app.

These handlers reduce stale UI state during Streamlit reruns and keep the browser workflow aligned with the backend's current indexed document.

## How to Run
```bash
uvicorn app.main:app --reload
streamlit run streamlit_app.py
```
