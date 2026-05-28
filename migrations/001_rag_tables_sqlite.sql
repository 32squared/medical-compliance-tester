-- =============================================================================
-- 001_rag_tables_sqlite.sql  — RAG Phase 1 마이그레이션 (SQLite 로컬 개발용)
-- 주의: SQLite는 pgvector 미지원 — 벡터 컬럼은 TEXT(JSON serialized array)로 모킹
--       RAG 기능(/api/rag/*) 은 SQLite 모드에서 HTTP 503 반환 (T6/T7 구현 시)
--       로컬 개발 환경에서 테이블 구조 호환성만 유지하는 것이 목적
-- 멱등성: CREATE TABLE IF NOT EXISTS
-- =============================================================================

-- SQLite는 DDL 트랜잭션 지원 (BEGIN/COMMIT 사용)
BEGIN;

-- ---------------------------------------------------------------------------
-- 1. kb_sources
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_sources (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    license             TEXT NOT NULL,
    url                 TEXT,
    update_frequency    TEXT,
    last_updated_at     TEXT,
    is_active           INTEGER DEFAULT 1,
    created_at          TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 2. kb_documents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_documents (
    id                  TEXT PRIMARY KEY,
    source_id           TEXT,
    title               TEXT NOT NULL,
    content_md          TEXT NOT NULL,
    metadata_json       TEXT DEFAULT '{}',
    status              TEXT DEFAULT 'draft',
    author_id           TEXT,
    approved_by         TEXT,
    approved_at         TEXT,
    rejected_reason     TEXT,
    evidence_level      TEXT DEFAULT 'B',
    last_verified_date  TEXT,
    version             INTEGER DEFAULT 1,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES kb_sources(id)
);

CREATE INDEX IF NOT EXISTS idx_kb_documents_status ON kb_documents(status);
CREATE INDEX IF NOT EXISTS idx_kb_documents_source ON kb_documents(source_id);

-- ---------------------------------------------------------------------------
-- 3. kb_chunks  (벡터 컬럼 = TEXT, pgvector 미지원 모킹)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_chunks (
    id                          TEXT PRIMARY KEY,
    document_id                 TEXT NOT NULL,
    chunk_index                 INTEGER NOT NULL,
    content                     TEXT NOT NULL,
    section_path                TEXT,

    -- 벡터 컬럼: SQLite에서는 TEXT (JSON serialized float array)
    -- PostgreSQL의 vector(1536) / vector(1024) 를 모킹
    embedding_primary           TEXT,   -- JSON: [0.1, 0.2, ...]  (1536-dim)
    embedding_secondary         TEXT,   -- JSON: [0.1, 0.2, ...]  (1024-dim, Phase 4)
    embedding_primary_model     TEXT NOT NULL DEFAULT '',
    embedding_secondary_model   TEXT,
    secondary_indexed_at        TEXT,

    -- 자문 반영 신규 메타 컬럼
    evidence_country            TEXT,
    evidence_topic              TEXT,
    regulatory_korea            INTEGER DEFAULT 0,  -- SQLite: 0/1 (BOOLEAN 모킹)
    topic_keywords              TEXT DEFAULT '[]',  -- JSON array

    -- 일반 메타
    token_count                 INTEGER,
    symptom_tags                TEXT DEFAULT '[]',
    severity                    TEXT,
    content_tsv                 TEXT,   -- SQLite: tsvector 미지원, TEXT로 저장
    created_at                  TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES kb_documents(id) ON DELETE CASCADE
);

-- 벡터 인덱스는 SQLite에서 생성 불가 — B-tree 인덱스만 생성
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id);

-- ---------------------------------------------------------------------------
-- 4. llm_providers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_providers (
    id                      TEXT PRIMARY KEY,
    label                   TEXT NOT NULL,
    provider                TEXT NOT NULL,
    model_id                TEXT NOT NULL,
    base_url                TEXT,
    api_key_encrypted       TEXT,
    max_tokens              INTEGER DEFAULT 2048,
    temperature             REAL DEFAULT 0.3,
    streaming_supported     INTEGER DEFAULT 1,
    is_active               INTEGER DEFAULT 1,
    cost_per_1m_input       REAL,
    cost_per_1m_output      REAL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 5. rag_queries  (query_embedding도 TEXT 모킹)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rag_queries (
    id                      TEXT PRIMARY KEY,
    conversation_id         TEXT,
    user_id                 TEXT,
    query_text              TEXT NOT NULL,
    query_embedding         TEXT,       -- JSON serialized vector (모킹)
    retrieved_chunk_ids     TEXT NOT NULL,
    rerank_scores           TEXT,
    llm_provider_id         TEXT,
    system_prompt_hash      TEXT,
    response_text           TEXT,
    citations_json          TEXT,
    latency_total_ms        INTEGER,
    latency_retrieval_ms    INTEGER,
    latency_llm_ms          INTEGER,
    token_input             INTEGER,
    token_output            INTEGER,
    cost_usd                REAL,
    guardrail_violations    TEXT,
    guardrail_action        TEXT,
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_queries_conv ON rag_queries(conversation_id);
CREATE INDEX IF NOT EXISTS idx_rag_queries_user ON rag_queries(user_id);
CREATE INDEX IF NOT EXISTS idx_rag_queries_date ON rag_queries(created_at);

-- ---------------------------------------------------------------------------
-- 6. kb_feedback
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_feedback (
    id              TEXT PRIMARY KEY,
    rag_query_id    TEXT,
    chunk_id        TEXT,
    feedback_type   TEXT,
    note            TEXT,
    evaluator_id    TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (rag_query_id) REFERENCES rag_queries(id),
    FOREIGN KEY (chunk_id) REFERENCES kb_chunks(id)
);

-- ---------------------------------------------------------------------------
-- 7. embedding_providers
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_providers (
    slot                TEXT PRIMARY KEY,
    provider            TEXT NOT NULL,
    model_id            TEXT NOT NULL,
    dimension           INTEGER NOT NULL,
    base_url            TEXT,
    api_key_encrypted   TEXT,
    is_active           INTEGER DEFAULT 1,
    migration_status    TEXT DEFAULT 'stable',
    rollout_percentage  INTEGER DEFAULT 0,
    last_changed_by     TEXT,
    last_changed_at     TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 8. email_notifications
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_notifications (
    id              TEXT PRIMARY KEY,
    recipient       TEXT NOT NULL,
    subject         TEXT NOT NULL,
    body_html       TEXT NOT NULL,
    category        TEXT,
    status          TEXT DEFAULT 'pending',
    sent_at         TEXT,
    error_message   TEXT,
    created_at      TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 9. embedding_migration_log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_migration_log (
    id              TEXT PRIMARY KEY,
    checkpoint      TEXT NOT NULL,
    from_state      TEXT,
    to_state        TEXT,
    triggered_by    TEXT NOT NULL,
    approved_at     TEXT NOT NULL,
    rollback_plan   TEXT,
    metrics_json    TEXT,
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- 10. 기존 conversations 테이블 ALTER (SQLite는 IF NOT EXISTS 미지원 — try/except)
--     run_migration.py 에서 python으로 각각 실행하며 오류 무시
--     여기서는 문서화 목적으로 기재
-- ---------------------------------------------------------------------------
-- ALTER TABLE conversations ADD COLUMN emergency_state TEXT DEFAULT 'NORMAL';
-- ALTER TABLE conversations ADD COLUMN emergency_redirected_at TEXT;

-- ---------------------------------------------------------------------------
-- 11~12. 시드 데이터 (SQLite: INSERT OR IGNORE)
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO embedding_providers
    (slot, provider, model_id, dimension, is_active, migration_status,
     rollout_percentage, last_changed_by, last_changed_at)
VALUES
    ('default', 'openai', 'text-embedding-3-small', 1536, 1, 'stable',
     100, 'system_init', datetime('now'));

INSERT OR IGNORE INTO llm_providers
    (id, label, provider, model_id, max_tokens, temperature,
     streaming_supported, is_active, created_at, updated_at)
VALUES
    ('openai_gpt5',
     'GPT-5 (메인)',
     'openai', 'gpt-5',
     2048, 0.3, 1, 1, datetime('now'), datetime('now')),
    ('openai_gpt5_mini',
     'GPT-5 mini (재생성/저비용)',
     'openai', 'gpt-5-mini',
     2048, 0.3, 1, 1, datetime('now'), datetime('now'));

COMMIT;
