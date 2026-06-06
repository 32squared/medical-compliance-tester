-- =============================================================================
-- 001_rag_tables.sql  — RAG Phase 1 마이그레이션 (PostgreSQL 전용)
-- 대상 DB  : medical_app (Cloud SQL PostgreSQL 15)
-- 실행 방식: run_migration.py 또는 gcloud sql connect 직접 실행
-- 멱등성   : CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / ON CONFLICT DO NOTHING
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Extension 확인 (이미 활성화 완료 전제 — vector 0.8.1, pg_trgm 1.6)
--    이 SQL만 단독 실행할 경우를 위해 idempotent하게 재선언
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- 1. kb_sources  — KB 소스 정보
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_sources (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    source_type         TEXT NOT NULL,       -- 'guideline' | 'public' | 'internal'
    license             TEXT NOT NULL,       -- 'public_domain' | 'kogl_type1' | 'proprietary'
    url                 TEXT,
    update_frequency    TEXT,                -- 'monthly' | 'quarterly' | 'on_demand'
    last_updated_at     TEXT,
    is_active           INTEGER DEFAULT 1,
    created_at          TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 2. kb_documents  — KB 문서 원본
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_documents (
    id                  TEXT PRIMARY KEY,    -- uuid
    source_id           TEXT REFERENCES kb_sources(id),
    title               TEXT NOT NULL,
    content_md          TEXT NOT NULL,       -- 원본 마크다운
    metadata_json       TEXT DEFAULT '{}',   -- symptom_tags, age_group 등
    status              TEXT DEFAULT 'draft',
    -- status: draft | pending_review | approved | active | archived
    author_id           TEXT,
    approved_by         TEXT,
    approved_at         TEXT,
    rejected_reason     TEXT,
    evidence_level      CHAR(1) DEFAULT 'B', -- 'A' | 'B' | 'C'
    last_verified_date  TEXT,
    version             INTEGER DEFAULT 1,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kb_documents_status  ON kb_documents(status);
CREATE INDEX IF NOT EXISTS idx_kb_documents_source  ON kb_documents(source_id);

-- ---------------------------------------------------------------------------
-- 3. kb_chunks  — 청크 + 벡터 (듀얼 임베딩 컬럼 + 자문 반영 메타 컬럼)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_chunks (
    id                          TEXT PRIMARY KEY,
    document_id                 TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index                 INTEGER NOT NULL,
    content                     TEXT NOT NULL,
    section_path                TEXT,        -- JSON array of section titles

    -- 임베딩 듀얼 컬럼 (마이그레이션 대비, embedding_migration_strategy.md §1.2)
    embedding_primary           vector(1536),         -- Phase 1: OpenAI text-embedding-3-small
    embedding_secondary         vector(1024),          -- Phase 4: BGE-M3 (현재 NULL)
    embedding_primary_model     TEXT NOT NULL,         -- 'openai_small_v3'
    embedding_secondary_model   TEXT,                  -- NULL = 듀얼 모드 아님
    secondary_indexed_at        TEXT,

    -- 자문 반영 신규 메타 컬럼 (2026-05-27, expert_review_insights.md)
    evidence_country            TEXT,                  -- 'KR' | 'US' | 'EU' | 'other'
    evidence_topic              TEXT,                  -- 'fever_pediatric' 등 핵심 주제
    regulatory_korea            BOOLEAN DEFAULT FALSE, -- 국내 규제(심평원·식약처) 관련 여부
    topic_keywords              TEXT DEFAULT '[]',     -- JSON array — BM25 보조

    -- 일반 메타
    token_count                 INTEGER,
    symptom_tags                TEXT DEFAULT '[]',     -- JSON array
    severity                    TEXT,
    content_tsv                 tsvector,              -- BM25용 (to_tsvector 자동 채움)
    created_at                  TEXT NOT NULL
);

-- HNSW 인덱스: embedding_primary (m=16, ef_construction=64)
-- partial index: embedding_primary IS NOT NULL 조건으로 NULL 청크 제외
CREATE INDEX IF NOT EXISTS idx_kb_chunks_emb_primary
    ON kb_chunks USING hnsw (embedding_primary vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- secondary 인덱스는 Phase 4 듀얼 인덱싱 시점에 생성 (현재 주석)
-- CREATE INDEX idx_kb_chunks_emb_secondary
--     ON kb_chunks USING hnsw (embedding_secondary vector_cosine_ops)
--     WITH (m = 16, ef_construction = 64);

-- BM25 (tsvector GIN)
CREATE INDEX IF NOT EXISTS idx_kb_chunks_tsv      ON kb_chunks USING gin(content_tsv);

-- 메타 필터링 B-tree
CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id);

-- ---------------------------------------------------------------------------
-- 4. llm_providers  — LLM 프로바이더 설정
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_providers (
    id                      TEXT PRIMARY KEY,   -- 'openai_gpt5' 등
    label                   TEXT NOT NULL,
    provider                TEXT NOT NULL,      -- 'openai' | 'anthropic' | 'vertex' | 'self_hosted'
    model_id                TEXT NOT NULL,      -- 'gpt-5' / 'gpt-5-mini' 등
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
-- 5. rag_queries  — RAG 질의 감사 추적 로그
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rag_queries (
    id                      TEXT PRIMARY KEY,
    conversation_id         TEXT,
    user_id                 TEXT,
    query_text              TEXT NOT NULL,
    query_embedding         vector(1536),       -- 디버깅용, 옵션
    retrieved_chunk_ids     TEXT NOT NULL,      -- JSON array
    rerank_scores           TEXT,               -- JSON [{chunk_id, score}]
    llm_provider_id         TEXT,
    system_prompt_hash      TEXT,
    response_text           TEXT,
    citations_json          TEXT,               -- JSON [{marker:"[1]", chunk_id:"..."}]
    latency_total_ms        INTEGER,
    latency_retrieval_ms    INTEGER,
    latency_llm_ms          INTEGER,
    token_input             INTEGER,
    token_output            INTEGER,
    cost_usd                REAL,
    guardrail_violations    TEXT,               -- JSON array
    guardrail_action        TEXT,               -- 'pass' | 'regenerated' | 'blocked'
    created_at              TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rag_queries_conv  ON rag_queries(conversation_id);
CREATE INDEX IF NOT EXISTS idx_rag_queries_user  ON rag_queries(user_id);
CREATE INDEX IF NOT EXISTS idx_rag_queries_date  ON rag_queries(created_at);

-- ---------------------------------------------------------------------------
-- 6. kb_feedback  — 의사 KB 피드백 (response_feedback과 별도)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_feedback (
    id              TEXT PRIMARY KEY,
    rag_query_id    TEXT REFERENCES rag_queries(id),
    chunk_id        TEXT REFERENCES kb_chunks(id),
    feedback_type   TEXT,   -- 'good_citation' | 'irrelevant' | 'outdated' | 'wrong_info'
    note            TEXT,
    evaluator_id    TEXT,
    created_at      TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 7. embedding_providers  — 임베딩 모델 슬롯 설정 (마이그레이션 제어)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_providers (
    slot                TEXT PRIMARY KEY,   -- 'default' | 'ingest' | 'shadow'
    provider            TEXT NOT NULL,      -- 'openai' | 'bge_m3'
    model_id            TEXT NOT NULL,
    dimension           INTEGER NOT NULL,
    base_url            TEXT,
    api_key_encrypted   TEXT,
    is_active           INTEGER DEFAULT 1,
    -- 마이그레이션 상태 추적 (embedding_migration_strategy.md §1.2)
    migration_status    TEXT DEFAULT 'stable',
    -- 'stable' | 'dual_indexing' | 'shadow_eval' | 'rollout' | 'migrating' | 'rollback'
    rollout_percentage  INTEGER DEFAULT 0,  -- 0~100, 신규 모델 사용 비율
    last_changed_by     TEXT,
    last_changed_at     TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 8. email_notifications  — 이메일 알림 큐 (Phase 4 발송 로직 구현 예정)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS email_notifications (
    id              TEXT PRIMARY KEY,
    recipient       TEXT NOT NULL,
    subject         TEXT NOT NULL,
    body_html       TEXT NOT NULL,
    category        TEXT,       -- 'checkpoint_wait' | 'auto_rollback' | 'daily_summary'
    status          TEXT DEFAULT 'pending',  -- 'pending' | 'sent' | 'failed'
    sent_at         TEXT,
    error_message   TEXT,
    created_at      TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 9. embedding_migration_log  — 마이그레이션 감사 추적
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_migration_log (
    id              TEXT PRIMARY KEY,
    checkpoint      TEXT NOT NULL,      -- 'check_1' ~ 'check_7'
    from_state      TEXT,
    to_state        TEXT,
    triggered_by    TEXT NOT NULL,
    approved_at     TEXT NOT NULL,
    rollback_plan   TEXT,
    metrics_json    TEXT,
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- 10. (이전됨) conversations EMERGENCY_REDIRECTED 상태머신 컬럼
--     conversations 는 호스트(테스트 시스템) 소유 테이블이므로, 이 컬럼 ALTER 는
--     호스트 마이그레이션(db.py init_db 의 migrations_pg / migrations)으로 이전했다.
--     RAG 마이그레이션은 호스트 테이블을 변형하지 않는다(저장소 분리 불변식).
--     rag_architecture.md §5.7
--     ※ Phase 1 에서 emergency_state 자체를 RAG 소유 테이블로 이관 예정.
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 11. 시드 데이터 — embedding_providers (ON CONFLICT DO NOTHING 으로 멱등)
-- ---------------------------------------------------------------------------
INSERT INTO embedding_providers
    (slot, provider, model_id, dimension, is_active, migration_status,
     rollout_percentage, last_changed_by, last_changed_at)
VALUES
    ('default', 'openai', 'text-embedding-3-small', 1536, 1, 'stable',
     100, 'system_init', NOW())
ON CONFLICT (slot) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 12. 시드 데이터 — llm_providers (GPT-5 메인 + GPT-5-mini 저비용)
-- ---------------------------------------------------------------------------
INSERT INTO llm_providers
    (id, label, provider, model_id, max_tokens, temperature,
     streaming_supported, is_active, created_at, updated_at)
VALUES
    ('openai_gpt5',
     'GPT-5 (메인)',
     'openai', 'gpt-5',
     2048, 0.3, 1, 1, NOW(), NOW()),
    ('openai_gpt5_mini',
     'GPT-5 mini (재생성/저비용)',
     'openai', 'gpt-5-mini',
     2048, 0.3, 1, 1, NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

COMMIT;
