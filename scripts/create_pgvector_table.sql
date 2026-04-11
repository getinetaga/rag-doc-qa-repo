--Enable the pgvector extension for vector support in 
--PostgreSQL
CREATE EXTENSION IF NOT EXISTS vector;
--VERIFY THAT THE pgvector EXTENSION IS INSTALLED
 SELECT * FROM pg_extension WHERE extname = 'vector';

 -- CREATE THE rag_embeddings TABLE TO STORE TEXT,EMBEDDINGS, AND METADATA
CREATE TABLE IF NOT EXISTS rag_embeddings (
    id BIGSERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    embedding vector(384) NOT NULL,-- 384-dimensional vector for the local all-MiniLM-L6-v2 model
    source_document TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,--OPTIONAL context or additional information about the embedding
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()-- Timestamp for when the embedding row was created
);
--Add a vector index on the embedding column for efficient similarity search
CREATE INDEX IF NOT EXISTS rag_embeddings_embedding_hnsw_idx
    ON rag_embeddings USING hnsw (embedding vector_l2_ops);

CREATE INDEX IF NOT EXISTS rag_embeddings_source_document_idx
    ON rag_embeddings (source_document);
