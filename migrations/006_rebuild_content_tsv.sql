-- =============================================================================
-- 006_rebuild_content_tsv.sql — kb_chunks.content_tsv 일괄 재생성 (PostgreSQL)
-- 호환: PostgreSQL (Cloud SQL)
-- 멱등성: WHERE content IS NOT NULL (재실행 안전)
-- 목적: BM25 sparse 검색 0건 → content_tsv NULL 일괄 채움
-- tokenizer: simple (한글 키워드 매칭, 형태소 분석 없음)
-- =============================================================================

BEGIN;

-- 사전 진단 (출력용)
DO $$
DECLARE
    v_total   INTEGER;
    v_with_tsv INTEGER;
    v_missing  INTEGER;
BEGIN
    SELECT COUNT(*),
           COUNT(content_tsv),
           COUNT(*) FILTER (WHERE content_tsv IS NULL)
      INTO v_total, v_with_tsv, v_missing
      FROM kb_chunks;

    RAISE NOTICE '[006] 사전 진단: total=%, with_tsv=%, missing=%',
                 v_total, v_with_tsv, v_missing;
END;
$$;

-- 일괄 재생성 (단일 트랜잭션, 멱등)
UPDATE kb_chunks
   SET content_tsv = to_tsvector('simple', COALESCE(content, ''))
 WHERE content IS NOT NULL;

-- 사후 검증 (출력용)
DO $$
DECLARE
    v_total    INTEGER;
    v_with_tsv INTEGER;
    v_hits_fever INTEGER;
BEGIN
    SELECT COUNT(*), COUNT(content_tsv)
      INTO v_total, v_with_tsv
      FROM kb_chunks;

    SELECT COUNT(*)
      INTO v_hits_fever
      FROM kb_chunks
     WHERE content_tsv @@ plainto_tsquery('simple', '발열');

    RAISE NOTICE '[006] 사후 검증: total=%, with_tsv=%, tsv_rate=%s%%, hits(발열)=%',
                 v_total, v_with_tsv,
                 CASE WHEN v_total > 0
                      THEN ROUND(v_with_tsv::NUMERIC / v_total * 100, 1)
                      ELSE 0 END,
                 v_hits_fever;
END;
$$;

COMMIT;
