-- =============================================================================
-- 003_kb_source_url.sql — kb_documents에 원본 URL 추적 컬럼 추가
-- 목적: 사용자(의사)가 KB 문서의 원본 출처를 클릭으로 검증 가능하게 함
-- 호환: PostgreSQL (Cloud SQL) — IF NOT EXISTS 사용
-- 멱등성: ADD COLUMN IF NOT EXISTS + INSERT ON CONFLICT DO NOTHING
-- 실행: python migrations/run_migration_003.py
-- =============================================================================

-- 1) kb_documents 컬럼 추가
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS source_url       TEXT;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS source_fetched_at TEXT;
ALTER TABLE kb_documents ADD COLUMN IF NOT EXISTS source_checksum   TEXT;  -- SHA-256 변경 감지용

-- 2) 검색용 인덱스 (URL dedup, 변경 감지)
CREATE INDEX IF NOT EXISTS idx_kb_documents_source_url
  ON kb_documents(source_url) WHERE source_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_kb_documents_source_checksum
  ON kb_documents(source_checksum) WHERE source_checksum IS NOT NULL;

-- 3) 공공 출처 신규 시드 (멱등)
INSERT INTO kb_sources (id, name, source_type, license, update_frequency, is_active, created_at)
VALUES
  ('mfds',     '식품의약품안전처 의약품안전나라 (안전성 서한·DUR)',  'public', 'kogl_type1', 'weekly',  1, NOW()),
  ('nemc',     '응급의료포털 응급처치 가이드',                        'public', 'kogl_type1', 'monthly', 1, NOW()),
  ('kdca_api', '공공데이터포털 KDCA OpenAPI (감염병·예방접종)',       'public', 'kogl_type1', 'monthly', 1, NOW())
ON CONFLICT (id) DO NOTHING;
