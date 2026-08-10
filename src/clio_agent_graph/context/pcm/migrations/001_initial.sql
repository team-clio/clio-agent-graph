CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS pcm_projects (
    project_id TEXT PRIMARY KEY,
    active_pcm_revision BIGINT NOT NULL DEFAULT 0 CHECK (active_pcm_revision >= 0),
    knowledge_index_revision BIGINT NOT NULL DEFAULT 0 CHECK (knowledge_index_revision >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pcm_source_events (
    project_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
    commit_result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, source_event_id)
);

CREATE TABLE IF NOT EXISTS pcm_document_revisions (
    project_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    title TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, document_id, source_revision)
);

CREATE TABLE IF NOT EXISTS pcm_knowledge (
    project_id TEXT NOT NULL,
    knowledge_id TEXT NOT NULL,
    logical_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, knowledge_id),
    UNIQUE (project_id, logical_key)
);

CREATE TABLE IF NOT EXISTS pcm_commits (
    commit_id UUID PRIMARY KEY,
    project_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    base_pcm_revision BIGINT NOT NULL,
    target_pcm_revision BIGINT NOT NULL,
    change_summary JSONB NOT NULL,
    committed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, source_event_id)
);

CREATE TABLE IF NOT EXISTS pcm_knowledge_revisions (
    project_id TEXT NOT NULL,
    knowledge_id TEXT NOT NULL,
    knowledge_revision BIGINT NOT NULL CHECK (knowledge_revision >= 1),
    knowledge_type TEXT NOT NULL,
    title TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    body_content_hash TEXT NOT NULL,
    valid_from_pcm_revision BIGINT NOT NULL,
    valid_until_pcm_revision BIGINT,
    sources JSONB NOT NULL,
    related_knowledge_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_tombstone BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_commit_id UUID NOT NULL REFERENCES pcm_commits(commit_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, knowledge_id, knowledge_revision),
    FOREIGN KEY (project_id, knowledge_id)
        REFERENCES pcm_knowledge(project_id, knowledge_id)
);

CREATE INDEX IF NOT EXISTS pcm_knowledge_revision_snapshot_idx
ON pcm_knowledge_revisions (
    project_id,
    valid_from_pcm_revision,
    valid_until_pcm_revision
);

CREATE INDEX IF NOT EXISTS pcm_knowledge_title_trgm_idx
ON pcm_knowledge_revisions USING gin (title gin_trgm_ops);

CREATE TABLE IF NOT EXISTS pcm_schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
