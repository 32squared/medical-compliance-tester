-- =============================================================================
-- 005_evidence_grounding_sqlite.sql — Phase A Retrieval Gate 컬럼 추가 (SQLite)
-- SQLite는 ADD COLUMN IF NOT EXISTS 미지원 → run_migration_005.py에서
-- duplicate column 오류를 무시하는 방식으로 멱등성 보장.
-- =============================================================================

ALTER TABLE rag_queries ADD COLUMN evidence_quality      TEXT;
ALTER TABLE rag_queries ADD COLUMN retrieval_top1_score  REAL;
ALTER TABLE rag_queries ADD COLUMN retrieval_chunk_count INTEGER;
ALTER TABLE rag_queries ADD COLUMN retrieval_weighted_score REAL;
ALTER TABLE rag_queries ADD COLUMN gate_decision         TEXT;
ALTER TABLE rag_queries ADD COLUMN blocked_reasons       TEXT;
ALTER TABLE rag_queries ADD COLUMN claims_json           TEXT;
ALTER TABLE rag_queries ADD COLUMN verified_at           TEXT;

CREATE INDEX IF NOT EXISTS idx_rag_queries_gate_decision
    ON rag_queries(gate_decision);

CREATE INDEX IF NOT EXISTS idx_rag_queries_evidence_quality
    ON rag_queries(evidence_quality);
