-- =============================================================================
-- 003_kb_source_url_sqlite.sql — kb_documents 원본 URL 추적 컬럼 (SQLite 호환)
-- SQLite는 IF NOT EXISTS for ADD COLUMN을 지원하지 않으므로
-- run_migration_003.py에서 OperationalError "duplicate column" 무시 처리.
-- =============================================================================

ALTER TABLE kb_documents ADD COLUMN source_url       TEXT;
ALTER TABLE kb_documents ADD COLUMN source_fetched_at TEXT;
ALTER TABLE kb_documents ADD COLUMN source_checksum   TEXT;

CREATE INDEX IF NOT EXISTS idx_kb_documents_source_url
  ON kb_documents(source_url);

CREATE INDEX IF NOT EXISTS idx_kb_documents_source_checksum
  ON kb_documents(source_checksum);

INSERT OR IGNORE INTO kb_sources (id, name, source_type, license, update_frequency, is_active, created_at)
VALUES
  ('mfds',     '식품의약품안전처 의약품안전나라',                'public', 'kogl_type1', 'weekly',  1, datetime('now')),
  ('nemc',     '응급의료포털 응급처치 가이드',                   'public', 'kogl_type1', 'monthly', 1, datetime('now')),
  ('kdca_api', '공공데이터포털 KDCA OpenAPI',                    'public', 'kogl_type1', 'monthly', 1, datetime('now'));
