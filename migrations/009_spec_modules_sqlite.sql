-- 009_spec_modules_sqlite.sql (SQLite 개발 모드)
-- PostgreSQL 배열 타입은 TEXT(JSON)로 대체. ADD COLUMN IF NOT EXISTS 미지원이므로
-- run_migration 스크립트가 OperationalError(duplicate column)를 무시하도록 처리한다.

ALTER TABLE kb_sources ADD COLUMN priority_rank INTEGER DEFAULT 3;
ALTER TABLE kb_sources ADD COLUMN jurisdiction TEXT DEFAULT 'KR';
ALTER TABLE kb_sources ADD COLUMN medical_domain TEXT DEFAULT '[]';
ALTER TABLE kb_sources ADD COLUMN institution TEXT;
ALTER TABLE kb_sources ADD COLUMN update_cycle TEXT;

ALTER TABLE kb_chunks ADD COLUMN source_priority INTEGER DEFAULT 3;
ALTER TABLE kb_chunks ADD COLUMN population_tags TEXT DEFAULT '[]';
ALTER TABLE kb_chunks ADD COLUMN risk_tags TEXT DEFAULT '[]';
ALTER TABLE kb_chunks ADD COLUMN recommendation_grade TEXT;
ALTER TABLE kb_chunks ADD COLUMN chunk_type TEXT DEFAULT 'patient_info';
ALTER TABLE kb_chunks ADD COLUMN heading_path TEXT;

ALTER TABLE rag_queries ADD COLUMN answer_id TEXT;
ALTER TABLE rag_queries ADD COLUMN model_version TEXT;
ALTER TABLE rag_queries ADD COLUMN prompt_version TEXT;
ALTER TABLE rag_queries ADD COLUMN classification_json TEXT;
ALTER TABLE rag_queries ADD COLUMN evidence_pack_json TEXT;

CREATE TABLE IF NOT EXISTS review_queue_items (
    id            TEXT PRIMARY KEY,
    answer_id     TEXT,
    rag_query_id  TEXT,
    question      TEXT,
    answer        TEXT,
    priority      TEXT DEFAULT 'medium',
    assignee_role TEXT DEFAULT 'doctor',
    reasons_json  TEXT DEFAULT '[]',
    status        TEXT DEFAULT 'pending',
    reviewer_id   TEXT,
    review_label  TEXT,
    review_note   TEXT,
    created_at    TEXT DEFAULT (datetime('now')),
    reviewed_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue_items(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_priority ON review_queue_items(priority);
