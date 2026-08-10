ALTER TABLE pcm_projects
ADD COLUMN IF NOT EXISTS active_index_generation UUID;

CREATE TABLE IF NOT EXISTS pcm_index_generations (
    generation_id UUID PRIMARY KEY,
    project_id TEXT NOT NULL,
    embedding_model_id TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    chunker_version TEXT NOT NULL,
    indexed_pcm_revision BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('building', 'active', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    activated_at TIMESTAMPTZ,
    UNIQUE (project_id, embedding_model_id, chunker_version)
);

CREATE TABLE IF NOT EXISTS pcm_knowledge_chunks (
    chunk_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    knowledge_id TEXT NOT NULL,
    knowledge_revision BIGINT NOT NULL,
    heading_path JSONB NOT NULL DEFAULT '[]'::jsonb,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    valid_from_pcm_revision BIGINT NOT NULL,
    valid_until_pcm_revision BIGINT,
    search_vector TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', content)
    ) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (project_id, knowledge_id, knowledge_revision)
        REFERENCES pcm_knowledge_revisions(project_id, knowledge_id, knowledge_revision)
);

CREATE INDEX IF NOT EXISTS pcm_chunks_snapshot_idx
ON pcm_knowledge_chunks (
    project_id,
    valid_from_pcm_revision,
    valid_until_pcm_revision
);

CREATE INDEX IF NOT EXISTS pcm_chunks_search_vector_idx
ON pcm_knowledge_chunks USING gin (search_vector);

CREATE INDEX IF NOT EXISTS pcm_chunks_content_trgm_idx
ON pcm_knowledge_chunks USING gin (content gin_trgm_ops);

CREATE TABLE IF NOT EXISTS pcm_chunk_embeddings (
    generation_id UUID NOT NULL REFERENCES pcm_index_generations(generation_id),
    chunk_id TEXT NOT NULL REFERENCES pcm_knowledge_chunks(chunk_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (generation_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS pcm_chunk_embeddings_hnsw_idx
ON pcm_chunk_embeddings USING hnsw (embedding vector_cosine_ops);

UPDATE pcm_projects
SET knowledge_index_revision = 0,
    active_index_generation = NULL
WHERE active_index_generation IS NULL;
