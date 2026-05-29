-- 009_spec_modules.sql (PostgreSQL)
-- Evidence-first Medical RAG 스펙 정합용 스키마 보강
-- (작업지시서 §3.3 Source Registry, §3.4 Chunk, §13 Audit/Review)
-- 적용: run-migration Cloud Run Job 또는 psql. (※ 클라우드 적용은 별도 승인 후)

-- ── Source Registry 보강 (§3.3) ──────────────────────────────────────────────
ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS priority_rank   INT DEFAULT 3;
ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS jurisdiction    TEXT DEFAULT 'KR';
ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS medical_domain  TEXT[] DEFAULT '{}';
ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS institution     TEXT;
ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS update_cycle    TEXT;

-- 알려진 출처 priority_rank 시드 (낮을수록 우선)
UPDATE kb_sources SET priority_rank = 1, jurisdiction = 'KR' WHERE source_id IN ('kdca','kdca_api','health_kdca','mfds','mfds_dur','hira','hira_dur');
UPDATE kb_sources SET priority_rank = 2, jurisdiction = 'KR' WHERE source_id IN ('guideline','kmle');
UPDATE kb_sources SET priority_rank = 3 WHERE source_id IN ('who','cdc','nice');
UPDATE kb_sources SET priority_rank = 6 WHERE source_id IN ('pubmed','pmc_oa');

-- ── Chunk 메타 보강 (§3.4) ───────────────────────────────────────────────────
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS source_priority      INT DEFAULT 3;
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS population_tags      TEXT[] DEFAULT '{}';
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS risk_tags            TEXT[] DEFAULT '{}';
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS recommendation_grade TEXT;
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS chunk_type           TEXT DEFAULT 'patient_info';
ALTER TABLE kb_chunks ADD COLUMN IF NOT EXISTS heading_path         TEXT;

-- source_priority를 kb_sources.priority_rank로 백필
UPDATE kb_chunks c SET source_priority = s.priority_rank
  FROM kb_sources s WHERE c.source_id = s.source_id AND s.priority_rank IS NOT NULL;

-- ── Audit 보강 (§13 D-2) ─────────────────────────────────────────────────────
ALTER TABLE rag_queries ADD COLUMN IF NOT EXISTS answer_id      TEXT;
ALTER TABLE rag_queries ADD COLUMN IF NOT EXISTS model_version  TEXT;
ALTER TABLE rag_queries ADD COLUMN IF NOT EXISTS prompt_version TEXT;
ALTER TABLE rag_queries ADD COLUMN IF NOT EXISTS classification_json TEXT;
ALTER TABLE rag_queries ADD COLUMN IF NOT EXISTS evidence_pack_json  TEXT;

-- ── Review Queue (§13 E-2) ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS review_queue_items (
    id            TEXT PRIMARY KEY,
    answer_id     TEXT,
    rag_query_id  TEXT,
    question      TEXT,
    answer        TEXT,
    priority      TEXT DEFAULT 'medium',   -- low|medium|high
    assignee_role TEXT DEFAULT 'doctor',   -- doctor|pharmacist|legal
    reasons_json  TEXT DEFAULT '[]',
    status        TEXT DEFAULT 'pending',  -- pending|in_review|resolved|dismissed
    reviewer_id   TEXT,
    review_label  TEXT,
    review_note   TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    reviewed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue_items(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_priority ON review_queue_items(priority);
