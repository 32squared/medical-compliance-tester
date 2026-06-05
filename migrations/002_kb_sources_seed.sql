-- =============================================================================
-- 002_kb_sources_seed.sql — kb_sources 초기 시드 데이터
-- 대상: PostgreSQL (Cloud SQL) + SQLite (로컬 개발 모두 호환)
-- 멱등성: INSERT ... ON CONFLICT DO NOTHING (PG) / INSERT OR IGNORE (SQLite)
-- 실행: python migrations/run_migration.py 또는 직접 psql/sqlite3
-- =============================================================================

-- PostgreSQL
INSERT INTO kb_sources (id, name, source_type, license, update_frequency, is_active, created_at)
VALUES
  ('kmle_seed',   '대한의학회 KMLE 발췌',        'guideline', 'proprietary',  'quarterly',  1, NOW()),
  ('hira_kdca',   '심평원·질병관리청 공개 자료',  'public',    'kogl_type1',   'monthly',    1, NOW()),
  ('internal_md', '의사 직접 작성 콘텐츠',        'internal',  'proprietary',  'on_demand',  1, NOW())
ON CONFLICT (id) DO NOTHING;
