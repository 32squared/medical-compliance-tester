-- =============================================================================
-- 004_health_kdca_source.sql — 국가건강정보포털 (health.kdca.go.kr) 출처 시드
-- 호환: PostgreSQL (Cloud SQL)
-- 멱등성: INSERT ON CONFLICT DO NOTHING
-- 실행: python migrations/run_migration_004.py
-- =============================================================================

INSERT INTO kb_sources (id, name, source_type, license, update_frequency, is_active, created_at)
VALUES ('health_kdca', '국가건강정보포털 (KDCA)', 'public', 'kogl_type1', 'monthly', 1, NOW())
ON CONFLICT (id) DO NOTHING;
