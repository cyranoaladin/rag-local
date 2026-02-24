-- ═══════════════════════════════════════════════════════════
-- RAG Service v2 — Initialisation PostgreSQL + pgvector
-- ═══════════════════════════════════════════════════════════

-- Activation des extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- ═══════════════════════════
-- SCHÉMA PRINCIPAL
-- ═══════════════════════════

CREATE TABLE IF NOT EXISTS rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant VARCHAR(64) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_path TEXT NOT NULL,
    title TEXT,
    label TEXT,
    mime_type VARCHAR(64),
    file_hash VARCHAR(64),
    char_count INTEGER,
    chunk_count INTEGER DEFAULT 0,
    embed_model VARCHAR(128) NOT NULL DEFAULT 'nomic-embed-text:v1.5',
    embed_dim INTEGER NOT NULL DEFAULT 768,
    ingested_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}',
    UNIQUE(source_path, tenant)
);

CREATE TABLE IF NOT EXISTS rag_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
    tenant VARCHAR(64) NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding VECTOR(768),
    text_tsv TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('french', coalesce(text, ''))
    ) STORED,
    char_start INTEGER,
    char_end INTEGER,
    page_number INTEGER,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

-- Table API keys (sécurité)
CREATE TABLE IF NOT EXISTS rag_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant VARCHAR(64) NOT NULL,
    key_hash VARCHAR(128) NOT NULL UNIQUE,
    label VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true
);

-- Table métriques qualité RAG (évaluation)
CREATE TABLE IF NOT EXISTS rag_eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant VARCHAR(64) NOT NULL,
    run_at TIMESTAMPTZ DEFAULT NOW(),
    embed_model VARCHAR(128),
    precision_at_5 FLOAT,
    recall_at_5 FLOAT,
    mrr FLOAT,
    ndcg FLOAT,
    avg_latency_ms FLOAT,
    gold_set_version VARCHAR(32),
    metadata JSONB DEFAULT '{}'
);

-- ═══════════════════════════
-- INDEX OPTIMISÉS
-- ═══════════════════════════

-- HNSW pour similarité cosine (meilleur recall que IVFFlat)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON rag_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- GIN pour BM25 / full-text search
CREATE INDEX IF NOT EXISTS idx_chunks_text_tsv
    ON rag_chunks USING GIN(text_tsv);

-- Index tenant pour filtrage
CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON rag_chunks(tenant);
CREATE INDEX IF NOT EXISTS idx_docs_tenant ON rag_documents(tenant);
CREATE INDEX IF NOT EXISTS idx_docs_hash ON rag_documents(file_hash, tenant);
CREATE INDEX IF NOT EXISTS idx_docs_source ON rag_documents(source_path, tenant);

-- GIN index sur metadata JSONB pour filtrage rapide par taxonomie (section, matiere, niveau)
CREATE INDEX IF NOT EXISTS idx_chunks_metadata_gin ON rag_chunks USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_docs_metadata_gin ON rag_documents USING GIN(metadata);

-- ═══════════════════════════
-- TRIGGERS
-- ═══════════════════════════

-- Mise à jour automatique updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON rag_documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Mise à jour chunk_count automatique
CREATE OR REPLACE FUNCTION update_chunk_count()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE rag_documents
    SET chunk_count = (SELECT COUNT(*) FROM rag_chunks WHERE document_id = COALESCE(NEW.document_id, OLD.document_id))
    WHERE id = COALESCE(NEW.document_id, OLD.document_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_chunk_count
    AFTER INSERT OR DELETE ON rag_chunks
    FOR EACH ROW EXECUTE FUNCTION update_chunk_count();
