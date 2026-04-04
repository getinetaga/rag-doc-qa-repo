CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_embeddings (
    id BIGSERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    source_document TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS rag_embeddings_embedding_hnsw_idx
    ON rag_embeddings USING hnsw (embedding vector_l2_ops);

CREATE INDEX IF NOT EXISTS rag_embeddings_source_document_idx
    ON rag_embeddings (source_document);
