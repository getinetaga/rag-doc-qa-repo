# Intelligent Document Question Answering System (RAG-Based)

## Overview
An AI-powered system that enables users to upload documents and ask natural-language questions. The system uses Retrieval-Augmented Generation (RAG) to retrieve relevant content and generate accurate, grounded answers.

## Features
- PDF, DOCX, and TXT document support
- Semantic search using vector embeddings
- Context-aware LLM responses
- Source-grounded answers
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

## How to Run
```bash
uvicorn app.main:app --reload
