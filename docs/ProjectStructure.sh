rag-doc-qa/
│
├── app/
│   ├── main.py                # FastAPI entry point
│   ├── config.py              # Config & environment variables
│   ├── ingestion.py           # Document loading & parsing
│   ├── chunking.py            # Text chunking logic
│   ├── embeddings.py          # Embedding generation
│   ├── vector_store.py        # Vector DB (FAISS)
│   ├── rag.py                 # Retrieval + generation
│   └── schemas.py             # Request/response models
│
├── requirements.txt
└── README.md
