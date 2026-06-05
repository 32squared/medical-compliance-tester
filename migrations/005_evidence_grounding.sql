-- =============================================================================
-- 005_evidence_grounding.sql — Phase A Retrieval Gate 컬럼 추가 (PostgreSQL)
-- 호환: PostgreSQL (Cloud SQL)
-- 멱등성: ADD COLUMN IF NOT EXISTS
-- 실행: python migrations/run_migration_005.py
-- =============================================================================

BEGIN;

ALTER TABLE rag_queries
    ADD COLUMN IF NOT EXISTS evidence_quality      TEXT,
    ADD COLUMN IF NOT EXISTS retrieval_top1_score  REAL,
    ADD COLUMN IF NOT EXISTS retrieval_chunk_count INTEGER,
    ADD COLUMN IF NOT EXISTS retrieval_weighted_score REAL,
    ADD COLUMN IF NOT EXISTS gate_decision         TEXT,
    ADD COLUMN IF NOT EXISTS blocked_reasons       JSONB,
    ADD COLUMN IF NOT EXISTS claims_json           TEXT,
    ADD COLUMN IF NOT EXISTS verified_at           TEXT;

CREATE INDEX IF NOT EXISTS idx_rag_queries_gate_decision
    ON rag_queries(gate_decision);

CREATE INDEX IF NOT EXISTS idx_rag_queries_evidence_quality
    ON rag_queries(evidence_quality);

COMMIT;
