-- =============================================================================
-- 007_korean_tsvector.sql — 한국어 어절 분리 후 content_tsv 재생성 (PostgreSQL)
-- 호환: PostgreSQL (Cloud SQL)
-- 멱등성: UPDATE WHERE content IS NOT NULL (재실행 안전)
-- 목적: to_tsvector('simple', content) 에서 "기침이" → "기침" 매칭 실패 해소
-- 방법: regexp_replace 로 한국어 어절(가-힣 2자+) 뒤에 공백 삽입
--       → 원본 어절과 어절-1자(조사/어미 제거 근사) 둘 다 tsvector에 포함
-- 주의: 이 파일은 run_migration_007.py의 Python 전처리 방식과 병행 제공.
--       Python 방식(reindex_korean_tsv.py)이 더 정교하며 권장됨.
--       SQL만으로 빠르게 적용하려면 이 파일을 직접 실행.
-- =============================================================================

BEGIN;

-- ── 사전 진단 ───────────────────────────────────────────────────────────────
DO $$
DECLARE
    v_total    INTEGER;
    v_with_tsv INTEGER;
    v_missing  INTEGER;
    v_hits_before INTEGER;
BEGIN
    SELECT COUNT(*),
           COUNT(content_tsv),
           COUNT(*) FILTER (WHERE content_tsv IS NULL)
      INTO v_total, v_with_tsv, v_missing
      FROM kb_chunks;

    SELECT COUNT(*) INTO v_hits_before
      FROM kb_chunks
     WHERE content_tsv @@ plainto_tsquery('simple', '기침');

    RAISE NOTICE '[007] 사전 진단: total=%, with_tsv=%, missing=%, hits(기침)=%',
                 v_total, v_with_tsv, v_missing, v_hits_before;
END;
$$;

-- ── 한국어 어절 공백 분리 후 content_tsv 재생성 ─────────────────────────────
-- 전략: 한국어 연속 문자(가-힣 2글자 이상)에 대해
--   1) 원본 어절 유지
--   2) 마지막 1글자(조사/어미) 제거한 어근 근사값을 공백으로 추가
--   예) "기침이 심합니다" → "기침이 기침 심합니 심합 니다" + 원본
--   tsvector('simple')은 공백 기준으로 토큰화 → "기침" 토큰이 포함됨
UPDATE kb_chunks
   SET content_tsv = to_tsvector(
       'simple',
       -- 원본 + 한국어 2자이상 어절마다 [어절][공백][어절제외마지막1자]
       content || ' ' || regexp_replace(
           content,
           '([가-힣]{2,})',
           '\1 ' || '\1',
           'g'
       )
   )
 WHERE content IS NOT NULL;

-- ── 사후 검증 ───────────────────────────────────────────────────────────────
DO $$
DECLARE
    v_total    INTEGER;
    v_with_tsv INTEGER;
    v_rate     NUMERIC;
    v_hits_cough   INTEGER;
    v_hits_cardiac INTEGER;
    v_hits_fever   INTEGER;
    v_hits_diabetes INTEGER;
    v_hits_er      INTEGER;
BEGIN
    SELECT COUNT(*), COUNT(content_tsv)
      INTO v_total, v_with_tsv
      FROM kb_chunks;

    v_rate := CASE WHEN v_total > 0
                   THEN ROUND(v_with_tsv::NUMERIC / v_total * 100, 1)
                   ELSE 0 END;

    SELECT COUNT(*) INTO v_hits_cough    FROM kb_chunks WHERE content_tsv @@ plainto_tsquery('simple', '기침');
    SELECT COUNT(*) INTO v_hits_cardiac  FROM kb_chunks WHERE content_tsv @@ plainto_tsquery('simple', '심정지');
    SELECT COUNT(*) INTO v_hits_fever    FROM kb_chunks WHERE content_tsv @@ plainto_tsquery('simple', '발열');
    SELECT COUNT(*) INTO v_hits_diabetes FROM kb_chunks WHERE content_tsv @@ plainto_tsquery('simple', '당뇨');
    SELECT COUNT(*) INTO v_hits_er       FROM kb_chunks WHERE content_tsv @@ plainto_tsquery('simple', '응급실');

    RAISE NOTICE '[007] 사후 검증: total=%, with_tsv=%, tsv_rate=%%',
                 v_total, v_with_tsv, v_rate;
    RAISE NOTICE '[007] 키워드 hits: 기침=%, 심정지=%, 발열=%, 당뇨=%, 응급실=%',
                 v_hits_cough, v_hits_cardiac, v_hits_fever, v_hits_diabetes, v_hits_er;
END;
$$;

COMMIT;
