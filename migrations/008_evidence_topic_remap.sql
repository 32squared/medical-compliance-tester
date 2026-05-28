-- =============================================================================
-- 008_evidence_topic_remap.sql — kb_chunks.evidence_topic 수동 매핑 보정
-- 호환: PostgreSQL (Cloud SQL)
-- 멱등성: UPDATE는 WHERE 조건 기반 → 재실행 시 이미 매핑된 행은 무변경
-- 목적: validate-rag-direct 결과에서 no_topic_match가 지배적이었던 원인 해소
--       → KB 문서 title 패턴 기준으로 evidence_topic 강제 부여
-- =============================================================================

BEGIN;

-- ── 사전 진단 ───────────────────────────────────────────────────────────────
DO $$
DECLARE
    v_total   INTEGER;
    v_general INTEGER;
    v_null    INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_total FROM kb_chunks;
    SELECT COUNT(*) INTO v_general FROM kb_chunks WHERE evidence_topic = 'general';
    SELECT COUNT(*) INTO v_null FROM kb_chunks WHERE evidence_topic IS NULL OR evidence_topic = '';
    RAISE NOTICE '[008] 사전: total=%, general=%, null/empty=%',
                 v_total, v_general, v_null;
END;
$$;

-- ── 심정지 / CPR / 심폐소생 ─────────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'cardiac_arrest'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND document_id IN (
       SELECT id FROM kb_documents
        WHERE title ILIKE '%심정지%'
           OR title ILIKE '%심폐소생%'
           OR title ILIKE '%CPR%'
           OR title ILIKE '%심폐%'
   );

-- ── AED / 자동심장충격기 ─────────────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'aed_usage'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND document_id IN (
       SELECT id FROM kb_documents
        WHERE title ILIKE '%AED%'
           OR title ILIKE '%자동심장%'
           OR title ILIKE '%심장충격%'
           OR title ILIKE '%제세동%'
   );

-- ── 응급상황 / 응급실 / 위험신호 ────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'emergency_signs'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND document_id IN (
       SELECT id FROM kb_documents
        WHERE title ILIKE '%응급실%'
           OR title ILIKE '%응급상황%'
           OR title ILIKE '%위험신호%'
           OR title ILIKE '%응급의료%'
           OR title ILIKE '%119%'
   );

-- ── 발열 / 체온 ─────────────────────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'fever'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND (
       document_id IN (
           SELECT id FROM kb_documents
            WHERE title ILIKE '%발열%'
               OR title ILIKE '%체온%'
               OR title ILIKE '%고열%'
               OR title ILIKE '%열%'
       )
       -- 짧은 청크(1000자 이하)에서 발열 키워드가 있는 경우도 보정
       OR (content ILIKE '%발열%' AND LENGTH(content) < 1000)
   );

-- ── 기침 / 가래 / 객담 ──────────────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'cough'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND document_id IN (
       SELECT id FROM kb_documents
        WHERE title ILIKE '%기침%'
           OR title ILIKE '%가래%'
           OR title ILIKE '%객담%'
           OR title ILIKE '%해수%'
   );

-- ── 당뇨 / 혈당 / 인슐린 ────────────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'diabetes'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND document_id IN (
       SELECT id FROM kb_documents
        WHERE title ILIKE '%당뇨%'
           OR title ILIKE '%혈당%'
           OR title ILIKE '%인슐린%'
           OR title ILIKE '%당화%'
   );

-- ── 호흡곤란 / 천식 ─────────────────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'dyspnea'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND document_id IN (
       SELECT id FROM kb_documents
        WHERE title ILIKE '%호흡곤란%'
           OR title ILIKE '%천식%'
           OR title ILIKE '%숨%'
           OR title ILIKE '%호흡%'
   );

-- ── 두통 / 편두통 ────────────────────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'headache'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND document_id IN (
       SELECT id FROM kb_documents
        WHERE title ILIKE '%두통%'
           OR title ILIKE '%편두통%'
           OR title ILIKE '%머리%아%'
   );

-- ── 혈압 / 고혈압 / 저혈압 ──────────────────────────────────────────────────
UPDATE kb_chunks
   SET evidence_topic = 'hypertension'
 WHERE (evidence_topic = 'general' OR evidence_topic IS NULL OR evidence_topic = '')
   AND document_id IN (
       SELECT id FROM kb_documents
        WHERE title ILIKE '%혈압%'
           OR title ILIKE '%고혈압%'
           OR title ILIKE '%저혈압%'
   );

-- ── 사후 검증 ───────────────────────────────────────────────────────────────
DO $$
DECLARE
    v_total   INTEGER;
    v_general INTEGER;
    v_null    INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_total FROM kb_chunks;
    SELECT COUNT(*) INTO v_general FROM kb_chunks WHERE evidence_topic = 'general';
    SELECT COUNT(*) INTO v_null FROM kb_chunks WHERE evidence_topic IS NULL OR evidence_topic = '';
    RAISE NOTICE '[008] 사후: total=%, general=%, null/empty=%',
                 v_total, v_general, v_null;
END;
$$;

COMMIT;
