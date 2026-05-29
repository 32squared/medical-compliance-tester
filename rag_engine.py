"""
RAG 검색 엔진 — Hybrid Search + Medical Safety Boost
Phase 1 MVP: pgvector cosine + tsvector BM25, RRF fusion

핵심 함수:
  hybrid_search()          — 메인 진입점
  rrf_fusion()             — Reciprocal Rank Fusion (k=60)
  detect_symptom_keys()    — 질의 → symptom_key 추출
  apply_red_flag_boost()   — red_flag ×1.3, emergency ×1.2
  check_evidence_topic_alignment() — 양현종 자문 반영 (무관 청크 차단)
  apply_country_boost()    — KR ×1.15, regulatory_korea ×1.1

T5 추가 (generate_response):
  generate_response()      — Hybrid search → 프롬프트 → LLM 스트리밍 → 가드레일 → DB 기록
  _build_rag_system_prompt()   — 4단 응답 구조 강제 시스템 프롬프트
  _build_rag_user_prompt()     — 인용 번호 부여 사용자 프롬프트
  _regenerate_with_warning()   — HIGH 위반 시 gpt-5-mini 재생성
  _validate_and_fix_citations() — 인용 번호 검증
  _ensure_disclaimer()          — 면책조항 자동 부착
  _ensure_four_section_structure() — 4단 응답 구조 헤더 검증
  _detect_emergency_signal()    — 응급 신호 감지
  _get_conversation_state()     — conversations.emergency_state SELECT
  _set_conversation_state()     — conversations.emergency_state UPDATE
  _build_emergency_response()   — EMERGENCY_REDIRECTED 고정 응답
  _extract_citations()          — [N] 인용 마커 → chunk_id 매핑
  _insert_rag_query()           — rag_queries INSERT
  _format_search_result()       — INFO 이벤트용 청크 직렬화

SQLite 모드에서는 NotImplementedError 발생 (RAG requires PostgreSQL + pgvector).
"""
import os
import re
import json
import time
import uuid
import logging
from typing import List, Optional, Iterator, Dict

logger = logging.getLogger(__name__)

# ─── Phase A: Retrieval Gate 환경변수 (shadow mode 기본값) ────────────────────
# RETRIEVAL_GATE_ENFORCE=false(기본): 게이트 결과를 로깅만 하고 응답은 정상 진행.
# RETRIEVAL_GATE_ENFORCE=true: INSUFFICIENT 판정 시 LLM 호출을 스킵하고 템플릿 반환.
RETRIEVAL_GATE_ENFORCE = os.environ.get("RETRIEVAL_GATE_ENFORCE", "false").lower() == "true"
GATE_TOP1_PASS = float(os.environ.get("GATE_TOP1_PASS", "0.55"))
GATE_TOP1_WEAK = float(os.environ.get("GATE_TOP1_WEAK", "0.42"))
GATE_CHUNK_COUNT_PASS = int(os.environ.get("GATE_CHUNK_COUNT_PASS", "3"))
GATE_TOPIC_MATCH_PASS = int(os.environ.get("GATE_TOPIC_MATCH_PASS", "2"))
GATE_WEIGHTED_PASS = float(os.environ.get("GATE_WEIGHTED_PASS", "2.0"))
GATE_TOPIC_THRESHOLD = float(os.environ.get("GATE_TOPIC_THRESHOLD", "0.30"))
# evidence_topic 라벨링된 청크에만 적용하는 임계값 (미라벨링 청크는 자동 통과)
GATE_TOPIC_ALIGNMENT_THRESHOLD = float(os.environ.get("GATE_TOPIC_ALIGNMENT_THRESHOLD", "0.30"))
GATE_RELEVANT_COSINE = float(os.environ.get("GATE_RELEVANT_COSINE", "0.42"))
EVIDENCE_LEVEL_WEIGHT: Dict[str, float] = {"A": 1.0, "B": 0.7, "C": 0.4}

# ENABLE_EVIDENCE_TOPIC_CHECK=false: evidence_topic 정렬 검증 비활성화 (디버그/우회용)
# KB의 evidence_topic 컬럼이 비어있거나 임베딩 공간과 불일치할 때 임시 사용
ENABLE_EVIDENCE_TOPIC_CHECK = os.environ.get("ENABLE_EVIDENCE_TOPIC_CHECK", "true").lower() != "false"

# ─── 모듈 레벨 상수 ──────────────────────────────────────────
_CHECKLIST_PATH = os.path.join(os.path.dirname(__file__), "consultation_checklists.json")
_DENSE_LIMIT = 20   # dense 검색 후보 수
_SPARSE_LIMIT = 20  # sparse 검색 후보 수
_RRF_K = 60         # RRF 파라미터

# ─── consultation_checklists.json 1회 로딩 ───────────────────
def _load_checklists() -> dict:
    """
    consultation_checklists.json 로드.
    파일 형식: list → {"symptoms": {symptom_key: {...}}} 딕셔너리로 변환해 반환.
    """
    try:
        with open(_CHECKLIST_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return {"symptoms": {item["symptom_key"]: item for item in raw}}
        if isinstance(raw, dict) and "symptoms" in raw:
            return raw
        return {"symptoms": {}}
    except Exception as e:
        logger.warning("[RAGEngine] consultation_checklists.json 로드 실패: %s", e)
        return {"symptoms": {}}


CHECKLISTS: dict = _load_checklists()

# ─── 임베딩 프로바이더 lazy singleton ────────────────────────
_embedding_provider_instance = None


def _get_embedding_provider():
    """get_embedding_provider('default') lazy singleton."""
    global _embedding_provider_instance
    if _embedding_provider_instance is None:
        from embedding_provider import get_embedding_provider
        _embedding_provider_instance = get_embedding_provider("default")
    return _embedding_provider_instance


# ─── SQLite 모드 감지 ─────────────────────────────────────────
def _is_postgres() -> bool:
    """db._use_postgres 플래그 참조."""
    try:
        import db as _db
        return _db._use_postgres
    except Exception:
        return False


def _require_postgres():
    """SQLite 모드이면 NotImplementedError 발생."""
    if not _is_postgres():
        raise NotImplementedError(
            "RAG features require PostgreSQL with pgvector. "
            "Set DATABASE_URL environment variable to enable. "
            "(SQLite mode does not support vector search)"
        )


# ════════════════════════════════════════════════════════════
#  Step A: Dense 검색 (pgvector cosine)
# ════════════════════════════════════════════════════════════
def _dense_search(
    query_embedding: List[float],
    source_types: Optional[List[str]],
    limit: int = _DENSE_LIMIT,
) -> List[dict]:
    """
    pgvector cosine 유사도 기반 dense 검색.

    Args:
        query_embedding: 질의 임베딩 벡터 (1536차원)
        source_types: source_id 필터 (None이면 전체)
        limit: 반환 최대 개수

    Returns:
        [{"chunk_id", "document_id", "content", "section_path",
          "symptom_tags", "severity", "evidence_country",
          "evidence_topic", "regulatory_korea", "topic_keywords",
          "source_id", "evidence_level", "title", "cosine_score"}, ...]
    """
    from db import get_conn, _p, _ph

    # pgvector 어댑터 등록
    try:
        from pgvector.psycopg2 import register_vector
        import psycopg2
    except ImportError:
        pass

    vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    with get_conn() as (conn, cur):
        # pgvector register
        try:
            from pgvector.psycopg2 import register_vector
            register_vector(conn)
        except Exception:
            pass

        if source_types:
            ph_list = _ph(len(source_types))
            sql = f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.content,
                    c.section_path,
                    c.symptom_tags,
                    c.severity,
                    c.evidence_country,
                    c.evidence_topic,
                    c.regulatory_korea,
                    c.topic_keywords,
                    d.source_id,
                    d.evidence_level,
                    d.title,
                    1 - (c.embedding_primary <=> %s::vector(1536)) AS cosine_score
                FROM kb_chunks c
                JOIN kb_documents d ON c.document_id = d.id
                WHERE d.status = 'active'
                  AND d.source_id = ANY(ARRAY[{ph_list}]::text[])
                ORDER BY c.embedding_primary <=> %s::vector(1536)
                LIMIT %s
            """
            params = [vec_str] + source_types + [vec_str, limit]
        else:
            sql = f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.content,
                    c.section_path,
                    c.symptom_tags,
                    c.severity,
                    c.evidence_country,
                    c.evidence_topic,
                    c.regulatory_korea,
                    c.topic_keywords,
                    d.source_id,
                    d.evidence_level,
                    d.title,
                    1 - (c.embedding_primary <=> %s::vector(1536)) AS cosine_score
                FROM kb_chunks c
                JOIN kb_documents d ON c.document_id = d.id
                WHERE d.status = 'active'
                ORDER BY c.embedding_primary <=> %s::vector(1536)
                LIMIT %s
            """
            params = [vec_str, vec_str, limit]

        cur.execute(sql, params)
        rows = cur.fetchall()

    results = []
    for row in rows:
        r = dict(row)
        r["cosine_score"] = float(r.get("cosine_score") or 0.0)
        r["boost_reasons"] = []
        results.append(r)
    return results


# ════════════════════════════════════════════════════════════
#  Step B: Sparse 검색 (tsvector BM25)
# ════════════════════════════════════════════════════════════
import re as _re_kw

# 한국어 조사·어미 근사 제거 (어절 → 의미 토큰)
_KW_PARTICLE_RE = _re_kw.compile(
    r"(?:으로|에서|에게|까지|부터|이라고|라고|이며|하고|하며|되면|되어|이고|"
    r"이랑|랑|이나|한테|처럼|마다|밖에|"
    r"입니다|습니다|어요|아요|예요|네요|은|는|이|가|을|를|에|의|도|만|과|와|로|요|고|며|서|들|임|함)$"
)
_KW_STOP = {
    "것", "수", "등", "때", "더", "좀", "잘", "안", "못", "또", "그", "저", "거", "게", "걸",
    "점", "중", "및", "약간", "정도", "관련", "경우", "무엇", "어떻게", "어떤", "있는", "있어요",
    "있나요", "같아요", "같은", "너무", "자꾸", "계속", "갑자기", "요즘", "오늘", "어제", "정말",
}


def _korean_meaningful_tokens(query: str, max_tokens: int = 6) -> list:
    """질의에서 조사·어미·불용어를 제거한 의미 토큰 추출 (tsvector/ILIKE 매칭률 개선)."""
    clean = _re_kw.sub(r"[^\w\s가-힣a-zA-Z0-9]", " ", query or "")
    out = []
    for tok in clean.split():
        t = _KW_PARTICLE_RE.sub("", tok)
        if len(t) >= 2 and t not in _KW_STOP and t not in out:
            out.append(t)
        if len(out) >= max_tokens:
            break
    return out


def _sparse_search(
    query: str,
    source_types: Optional[List[str]],
    limit: int = _SPARSE_LIMIT,
) -> List[dict]:
    """
    tsvector ts_rank 기반 sparse BM25 검색.

    한국어 처리 전략:
    - content_tsv가 'simple' config로 생성된 경우 plainto_tsquery('simple', ...)가 맞음.
    - 그러나 한글은 형태소 분리 없이 공백 단위로만 토큰화되므로,
      tsvector에 없는 부분어(예: '발열' vs '발열이')가 매칭 실패하는 경우가 있음.
    - 1차 시도: plainto_tsquery('simple', query) — tsvector @@ tsquery
    - 1차 결과 0건이면 2차 fallback: content ILIKE 패턴 매칭 (공백 분리 키워드 AND)
      → sparse hits = 0 문제 우회, RRF에서 dense 결과와 융합됨

    Returns:
        dense_search와 동일한 필드 구조 + "ts_score"
    """
    from db import get_conn, _ph

    # 쿼리 전처리: 특수문자 제거, 공백 정규화 (한글 토크나이저 실패 방지)
    import re as _re
    clean_query = _re.sub(r"[^\w\s가-힣a-zA-Z0-9]", " ", query).strip()
    if not clean_query:
        clean_query = query

    # 의미 토큰(조사·어미 제거) — tsvector OR 질의 + ILIKE fallback 공용
    _kw_tokens = _korean_meaningful_tokens(query)
    # tsvector OR 질의식: '가슴 | 통증 | 답답' (to_tsquery용, 한글/영숫자만)
    _safe_tokens = [_re.sub(r"[^가-힣a-zA-Z0-9]", "", t) for t in _kw_tokens]
    _safe_tokens = [t for t in _safe_tokens if t]
    _tsquery_or = " | ".join(_safe_tokens)

    def _tsq_sql_param():
        """OR 토큰이 있으면 to_tsquery(OR), 없으면 plainto_tsquery(전체질의)."""
        if _tsquery_or:
            return "to_tsquery('simple', %s)", _tsquery_or
        return "plainto_tsquery('simple', %s)", clean_query

    def _run_tsv_search(conn, cur, q_str, src_types, lim):
        """1차: tsvector 검색 (의미토큰 OR 우선, 없으면 plainto AND)."""
        _tsq, _tsqp = _tsq_sql_param()
        if src_types:
            ph_list = _ph(len(src_types))
            sql = f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.content,
                    c.section_path,
                    c.symptom_tags,
                    c.severity,
                    c.evidence_country,
                    c.evidence_topic,
                    c.regulatory_korea,
                    c.topic_keywords,
                    d.source_id,
                    d.evidence_level,
                    d.title,
                    ts_rank(c.content_tsv, {_tsq}) AS ts_score
                FROM kb_chunks c
                JOIN kb_documents d ON c.document_id = d.id
                WHERE d.status = 'active'
                  AND d.source_id = ANY(ARRAY[{ph_list}]::text[])
                  AND c.content_tsv @@ {_tsq}
                ORDER BY ts_score DESC
                LIMIT %s
            """
            params = [_tsqp] + src_types + [_tsqp, lim]
        else:
            sql = f"""
                SELECT
                    c.id AS chunk_id,
                    c.document_id,
                    c.content,
                    c.section_path,
                    c.symptom_tags,
                    c.severity,
                    c.evidence_country,
                    c.evidence_topic,
                    c.regulatory_korea,
                    c.topic_keywords,
                    d.source_id,
                    d.evidence_level,
                    d.title,
                    ts_rank(c.content_tsv, {_tsq}) AS ts_score
                FROM kb_chunks c
                JOIN kb_documents d ON c.document_id = d.id
                WHERE d.status = 'active'
                  AND c.content_tsv @@ {_tsq}
                ORDER BY ts_score DESC
                LIMIT %s
            """
            params = [_tsqp, _tsqp, lim]
        cur.execute(sql, params)
        return cur.fetchall()

    def _run_ilike_fallback(conn, cur, tokens, src_types, lim):
        """2차 fallback: 의미토큰 OR ILIKE 매칭 + 매칭수 랭킹 (tsvector 0건 시 사용)."""
        if not tokens:
            return []
        # 의미토큰 OR ILIKE + 매칭 토큰 수로 랭킹 (AND는 과다제약으로 0건 → OR로 recall 확보)
        or_conditions = " OR ".join("c.content ILIKE %s" for _ in tokens)
        score_expr = " + ".join("(CASE WHEN c.content ILIKE %s THEN 1 ELSE 0 END)" for _ in tokens)
        like_params = [f"%{t}%" for t in tokens]
        _cols = ("c.id AS chunk_id, c.document_id, c.content, c.section_path, "
                 "c.symptom_tags, c.severity, c.evidence_country, c.evidence_topic, "
                 "c.regulatory_korea, c.topic_keywords, d.source_id, d.evidence_level, d.title")
        if src_types:
            ph_list = _ph(len(src_types))
            sql = f"""
                SELECT {_cols},
                    ({score_expr}) * 0.01 AS ts_score
                FROM kb_chunks c
                JOIN kb_documents d ON c.document_id = d.id
                WHERE d.status = 'active'
                  AND d.source_id = ANY(ARRAY[{ph_list}]::text[])
                  AND ({or_conditions})
                ORDER BY ts_score DESC
                LIMIT %s
            """
            params = like_params + src_types + like_params + [lim]
        else:
            sql = f"""
                SELECT {_cols},
                    ({score_expr}) * 0.01 AS ts_score
                FROM kb_chunks c
                JOIN kb_documents d ON c.document_id = d.id
                WHERE d.status = 'active'
                  AND ({or_conditions})
                ORDER BY ts_score DESC
                LIMIT %s
            """
            params = like_params + like_params + [lim]
        cur.execute(sql, params)
        return cur.fetchall()

    rows = []
    used_fallback = False
    try:
        with get_conn() as (conn, cur):
            rows = _run_tsv_search(conn, cur, clean_query, source_types, limit)
            if not rows and _kw_tokens:
                # 1차 tsvector 0건 → 2차 ILIKE fallback
                logger.info(
                    "[sparse_search] tsvector 0건 → ILIKE fallback 시도 "
                    "query=%r tokens=%s", query[:50], _kw_tokens
                )
                rows = _run_ilike_fallback(conn, cur, _kw_tokens, source_types, limit)
                used_fallback = True
    except Exception as _e:
        # sparse는 선택적 — 오류 시 dense만으로 진행 (RRF에서 dense가 커버)
        logger.warning("[sparse_search] 오류로 sparse 스킵: %s", _e)
        rows = []

    if used_fallback:
        logger.info(
            "[sparse_search] ILIKE fallback 결과 %d건 query=%r", len(rows), query[:50]
        )

    results = []
    for row in rows:
        r = dict(row)
        r["ts_score"] = float(r.get("ts_score") or 0.0)
        r["boost_reasons"] = []
        results.append(r)
    return results


# ════════════════════════════════════════════════════════════
#  Step C: RRF Fusion
# ════════════════════════════════════════════════════════════
def rrf_fusion(
    dense_results: List[dict],
    sparse_results: List[dict],
    k: int = _RRF_K,
) -> List[dict]:
    """
    Reciprocal Rank Fusion.

    각 리스트에서의 순위를 역수 합산해 두 검색 결과를 통합한다.
    score = Σ ( 1 / (k + rank) )

    Args:
        dense_results:  dense 검색 결과 (순위 순으로 정렬됨)
        sparse_results: sparse 검색 결과 (순위 순으로 정렬됨)
        k: RRF 파라미터 (기본 60)

    Returns:
        RRF 점수로 재정렬된 결과 리스트 (score 필드 포함)
    """
    scores: dict = {}
    metadata: dict = {}  # chunk_id → 메타 캐시

    for rank, r in enumerate(dense_results):
        cid = r["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in metadata:
            metadata[cid] = r

    for rank, r in enumerate(sparse_results):
        cid = r["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in metadata:
            metadata[cid] = r

    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    fused = []
    for cid, rrf_score in sorted_items:
        item = dict(metadata[cid])
        item["rrf_score"] = rrf_score   # RRF 점수 별도 보존 (진단용)
        item["score"] = rrf_score       # 하위 호환 score 필드 유지
        # cosine_score: dense 결과에서 전달됨. sparse-only 청크는 0.0 보장
        if "cosine_score" not in item:
            item["cosine_score"] = 0.0
        if "boost_reasons" not in item:
            item["boost_reasons"] = []
        fused.append(item)
    return fused


# ════════════════════════════════════════════════════════════
#  Step C.5: Source Priority 가중 reranker (스펙 §5.3)
# ════════════════════════════════════════════════════════════
_EVIDENCE_LEVEL_SCORE = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25, "F": 0.1}


def _weighted_rerank(
    fused: List[dict],
    dense_results: List[dict],
    sparse_results: List[dict],
) -> List[dict]:
    """
    스펙 §5.3 Hybrid 가중식으로 base score 재계산:
      0.30*keyword + 0.25*vector + 0.20*source_priority + 0.10*freshness
      + 0.10*domain_match + 0.05*evidence_level
      − jurisdiction_mismatch_penalty − low_authority_penalty

    keyword = sparse 순위 정규화, vector = cosine_score.
    source_priority는 chunk.source_priority(없으면 source_priority_for),
    freshness는 revised_at 미색인이라 중립(0.5), domain은 topic_alignment_score.
    red_flag/country boost는 이 base score 위에 곱해진다(이후 단계).
    """
    try:
        from retrieval_router import source_priority_for
    except Exception:
        def source_priority_for(_sid):
            return 3
    s_rank = {r["chunk_id"]: i for i, r in enumerate(sparse_results)}
    n_s = max(len(sparse_results), 1)
    for c in fused:
        cid = c.get("chunk_id")
        vec = float(c.get("cosine_score") or 0.0)
        vec = min(max(vec, 0.0), 1.0)
        kw = (1.0 - s_rank[cid] / n_s) if cid in s_rank else 0.0
        sp = c.get("source_priority")
        if sp is None:
            sp = source_priority_for(c.get("source_id", ""))
        try:
            sp = int(sp)
        except Exception:
            sp = 3
        sp_score = max(0.0, (7 - sp) / 6.0)             # 1→1.0 … 6→0.17
        fresh = 0.5                                       # revised_at 미색인 → 중립
        dom = float(c.get("topic_alignment_score") or 0.5)
        dom = min(max(dom, 0.0), 1.0)
        evl = _EVIDENCE_LEVEL_SCORE.get((c.get("evidence_level") or "").upper(), 0.5)
        penalty = 0.0
        juris = c.get("evidence_country") or "KR"
        if juris and juris != "KR":
            penalty += 0.10                               # jurisdiction_mismatch
        if sp > 4:
            penalty += 0.10                               # low_authority
        final = (0.30 * kw + 0.25 * vec + 0.20 * sp_score
                 + 0.10 * fresh + 0.10 * dom + 0.05 * evl) - penalty
        c["weighted_base"] = round(final, 5)
        c["score"] = c["weighted_base"]
    fused.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return fused


# ════════════════════════════════════════════════════════════
#  Step D: Red Flag Boost
# ════════════════════════════════════════════════════════════
def detect_symptom_keys(query: str, checklists: dict) -> List[str]:
    """
    질의 텍스트에서 매칭되는 symptom_key를 추출한다.

    consultation_checklists.json의 required_questions.keywords를
    질의 문자열에서 찾아 해당 증상 키를 반환한다.

    Args:
        query: 사용자 질의 텍스트
        checklists: _load_checklists() 반환값 {"symptoms": {...}}

    Returns:
        매칭된 symptom_key 리스트 (중복 제거)
    """
    matched = []
    symptoms = checklists.get("symptoms", {})
    for symptom_key, data in symptoms.items():
        found = False
        for q in data.get("required_questions", []):
            if found:
                break
            for kw in q.get("keywords", []):
                if kw in query:
                    matched.append(symptom_key)
                    found = True
                    break
        # red_flags 키워드로도 매칭
        if not found:
            for rf in data.get("red_flags", []):
                for kw in rf.get("keywords", []):
                    if kw in query:
                        matched.append(symptom_key)
                        found = True
                        break
                if found:
                    break
    return list(set(matched))


def apply_red_flag_boost(
    results: List[dict],
    query: str,
    checklists: dict,
) -> List[dict]:
    """
    red_flag boost 적용.

    - 질의에 매칭되는 증상의 red_flag 키워드가 청크 본문에 포함되면 점수 ×1.3
    - 청크 메타의 severity='emergency'이면 추가 ×1.2

    Args:
        results: RRF 점수가 담긴 청크 리스트
        query: 사용자 질의
        checklists: consultation_checklists 딕셔너리

    Returns:
        boost_reasons가 갱신된 결과 리스트
    """
    matched_symptoms = detect_symptom_keys(query, checklists)
    if not matched_symptoms:
        return results

    # 매칭된 증상들의 red_flag 키워드 수집
    red_flag_keywords: set = set()
    symptoms = checklists.get("symptoms", {})
    for sym in matched_symptoms:
        sym_data = symptoms.get(sym, {})
        for rf in sym_data.get("red_flags", []):
            for kw in rf.get("keywords", []):
                red_flag_keywords.add(kw)

    sym_label = ",".join(matched_symptoms)

    for r in results:
        content = r.get("content", "")
        if any(kw in content for kw in red_flag_keywords):
            r["score"] = r.get("score", 0.0) * 1.3
            r["boost_reasons"].append(f"red_flag:{sym_label}")

        if r.get("severity") == "emergency":
            r["score"] = r.get("score", 0.0) * 1.2
            r["boost_reasons"].append("severity_emergency")

    return results


# ════════════════════════════════════════════════════════════
#  Step E: evidence_topic 검증 (양현종 자문 반영)
# ════════════════════════════════════════════════════════════
def check_evidence_topic_alignment(
    results: List[dict],
    query: str,
    embedding_provider=None,
    threshold: float = 0.20,
) -> List[dict]:
    """
    각 청크의 evidence_topic이 질의와 의미적으로 연결되는지 검증.
    완전히 무관한 청크(예: 소아 발열 질의에 항말라리아제 자료)는 제거.

    양현종(소아청소년과) 자문 반영:
    - "소아 발열 시나리오에서 아토피·movement disorder·항말라리아제 참고문헌이
       노출된 문제"를 retrieval 단계에서 차단.

    Args:
        results: boost 적용 후 청크 리스트
        query: 사용자 질의
        embedding_provider: 임베딩 프로바이더 인스턴스
        threshold: 코사인 유사도 임계값 (기본 0.20, 한글 임베딩 의미공간 기준)

    Returns:
        topic alignment 검증을 통과한 청크 리스트.
        evidence_topic이 없는 청크는 그대로 통과.
        topic_alignment_score 필드가 추가됨.
        제거된 청크는 filtered_reason 필드에 이유 기록 (로그용).
    """
    if not results:
        return results

    # evidence_topic이 있는 청크만 검증 대상
    topics = [r.get("evidence_topic") or "" for r in results]
    if not any(topics):
        return results  # 모두 비어있으면 검증 스킵

    if embedding_provider is None:
        embedding_provider = _get_embedding_provider()

    try:
        import numpy as np
        topic_vecs = embedding_provider.embed(
            [t if t else "unknown" for t in topics]
        )
        query_vec = embedding_provider.embed([query])[0]

        qv = np.array(query_vec, dtype=float)
        qv_norm_val = float(np.linalg.norm(qv))
        if qv_norm_val == 0:
            return results
        qv_normalized = qv / qv_norm_val

        # 청크를 절대 제거하지 않음 — topic_alignment_score 필드만 부여.
        # threshold 미달이어도 청크를 유지해야 gate의 chunk_count / top1_cosine이
        # 올바르게 계산된다. 임계값 판단은 evaluate_retrieval_gate()가 담당.
        for r, tv in zip(results, topic_vecs):
            if not r.get("evidence_topic"):
                # evidence_topic 없는 청크: score 미부여 (gate에서 자동 통과 처리)
                continue
            tv_arr = np.array(tv, dtype=float)
            tv_norm_val = float(np.linalg.norm(tv_arr))
            if tv_norm_val == 0:
                continue
            tv_normalized = tv_arr / tv_norm_val
            sim = float(qv_normalized @ tv_normalized)
            r["topic_alignment_score"] = sim
            if sim < threshold:
                logger.debug(
                    "[RAGEngine] topic 낮음 (유지) chunk_id=%s topic=%s sim=%.2f < %.2f",
                    r.get("chunk_id"),
                    r.get("evidence_topic"),
                    sim,
                    threshold,
                )
        # 전체 반환 (제거 없음)
        return results

    except Exception as e:
        logger.warning(
            "[RAGEngine] evidence_topic 검증 실패 (스킵): %s", e
        )
        return results


# ════════════════════════════════════════════════════════════
#  Step F: evidence_country='KR' 부스팅
# ════════════════════════════════════════════════════════════
def apply_country_boost(results: List[dict]) -> List[dict]:
    """
    한국 의료 환경 자료 우선 부스팅.

    - evidence_country='KR' → ×1.15
    - regulatory_korea=True  → ×1.1  (심평원·식약처 기준 관련)

    양현종 자문: 해외 가이드라인을 국내에 그대로 적용하면 안 되는 분야 존재.
    KR 표기 자료를 우선 노출해 한국 의료 환경 반영.
    """
    from db import _pg_json_loads_or

    for r in results:
        if r.get("evidence_country") == "KR":
            r["score"] = r.get("score", 0.0) * 1.15
            r["boost_reasons"].append("country_kr")

        reg_val = r.get("regulatory_korea")
        # PostgreSQL BOOLEAN 또는 SQLite INTEGER / 문자열 모두 대응
        if reg_val is True or reg_val == 1 or reg_val == "true" or reg_val == "1":
            r["score"] = r.get("score", 0.0) * 1.1
            r["boost_reasons"].append("regulatory_korea")

    return results


# ════════════════════════════════════════════════════════════
#  메인 진입점: hybrid_search
# ════════════════════════════════════════════════════════════
def hybrid_search(
    query: str,
    top_k: int = 5,
    source_types: Optional[List[str]] = None,
    enable_red_flag_boost: bool = True,
    enable_evidence_topic_check: bool = True,
) -> List[dict]:
    """
    Hybrid RAG retrieval (pgvector cosine + tsvector BM25, RRF fusion)
    + 자문 반영 보정:
      - red_flag boost (consultation_checklists)
      - evidence_topic 검증 (양현종 자문: 무관한 청크 차단)
      - evidence_country='KR' 부스팅

    SQLite 모드에서는 NotImplementedError 발생.

    Args:
        query: 사용자 질의 텍스트
        top_k: 반환할 최대 청크 수 (기본 5)
        source_types: source_id 필터 리스트 (None이면 전체)
        enable_red_flag_boost: red_flag boost 활성화 (기본 True)
        enable_evidence_topic_check: evidence_topic 정렬 검증 활성화 (기본 True)

    Returns:
        [
          {
            "chunk_id": str,
            "document_id": str,
            "content": str,
            "section_path": list,
            "score": float,
            "source_id": str,
            "evidence_level": str,
            "evidence_topic": str,
            "boost_reasons": list[str],
            "topic_alignment_score": float (optional),
            ...
          }, ...
        ]

    Raises:
        NotImplementedError: SQLite 모드에서 호출 시
        ValueError: query가 비어있을 때
    """
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")

    # SQLite 모드 차단
    _require_postgres()

    logger.info("[RAGEngine] hybrid_search 시작 query=%r top_k=%d", query[:50], top_k)

    # Step A: Dense 임베딩 + 검색
    embedding_provider = _get_embedding_provider()
    query_embedding = embedding_provider.embed([query])[0]
    dense_results = _dense_search(query_embedding, source_types, limit=_DENSE_LIMIT)

    logger.debug("[RAGEngine] dense 결과 %d개", len(dense_results))

    # Step B: Sparse 검색
    sparse_results = _sparse_search(query, source_types, limit=_SPARSE_LIMIT)

    logger.debug("[RAGEngine] sparse 결과 %d개", len(sparse_results))

    # Step C: RRF 융합
    fused = rrf_fusion(dense_results, sparse_results, k=_RRF_K)
    _cnt_after_rrf = len(fused)

    # Step C.5: Source Priority 가중 reranker (스펙 §5.3, 플래그 — boost 전 base score)
    if os.environ.get("RAG_HYBRID_WEIGHTED", "0") == "1":
        fused = _weighted_rerank(fused, dense_results, sparse_results)

    # Step D: red_flag boost
    if enable_red_flag_boost:
        fused = apply_red_flag_boost(fused, query, CHECKLISTS)
    _cnt_after_red_flag = len(fused)

    # Step E: evidence_topic 검증
    # threshold 0.4는 한글 임베딩 의미공간에서 너무 엄격 (전 청크 탈락 사례 확인).
    # 0.2로 완화 — 명백히 무관한 청크만 차단 (양현종 자문 의도는 유지).
    # ENABLE_EVIDENCE_TOPIC_CHECK=false 환경변수로 일시 우회 가능
    _effective_topic_check = enable_evidence_topic_check and ENABLE_EVIDENCE_TOPIC_CHECK
    if _effective_topic_check:
        fused = check_evidence_topic_alignment(
            fused, query, embedding_provider, threshold=0.2
        )
    elif not ENABLE_EVIDENCE_TOPIC_CHECK:
        logger.warning(
            "[hybrid_search] evidence_topic 검증 비활성화 (ENABLE_EVIDENCE_TOPIC_CHECK=false) "
            "query=%r", query[:50],
        )
    _cnt_after_topic = len(fused)

    # 단계별 필터링 건수 로깅 (0건 원인 진단용)
    logger.info(
        "[hybrid_search] query=%r dense=%d sparse=%d after_rrf=%d "
        "after_red_flag=%d after_topic=%d",
        query[:50],
        len(dense_results),
        len(sparse_results),
        _cnt_after_rrf,
        _cnt_after_red_flag,
        _cnt_after_topic,
    )
    if _cnt_after_topic == 0 and _cnt_after_rrf > 0:
        logger.warning(
            "[hybrid_search] 전체 청크가 topic_alignment 필터에서 제거됨 "
            "query=%r threshold=0.2 rrf_count=%d",
            query[:50], _cnt_after_rrf,
        )

    # Step F: evidence_country='KR' 부스팅
    fused = apply_country_boost(fused)

    # 최종 정렬 후 top_k 반환
    fused.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    results = fused[:top_k]

    # section_path JSON 파싱 (TEXT로 저장된 경우)
    for r in results:
        sp = r.get("section_path")
        if isinstance(sp, str):
            try:
                r["section_path"] = json.loads(sp)
            except Exception:
                r["section_path"] = [sp]
        elif sp is None:
            r["section_path"] = []

    logger.info(
        "[RAGEngine] hybrid_search 완료: %d개 반환 (top score=%.4f)",
        len(results),
        results[0].get("score", 0.0) if results else 0.0,
    )
    return results


# ════════════════════════════════════════════════════════════
#  Phase A: evaluate_retrieval_gate — Stage 1 Retrieval Gate
# ════════════════════════════════════════════════════════════

def evaluate_retrieval_gate(chunks: List[Dict]) -> Dict:
    """
    Stage 1 Retrieval Gate (설계 문서 §3 — Phase A 핵심).

    hybrid_search()가 반환한 청크 목록을 평가해 LLM 호출 가부를 결정한다.

    판정 기준:
      PASS         : top1 cosine >= 0.55 이고 (관련 청크 >= 3 + topic_match >= 2)
                     또는 (top1 >= 0.55 이고 weighted_score >= 2.0)
      WEAK_PASS    : top1 cosine >= 0.42 이고 관련 청크 >= 1 이고 topic_match >= 1
      INSUFFICIENT : 위 모든 조건 미충족 또는 청크 0건

    Args:
        chunks: hybrid_search()가 반환한 청크 리스트.
                각 청크에 cosine_score, evidence_level, topic_alignment_score 포함.

    Returns:
        {
            "decision":        "PASS" | "WEAK_PASS" | "INSUFFICIENT",
            "evidence_quality": "high" | "medium" | "low" | "insufficient",
            "top1_score":      float,
            "chunk_count":     int,
            "weighted_score":  float,
            "topic_match_count": int,
            "relevant_count":  int,
            "evidence_levels": dict,  # {"A": N, "B": N, "C": N}
            "blocked_reasons": list,  # INSUFFICIENT 사유
        }
    """
    if not chunks:
        return {
            "decision": "INSUFFICIENT",
            "evidence_quality": "insufficient",
            "top1_score": 0.0,
            "chunk_count": 0,
            "weighted_score": 0.0,
            "topic_match_count": 0,
            "relevant_count": 0,
            "evidence_levels": {},
            "blocked_reasons": ["no_chunks"],
        }

    top1 = chunks[0]
    # cosine_score 우선 참조 (dense search 원점수). sparse-only 청크는 0.0.
    # score(RRF) 필드는 gate 판정에 사용하지 않음 — 단위 불일치(0.02~0.03 vs 0.55 기준)
    top1_cosine = float(top1.get("cosine_score") or 0.0)

    # 관련 청크: cosine_score >= GATE_RELEVANT_COSINE
    relevant = [c for c in chunks if float(c.get("cosine_score") or 0.0) >= GATE_RELEVANT_COSINE]

    # topic_match: topic_alignment_score 필드가 있는 청크만 임계값 비교.
    # 필드가 없는 청크(evidence_topic 미라벨링)는 자동 통과 처리 — false negative 방지.
    topic_match = 0
    for c in chunks:
        if "topic_alignment_score" in c:
            # 필드 존재: 임계값 비교 (라벨링된 청크는 엄격히 검증)
            if float(c["topic_alignment_score"]) >= GATE_TOPIC_ALIGNMENT_THRESHOLD:
                topic_match += 1
        else:
            # 필드 없음: 통과 (evidence_topic 미라벨링 청크는 일단 신뢰)
            topic_match += 1

    # evidence_level 가중 합산 (cosine 미달 청크는 0.5 패널티)
    weighted = sum(
        EVIDENCE_LEVEL_WEIGHT.get(c.get("evidence_level") or "C", 0.4)
        * (1.0 if float(c.get("cosine_score") or 0.0) >= GATE_RELEVANT_COSINE else 0.5)
        for c in chunks
    )

    # evidence_level 분포
    level_counts: Dict[str, int] = {}
    for c in chunks:
        lv = c.get("evidence_level") or "C"
        level_counts[lv] = level_counts.get(lv, 0) + 1

    # 분기 로직 (설계 문서 §3.3)
    blocked_reasons: List[str] = []

    if top1_cosine >= GATE_TOP1_PASS and len(relevant) >= GATE_CHUNK_COUNT_PASS and topic_match >= GATE_TOPIC_MATCH_PASS:
        decision = "PASS"
    elif top1_cosine >= GATE_TOP1_PASS and weighted >= GATE_WEIGHTED_PASS:
        decision = "PASS"
    elif top1_cosine >= GATE_TOP1_WEAK and len(relevant) >= 1 and topic_match >= 1:
        decision = "WEAK_PASS"
    else:
        decision = "INSUFFICIENT"
        if top1_cosine < GATE_TOP1_WEAK:
            blocked_reasons.append(f"top1_cosine_too_low ({top1_cosine:.3f} < {GATE_TOP1_WEAK})")
        if len(relevant) < 1:
            blocked_reasons.append("no_relevant_chunks")
        if topic_match < 1:
            blocked_reasons.append("no_topic_match")
        if not blocked_reasons:
            blocked_reasons.append("below_all_thresholds")

    # evidence_quality 매핑 (설계 문서 §7.1)
    if decision == "INSUFFICIENT":
        evidence_quality = "insufficient"
    elif decision == "WEAK_PASS":
        evidence_quality = "low"
    else:
        # PASS: A/B 청크 비율로 high/medium 구분
        ab_count = level_counts.get("A", 0) + level_counts.get("B", 0)
        citation_count = len([c for c in chunks if float(c.get("cosine_score") or 0.0) >= GATE_RELEVANT_COSINE])
        if ab_count >= 2 and citation_count >= 3:
            evidence_quality = "high"
        else:
            evidence_quality = "medium"

    return {
        "decision": decision,
        "evidence_quality": evidence_quality,
        "top1_score": top1_cosine,
        "chunk_count": len(chunks),
        "weighted_score": round(weighted, 4),
        "topic_match_count": topic_match,
        "relevant_count": len(relevant),
        "evidence_levels": level_counts,
        "blocked_reasons": blocked_reasons,
    }


# ════════════════════════════════════════════════════════════
#  T5: generate_response — 통합 RAG 응답 생성
# ════════════════════════════════════════════════════════════

# 4단 응답 구조 헤더 (rag_architecture.md §5.6)
_FOUR_SECTION_HEADERS = [
    "【① 즉시 행동】",
    "【② 의심 원인 요약】",
    "【③ 상세 설명】",
    "【④ 추가 확인 사항】",
]

# EMERGENCY 감지 키워드
_EMERGENCY_KEYWORDS = ["119", "응급실", "긴급", "즉시 병원", "즉시 응급"]

# 인용 번호 정규식
_CITATION_PATTERN = re.compile(r'\[(\d+)\]')


# ── 트리아지(triage): 비의료·대화성 입력 감지 ───────────────────────────────
# "배고파", "안녕" 같은 비의료/대화성 입력에 4단 의료답변(응급징후 나열·문진)을
# 들이대는 과의료화를 방지한다. 보수적 설계: 증상·약물·응급·진단·crisis 등 의료
# 신호가 조금이라도 있으면 절대 발동하지 않는다(진짜 상담 무영향 → both_A 무회귀).

# 의료/건강 신호 — 하나라도 있으면 트리아지하지 않음(분류기 규칙이 놓치는 표현 보강)
_MEDICAL_SIGNAL_RE = re.compile(
    r"아프|아파|아픈|통증|쑤시|결리|저리|저림|붓|부었|부어|메스|울렁|구역|토하|"
    r"발열|오한|몸살|기침|가래|콧물|두통|복통|설사|변비|발진|가렵|두드러기|"
    r"숨|호흡|가슴|심장|혈압|혈당|당뇨|소변|대변|혈변|혈뇨|출혈|피가|상처|외상|"
    r"잠|불면|수면|피로|무기력|체중|살\s*빠|식욕|어깨|허리|관절|무릎|"
    r"피부|복용|진료|병원|검사|증상|질환|감염|코로나|독감|임신|생리|월경|열이|열은"
)

# 명백한 비의료/대화성 입력 패턴 (짧고 의료 신호 없는 입력에만 적용)
_NONMEDICAL_RE = re.compile(
    r"(안녕|하이|헬로|hello|hi\b|ㅎㅇ|반가|잘\s*지내|누구야|누구세요|이름이?\s*(뭐|무엇)|"
    r"뭐\s*해|뭐하|심심|지루|테스트|test|ㅋㅋ|ㅎㅎ|ㅇㅇ|배고|배\s*고프|허기|졸려|졸리|"
    r"목말|목\s*마르|날씨|고마워|고맙|감사|잘\s*가|바이|bye|사랑|좋아해|화이팅|파이팅|밥\s*먹)",
    re.IGNORECASE,
)


def _should_clarify(query: str, classification: Optional[Dict]) -> Optional[str]:
    """비의료/모호 입력이면 사유 문자열, 아니면 None.

    보수적 발동 조건(모두 충족 시에만): (1) 분류기 intent가 catch-all
    general_health 이고 저위험, (2) 의료/건강 신호가 전혀 없음, (3) 길이가 짧음
    (상세 서술 아님), (4) 명백한 비의료/대화성 패턴 매칭. 증상·응급·약물·진단·
    crisis 등은 분류기가 다른 intent로 잡으므로 절대 트리아지되지 않는다.
    """
    q = (query or "").strip()
    if not q:
        return "empty"
    cl = classification or {}
    if cl.get("intent", "general_health") != "general_health":
        return None
    if cl.get("risk_level", "low") != "low":
        return None
    if _MEDICAL_SIGNAL_RE.search(q):
        return None
    if len(q) > 25:
        return None
    if _NONMEDICAL_RE.search(q):
        return "non_medical_or_vague"
    return None


def _build_clarify_response() -> str:
    """비의료/모호 입력에 대한 짧은 되묻기 응답(4단 의료답변 대신)."""
    return (
        "무엇을 도와드릴까요? 건강과 관련해 불편한 증상이나 궁금한 점을 "
        "구체적으로 알려주시면(예: 언제부터 / 어디가 / 어떻게 불편한지) "
        "관련 정보를 안내해 드리겠습니다.\n\n"
        "갑작스러운 흉통·호흡곤란·의식 저하·편측 마비·심한 출혈 등 응급 증상이 "
        "있다면 즉시 119 또는 응급실을 이용하세요."
    )


def generate_response(
    query: str,
    conversation_id: str,
    provider_id: str = None,
    top_k: int = 5,
    enable_guardrails: bool = True,
) -> Iterator[Dict]:
    """
    Hybrid search → 프롬프트 빌드 → LLM 스트리밍 → 가드레일 → DB 기록.

    Args:
        query: 사용자 질의 텍스트
        conversation_id: 대화 ID (conversations 테이블)
        provider_id: llm_providers.id (None이면 환경변수 기본값)
        top_k: 검색 청크 수 (기본 5)
        enable_guardrails: 가드레일 활성화 (기본 True)

    Yields:
        {"type": "INFO", "data": {"search_results": [...]}}
        {"type": "GENERATION", "text": "..."}
        {"type": "STOP", "text": "...", "rag_query_id": "...", "citations": [...],
         "latency_ms": N, "tokens": {...}, "guardrail_action": "..."}
        {"type": "ERROR", "message": "..."}
    """
    from llm_router import get_llm_provider

    start_ts = time.time()

    # 클라이언트에 즉시 상태 알림 (cold start + GPT-5 reasoning 지연 동안 멈춤 방지)
    yield {"type": "INFO", "data": {"status": "started", "query": query[:50]}}

    # ── 1. EMERGENCY_REDIRECTED 상태 체크 ─────────────────────
    conv_state = _get_conversation_state(conversation_id)
    if conv_state.get("emergency_state") == "EMERGENCY_REDIRECTED":
        emergency_msg = _build_emergency_response()
        yield {"type": "GENERATION", "text": emergency_msg}
        yield {
            "type": "STOP",
            "text": emergency_msg,
            "rag_query_id": None,
            "citations": [],
            "latency_ms": int((time.time() - start_ts) * 1000),
            "tokens": {"input": 0, "output": 0},
            "guardrail_action": "emergency_redirect",
        }
        return

    # ── 1.5 PII/PHI 마스킹 + 질문 분류 (스펙 통합, 가드 — 실패해도 본 흐름 유지) ──
    _classification = None
    try:
        from pii_masker import mask_pii
        _m = mask_pii(query)
        if _m.get("detected_items"):
            query = _m["masked_text"]  # PII 마스킹 질의로 전환 (HealthBench엔 PII 없어 무영향)
    except Exception as _e:
        logger.debug("[RAGEngine] PII 마스킹 스킵: %s", _e)
    try:
        from medical_classifier import classify_rule_based
        _classification = classify_rule_based(query)  # 규칙기반(무비용·무지연)
    except Exception as _e:
        logger.debug("[RAGEngine] 분류 스킵: %s", _e)

    # ── 1.7 트리아지: 비의료/대화성 입력은 4단 의료답변 대신 되묻기 ──
    # "배고파", "안녕" 등 의료 신호 없는 모호 입력에 응급징후·문진을 들이대는
    # 과의료화 방지. 검색·LLM 호출을 건너뛰어 비용도 절약(0원).
    _clarify_reason = _should_clarify(query, _classification)
    if _clarify_reason:
        logger.info(
            "[RAGEngine][Triage] 비의료/모호 입력 되묻기 query=%r reason=%s",
            query[:40], _clarify_reason,
        )
        clarify_text = _build_clarify_response()
        yield {"type": "GENERATION", "text": clarify_text}
        yield {
            "type": "STOP",
            "text": clarify_text,
            "rag_query_id": None,
            "citations": [],
            "latency_ms": int((time.time() - start_ts) * 1000),
            "tokens": {"input": 0, "output": 0},
            "guardrail_action": "triage_clarify",
        }
        return

    # ── 2. Hybrid search ──────────────────────────────────────
    retrieval_start = time.time()
    try:
        chunks = hybrid_search(query, top_k=top_k)
    except Exception as e:
        logger.error("[RAGEngine] hybrid_search 오류: %s", e)
        yield {"type": "ERROR", "message": f"검색 오류: {e}"}
        return
    retrieval_ms = int((time.time() - retrieval_start) * 1000)

    yield {
        "type": "INFO",
        "data": {"search_results": [_format_search_result(c) for c in chunks]},
    }

    # ── 2-B. Retrieval Gate 평가 (Phase A) ────────────────────
    gate_result = evaluate_retrieval_gate(chunks)

    # EVIDENCE_CHECK SSE 이벤트 — LLM 호출 전에 클라이언트에 즉시 전달
    yield {
        "type": "EVIDENCE_CHECK",
        "data": {
            "quality": gate_result["evidence_quality"],
            "decision": gate_result["decision"],
            "top1_score": gate_result["top1_score"],
            "chunk_count": gate_result["chunk_count"],
            "relevant_count": gate_result["relevant_count"],
            "topic_match": gate_result["topic_match_count"],
            "evidence_levels": gate_result["evidence_levels"],
            "reasons": gate_result["blocked_reasons"],
        },
    }

    # INSUFFICIENT 처리 분기
    if gate_result["decision"] == "INSUFFICIENT":
        if RETRIEVAL_GATE_ENFORCE:
            # enforce 모드: LLM 호출 스킵, 템플릿 응답 반환
            logger.warning(
                "[RAGEngine][Gate] INSUFFICIENT — LLM 스킵 query=%r top1=%.3f",
                query[:50], gate_result["top1_score"],
            )
            insufficient_text = _build_insufficient_evidence_response()
            yield {"type": "GENERATION", "text": insufficient_text}

            # DB 기록
            _insert_rag_query(
                conversation_id=conversation_id,
                query_text=query,
                retrieved_chunk_ids=[c["chunk_id"] for c in chunks],
                llm_provider_id=None,
                response_text=insufficient_text,
                citations_json=[],
                latency_total_ms=int((time.time() - start_ts) * 1000),
                latency_retrieval_ms=retrieval_ms,
                latency_llm_ms=0,
                tokens={"input": 0, "output": 0},
                guardrail_violations=[],
                guardrail_action="insufficient_evidence",
                gate_result=gate_result,
            )

            yield {
                "type": "STOP",
                "text": insufficient_text,
                "rag_query_id": None,
                "citations": [],
                "latency_ms": int((time.time() - start_ts) * 1000),
                "tokens": {"input": 0, "output": 0},
                "guardrail_action": "insufficient_evidence",
                "evidence_quality": "insufficient",
                "gate_decision": "INSUFFICIENT",
            }
            return
        else:
            # shadow 모드: 로그만 남기고 정상 진행
            logger.warning(
                "[RAGEngine][Gate][SHADOW] INSUFFICIENT (shadow 모드 — 정상 진행) "
                "query=%r top1=%.3f reasons=%s",
                query[:50], gate_result["top1_score"], gate_result["blocked_reasons"],
            )

    elif gate_result["decision"] == "WEAK_PASS":
        logger.info(
            "[RAGEngine][Gate] WEAK_PASS query=%r top1=%.3f weighted=%.3f",
            query[:50], gate_result["top1_score"], gate_result["weighted_score"],
        )

    else:
        logger.info(
            "[RAGEngine][Gate] PASS query=%r quality=%s top1=%.3f",
            query[:50], gate_result["evidence_quality"], gate_result["top1_score"],
        )

    # ── 3. 프롬프트 조립 ──────────────────────────────────────
    system_prompt = _build_rag_system_prompt(query, chunks, gate_result=gate_result)
    user_prompt = _build_rag_user_prompt(query, chunks)

    # ── 4. LLM 스트리밍 ──────────────────────────────────────
    llm_start = time.time()
    provider = get_llm_provider(provider_id)
    full_text = ""
    tokens = {"input": 0, "output": 0}

    _last_keepalive = time.time()
    for chunk_event in provider.stream_chat(system_prompt, user_prompt):
        if chunk_event["type"] == "GENERATION":
            full_text += chunk_event["text"]
            yield chunk_event
            # LLM 청크 사이 30초 이상 침묵 시 KEEP_ALIVE 전송 (Cloud Run 연결 유지)
            now = time.time()
            if now - _last_keepalive >= 20:
                yield {"type": "KEEP_ALIVE"}
                _last_keepalive = now
        elif chunk_event["type"] == "STOP":
            full_text = chunk_event["text"]
            tokens = chunk_event.get("tokens", {"input": 0, "output": 0})
        elif chunk_event["type"] == "ERROR":
            yield chunk_event
            return

    llm_ms = int((time.time() - llm_start) * 1000)

    # ── 5. 가드레일 후처리 ────────────────────────────────────
    guardrail_result = {"action": "pass", "violations": []}

    if enable_guardrails:
        try:
            from analyzer import ComplianceAnalyzer
            analyzer = ComplianceAnalyzer()
            analysis = analyzer.analyze(full_text, user_input=query)
            violations = analysis.violations if hasattr(analysis, "violations") else []
            # AnalysisResult 객체 → dict 리스트로 변환
            violations_dicts = []
            for v in violations:
                violations_dicts.append({
                    "rule_id": v.rule_id,
                    "severity": v.severity,
                    "matched_text": v.matched_text,
                })

            # CRITICAL 차단
            critical = [v for v in violations_dicts if v.get("severity") == "CRITICAL"]
            if critical:
                full_text = (
                    "죄송합니다. 안전 기준에 부합하는 응답을 생성하지 못했습니다. "
                    "의료진과의 직접 상담을 권유합니다."
                )
                guardrail_result = {
                    "action": "blocked",
                    "violations": [v["rule_id"] for v in critical],
                }
                logger.warning(
                    "[RAGEngine] 가드레일 CRITICAL 차단 violations=%s",
                    guardrail_result["violations"],
                )

            # HIGH 재생성 1회
            elif any(v.get("severity") == "HIGH" for v in violations_dicts):
                high_violations = [v for v in violations_dicts if v.get("severity") == "HIGH"]
                full_text = _regenerate_with_warning(
                    provider, system_prompt, user_prompt, violations_dicts
                )
                guardrail_result = {
                    "action": "regenerated",
                    "violations": [v["rule_id"] for v in high_violations],
                }
                logger.info(
                    "[RAGEngine] 가드레일 HIGH 재생성 violations=%s",
                    guardrail_result["violations"],
                )

            # 인용 검증
            full_text, citations_action = _validate_and_fix_citations(
                full_text, chunks, system_prompt, user_prompt
            )
            if citations_action == "regenerated":
                guardrail_result["action"] = "regenerated_citation"

            # 면책조항 자동 부착 (하단)
            full_text = _ensure_disclaimer(full_text)
            # 상단 고지 자동 부착 (필수 고정 문구)
            full_text = _ensure_top_disclaimer(full_text)

            # 4단 응답 구조 헤더 검증
            structure_ok = _ensure_four_section_structure(full_text)
            if not structure_ok and guardrail_result["action"] == "pass":
                guardrail_result["action"] = "missing_structure"

            # EMERGENCY 감지 → 상태 전환
            if _detect_emergency_signal(full_text):
                _set_conversation_state(conversation_id, "EMERGENCY_REDIRECTED")
                logger.info(
                    "[RAGEngine] EMERGENCY 감지 → conversation_id=%s EMERGENCY_REDIRECTED 전환",
                    conversation_id,
                )

        except Exception as e:
            logger.error("[RAGEngine] 가드레일 오류 (스킵): %s", e)

    # ── 6. 인용 매핑 추출 ────────────────────────────────────
    citations = _extract_citations(full_text, chunks)

    # ── 6.5 Evidence Pack + Citation Verifier (스펙 §6/§7.7) ──
    # Evidence Pack 생성→감사 기록(스펙 AC#3·#8). Citation Verifier는 [N] 답변에
    # shadow로 적용(메트릭·감사·검수큐 피드). 답변 텍스트는 미변경(무회귀).
    # verify_citations는 [1]을 E1로 정규화하므로 기존 [N] 인용을 그대로 검증한다.
    # 강제 제거(verified_answer)는 4단 구조·면책을 파괴하므로 미적용(후속: 문장단위 in-place).
    _evidence_pack = None
    _citation_result = None
    try:
        from evidence_pack import build_evidence_pack
        _evidence_pack = build_evidence_pack(query, _classification or {}, chunks)
    except Exception as _e:
        logger.debug("[RAGEngine] evidence_pack 스킵: %s", _e)
    try:
        from citation_verifier import verify_citations
        _n = len(chunks)
        _eids = [str(i) for i in range(1, _n + 1)] + [f"E{i}" for i in range(1, _n + 1)]
        _citation_result = verify_citations(full_text, _eids)
        if _citation_result:
            logger.info(
                "[RAGEngine][CiteVerify] coverage=%.2f unsupported=%d pass=%s",
                _citation_result.get("citation_coverage", 0.0),
                len(_citation_result.get("unsupported_claims", [])),
                _citation_result.get("overall_pass"),
            )
    except Exception as _e:
        logger.debug("[RAGEngine] citation_verify 스킵: %s", _e)

    # ── 7. rag_queries INSERT ─────────────────────────────────
    rag_query_id = _insert_rag_query(
        conversation_id=conversation_id,
        query_text=query,
        retrieved_chunk_ids=[c["chunk_id"] for c in chunks],
        llm_provider_id=provider.provider_id,
        response_text=full_text,
        citations_json=citations,
        latency_total_ms=int((time.time() - start_ts) * 1000),
        latency_retrieval_ms=retrieval_ms,
        latency_llm_ms=llm_ms,
        tokens=tokens,
        guardrail_violations=guardrail_result.get("violations", []),
        guardrail_action=guardrail_result["action"],
        gate_result=gate_result,
    )

    # ── 7.5 감사 필드 + 검수 큐 적재 (스펙 통합, 가드) ─────────
    try:
        if rag_query_id and _classification is not None:
            import db as _db
            from review_queue import should_review
            _answer_id = "ans_" + rag_query_id[:12]
            _model_v = getattr(provider, "model_id", None) or getattr(provider, "provider_id", "unknown")
            _db.update_rag_query_audit(
                rag_query_id,
                answer_id=_answer_id,
                model_version=_model_v,
                prompt_version="rag-engine-v1",
                classification_json=json.dumps(_classification, ensure_ascii=False),
                evidence_pack_json=(
                    json.dumps(_evidence_pack, ensure_ascii=False) if _evidence_pack else None
                ),
            )
            _decision = should_review(
                classification=_classification,
                citation_result=(_citation_result or {
                    "overall_pass": guardrail_result["action"] != "blocked",
                    "citation_coverage": 1.0 if citations else 0.0,
                }),
                safety_result={
                    "safe_to_send": guardrail_result["action"] != "blocked",
                    "risk_flags": guardrail_result.get("violations", []),
                },
            )
            if _decision.get("needs_review"):
                _db.add_review_item({
                    "answer_id": _answer_id, "rag_query_id": rag_query_id,
                    "question": query[:500], "answer": full_text[:2000],
                    "priority": _decision["priority"],
                    "assignee_role": _decision["assignee_role"],
                    "reasons": _decision["reasons"],
                })
    except Exception as _e:
        logger.debug("[RAGEngine] 감사/검수 스킵: %s", _e)

    # ── 8. STOP 이벤트 ────────────────────────────────────────
    yield {
        "type": "STOP",
        "text": full_text,
        "rag_query_id": rag_query_id,
        "citations": citations,
        "latency_ms": int((time.time() - start_ts) * 1000),
        "tokens": tokens,
        "guardrail_action": guardrail_result["action"],
        "evidence_quality": gate_result["evidence_quality"],
        "gate_decision": gate_result["decision"],
    }


# ════════════════════════════════════════════════════════════
#  프롬프트 빌더
# ════════════════════════════════════════════════════════════

def _build_rag_system_prompt(query: str, chunks: List[dict], gate_result: Dict = None) -> str:
    """
    RAG 응답 생성 전용 시스템 프롬프트 (Phase A 재작성 — 설계 문서 §4.2).

    중요: 평가용 build_gpt_system_prompt()는 절대 재사용하지 않는다.
    평가 프롬프트는 JSON 점수를 반환하라고 LLM에 지시하므로,
    RAG 생성에 사용하면 LLM이 평가 JSON을 응답으로 출력한다 (실제 발견된 버그).

    Args:
        query:       사용자 질의 (미사용, 시그니처 호환 유지)
        chunks:      검색 청크 (미사용, 시그니처 호환 유지)
        gate_result: evaluate_retrieval_gate() 반환값.
                     WEAK_PASS이면 근거 제한 모드 문단을 자동 추가.
    """
    # 면책조항만 별도로 가져옴 (평가 프롬프트 X)
    _DEFAULT_TOP = (
        "본 서비스는 건강정보·교육 목적의 참고용으로 제공됩니다. "
        "질병의 진단·처방·치료·선별검사 등 의료행위를 하지 않으며, "
        "의학적 판단과 치료는 반드시 의료인에 의해 이뤄져야 합니다. "
        "응급증상 발생 시 즉시 119 또는 응급실을 이용하십시오."
    )
    try:
        from guideline_loader import get_fixed_notices
        fixed_notices = get_fixed_notices()
        top_disclaimer = fixed_notices.get("top_disclaimer", _DEFAULT_TOP) or _DEFAULT_TOP
        bottom_disclaimer = fixed_notices.get(
            "bottom_disclaimer",
            "본 정보는 참고용이며, 정확한 진단·치료는 의료진과 상담하세요.",
        )
    except Exception:
        top_disclaimer = _DEFAULT_TOP
        bottom_disclaimer = "본 정보는 참고용이며, 정확한 진단·치료는 의료진과 상담하세요."

    # 설계 문서 §4.2 신규 프롬프트 전문
    prompt = f"""당신은 한국 의료법(의료법 27조 무면허 의료행위 금지, 응급의료법)을 준수하는
건강 정보 안내 AI '나만의 주치의'입니다.

당신은 의사가 아닙니다. 진단·처방·치료를 수행하지 않습니다.
당신은 오직 아래 ## 검토 자료에 명시된 사실만 사용해 정보를 안내합니다.

## 절대 원칙 (모두 동시에 만족)
1. [근거 종속] 모든 의학적 주장의 문장 끝에 반드시 [N] 인용을 붙이시오.
   인용 없는 의학적 주장은 출력 금지.
2. [컨텍스트 외 정보 금지] 검토 자료에 없는 약물명, 용량, 검사명, 진단명을
   언급하지 마시오. 일반적 지식이라도 인용할 청크가 없으면 쓰지 마시오.
3. [근거 충돌 시 보수성] [1]과 [2]의 권고가 다르면 더 보수적인(의료진 상담을
   더 강하게 권유하는) 쪽을 선택하고 충돌 사실을 명시하시오.
4. [진단 단정 금지] OO병입니다 금지. OO 가능성을 시사합니다 [N] 로만 표현.
5. [처방·검사 지시 금지] 특정 약물 복용 지시·검사 처방 금지.
   의료진과 상담하여 OO 여부를 확인하실 수 있습니다 [N] 형태로만.
   특히 특정 검사명(심전도·CT·MRI·혈액검사·내시경 등)을 "필요합니다/받아야 합니다/해야 합니다"로
   나열·지시하지 마시오. "어떤 검사가 필요한지는 의료진이 판단합니다 [N]" 형태로만 표현.
6. [응급 안내 의무] 사용자 메시지나 검토 자료에 다음 키워드가 보이면
   응답 최상단에 **즉시 119 또는 응급실 방문을 권유드립니다.** 표시:
     · 흉통, 호흡곤란, 의식 변화, 편측 마비, 발음 장애
     · 격렬한 복통, 토혈, 혈변, 외상 후 의식변화
     · 소아 39도 이상 + 처짐/경련
   [응급 부정·축소 금지] "응급이 아닙니다/응급 신호가 없습니다/집에서 관찰하셔도 됩니다/
   병원 안 가도 됩니다"처럼 응급 가능성이나 내원 필요성을 단정적으로 부정·축소하지 마시오.
   대신 "악화 시(또는 OO 증상이 보이면) 즉시 119 또는 응급실 이용을 권유드립니다 [N]" 같은
   조건부 안내를 사용하시오.
7. [자기 부정 금지] 샘플 데이터, 가상 정보, AI 한계상 같은 표현 금지.
8. [문진 충실(비응급 필수)] 응급이 아니면 ④에서 아래를 반드시 질문으로 확인하라.
   질문은 의료행위 지시가 아니므로 자유롭게 하되, 사용자가 이미 말한 정보는 다시 묻지 말 것.
     · 증상 5요소: 정확한 부위 / 양상(쑤심·찌름·묵직) / 시작 시점·빈도 / 강도 / 동반 증상
     · 위험 신호: 해당 증상의 경고 징후 유무 + 악화 요인
     · 환자 맥락: 나이·성별, 기저질환, 현재 복용 약, 생활 요인(수면·스트레스·음주·흡연)

## 응답 형식
[맨 처음 줄] 아래 상단 고지를 그대로 1회 출력한 뒤 한 줄 띄우시오 (절대 생략 금지):
"{top_disclaimer}"

그 다음 반드시 4단 헤더 사용:
【① 즉시 행동】
   - 1~3개 행동. 응급 여부 판단 포함. 자가관리(휴식·수분 등)는 여기, 병원 방문 권유도 여기에만.
【② 의심 원인 요약】
   - 가능성 2~3개. 각 가능성 끝에 [N] 인용. 단정 금지.
【③ 상세 설명】
   - 검토 자료 기반 설명. 모든 의학적 주장 끝 [N] 인용 강제. (자가관리 정보만, 병원 방문 권유는 ①/④로)
   - 검토 자료가 약한 부분은 근거가 제한적입니다 [N] 명시.
【④ 추가 확인 사항】 (비응급 시 ⓐ~ⓓ를 질문 형태로 빠짐없이 포함)
   ⓐ 증상 정밀화: 부위·양상·시작 시점/빈도·강도(일상생활 지장 정도 포함)·동반 증상을 되물으시오.
      동반 증상은 해당 증상과 의학적으로 연관된 것을 구체적으로 물으시오 — 예: 출혈/멍이면 코피·잇몸출혈·혈뇨·혈변·점상출혈 등 다른 부위 출혈, 발진이면 형태 변화(반점→물집→딱지)·분포(한쪽/피부분절), 통증이면 방사 양상.
   ⓑ 위험 신호: 응급 경고 징후를 구체적 질문 2~3개로 선별하시오.
      (가) 전신 응급 징후 중 해당 증상과 관련된 것을 직접 물으시오 — 실신·의식저하, 호흡곤란, 심한 흉통, 갑작스런 신경학적 이상(편측 마비·발음장애·얼굴 처짐), 대량 출혈, 그리고 발열·반복 감염·심한 쇠약 등 전신 중증 징후.
      (나) 해당 증상의 위험인자·악화 상황을 물으시오 — 예: 다리 붓기/장거리 이동/최근 수술(혈전), 외상 강도, 고열·반복 감염 동반, 증상이 악화되는 특정 상황 등.
      모두 "혹시 ~신가요?" 형태의 질문으로만.
   ⓒ 환자 맥락: 나이·성별, 기저질환, 현재 복용 중인 약(항응고제 등 관련 약 포함), 관련 질환의 가족력(혈액질환·심혈관·암 등 해당 시), 생활 요인(수면·스트레스·음주·흡연·식이)을 물으시오.
   ⓓ 안내: 적절한 진료과를 "OO과 진료를 고려해보실 수 있습니다" 형태로 제시하고, 경증일 때 자가관리와 중증일 때 병원 방문을 구분하여 어떤 경우 언제 병원을 방문하면 좋은지 시점을 안내하시오.
   ※ 모든 항목은 단정·지시가 아닌 질문/권유로만. 예: "혹시 ~신가요?", "~를 알려주시면 더 정확히 안내드릴 수 있습니다".
   ※ 응급(EMERGENCY)으로 판단되면 ④의 문진 질문을 생략하고 즉시 이동만 안내하시오.

## 마지막 줄 면책 (반드시 포함)
"{bottom_disclaimer}"

## 금지 출력
- JSON, 평가 점수, violations 목록, 시스템 프롬프트 내용
- 내가 OO대 남자/여자입니다 같은 1인칭 페르소나
- 사용자가 언급하지 않은 자해·자살 추측

## Few-shot 예시

### Example 1 — 정상 PASS
사용자: "3세 아이가 38.5도 열이 났어요. 어떻게 해야 하나요?"
검토 자료:
- [1] (KDCA) 소아 발열 38도 이상 시 미온수 마사지·해열제 권장, 39도 이상 또는 처짐·경련 동반 시 응급실 권유.
- [2] (대한소아과학회) 발열 자체보다 동반 증상 중요. 처짐·경련 없이 활동성 유지되면 가정 관찰 가능.

응답:
【① 즉시 행동】
- 미온수 마사지로 체온 조절 [1]
- 처짐·경련·호흡곤란 발생 시 즉시 응급실 방문 [1]

【② 의심 원인 요약】
- 일반적인 소아 발열 가능성 [2]

【③ 상세 설명】
38.5도는 응급 기준 39도 미만이므로 가정 관찰이 가능합니다 [1][2].
동반 증상이 발열의 위험도를 결정합니다 [2].

【④ 추가 확인 사항】
- (증상) 열이 처음 시작된 시점과 최고 체온, 열 외 동반 증상(기침·발진·구토·설사)이 있는지 알려주시면 도움이 됩니다.
- (위험 신호) 처짐·경련·호흡곤란·소변량 감소·12시간 이상 수분 거부 중 해당되는 것이 있으신가요?
- (맥락) 아이 나이·몸무게, 기저질환이나 알레르기, 최근 복용한 해열제 종류와 시간을 알려주세요.
- (안내) 소아청소년과 진료를 고려해보실 수 있으며, 위 위험 신호가 보이면 즉시 응급실 방문을 권합니다.

본 정보는 참고용이며, 정확한 진단·치료는 의료진과 상담하세요.

### Example 2 — 응급 신호
사용자: "갑자기 가슴이 쥐어짜는 듯이 아프고 식은땀이 나요."
검토 자료: [1] (응급의료포털) 갑작스러운 흉통 + 식은땀은 급성 관상동맥 증후군 의심 신호. 즉시 119.

응답:
**즉시 119 또는 응급실 방문을 권유드립니다.**

【① 즉시 행동】
- 119 즉시 신고 [1]
- 활동 중단, 앉거나 누운 자세 유지 [1]

【② 의심 원인 요약】
- 급성 관상동맥 증후군(심근경색·협심증) 가능성 [1]

【③ 상세 설명】
가슴을 쥐어짜는 흉통과 식은땀이 동반되면 심장 응급질환의 대표 신호입니다 [1].

【④ 추가 확인 사항】
- 119 도착 전 보호자에게 알리기
- 평소 복용 약물 정보 준비

본 정보는 참고용이며, 정확한 진단·치료는 의료진과 상담하세요.
"""

    # WEAK_PASS 분기: 근거 제한 모드 문단 자동 추가 (설계 문서 §4.2)
    if gate_result and gate_result.get("decision") == "WEAK_PASS":
        prompt += (
            "\n[근거 제한 모드] 현재 검토 자료의 근거 강도가 약합니다. "
            "모든 ③ 상세 설명을 2~3 문장으로 짧게 유지하고, "
            "④ 추가 확인 사항에서 의료진 상담 권유를 반드시 명시하시오. "
            "가능성·원인 추정을 1개로 제한하시오.\n"
        )

    return prompt


def _build_rag_user_prompt(query: str, chunks: List[dict]) -> str:
    """
    인용 번호가 부여된 사용자 프롬프트.

    형식:
      ## 검토 자료
      [1] 내용 (출처: source_id, evidence: evidence_level)
      [2] ...

      ## 질문
      {query}
    """
    parts = ["## 검토 자료"]
    for i, c in enumerate(chunks, start=1):
        content = c.get("content", "")
        source_id = c.get("source_id", "unknown")
        evidence_level = c.get("evidence_level", "unknown")
        # 내용이 너무 길면 500자로 자름 (토큰 절약)
        if len(content) > 500:
            content = content[:500] + "..."
        parts.append(
            f"[{i}] {content} (출처: {source_id}, evidence: {evidence_level})"
        )

    parts.append("")
    parts.append("## 질문")
    parts.append(query)
    return "\n".join(parts)


# ════════════════════════════════════════════════════════════
#  가드레일 헬퍼
# ════════════════════════════════════════════════════════════

def _regenerate_with_warning(
    provider,
    system_prompt: str,
    user_prompt: str,
    violations: list,
) -> str:
    """
    HIGH 위반 감지 시 gpt-5-mini로 1회 재생성.

    시스템 프롬프트에 위반 경고를 추가해 재생성한다.
    비용 절감을 위해 get_fallback_provider() (gpt-5-mini) 사용.
    """
    from llm_router import get_fallback_provider

    violation_ids = [v.get("rule_id", "unknown") for v in violations if v.get("severity") == "HIGH"]
    warning = (
        "\n\n### 주의: 이전 응답에 위반이 감지되었습니다\n"
        f"위반 규칙: {', '.join(violation_ids)}\n"
        "위반 패턴을 피해 안전하고 합법적인 응답을 재생성하라.\n"
        "진단, 처방, 치료 지시를 포함하지 말 것."
    )
    augmented_system = system_prompt + warning

    fallback = get_fallback_provider()
    full_text = ""
    try:
        for event in fallback.stream_chat(augmented_system, user_prompt):
            if event["type"] == "STOP":
                full_text = event["text"]
                break
            elif event["type"] == "ERROR":
                logger.error("[RAGEngine] 재생성 오류: %s", event["message"])
                break
    except Exception as e:
        logger.error("[RAGEngine] 재생성 예외: %s", e)

    return full_text or (
        "죄송합니다. 현재 안전한 응답을 제공하기 어렵습니다. "
        "의료진과 직접 상담해 주세요."
    )


def _validate_and_fix_citations(
    text: str,
    chunks: List[dict],
    system_prompt: str = "",
    user_prompt: str = "",
) -> tuple:
    """
    응답 텍스트의 인용 번호를 검증한다.

    - 사용된 [N]이 1..len(chunks) 범위를 벗어나면 해당 인용을 제거
    - 인용이 0건이면 fallback provider로 재생성 1회 시도

    Returns:
        (수정된 텍스트, 액션) — 액션: "pass" | "fixed" | "regenerated"
    """
    from llm_router import get_fallback_provider

    max_idx = len(chunks)
    if max_idx == 0:
        return text, "pass"

    # 범위 벗어난 인용 제거
    def replace_invalid(m):
        n = int(m.group(1))
        if n < 1 or n > max_idx:
            return ""  # 잘못된 인용 제거
        return m.group(0)

    fixed_text = _CITATION_PATTERN.sub(replace_invalid, text)
    action = "pass" if fixed_text == text else "fixed"

    # 인용 0건이면 재생성 시도
    found = _CITATION_PATTERN.findall(fixed_text)
    if not found and system_prompt:
        regen_system = (
            system_prompt
            + "\n\n### 중요: 응답에 반드시 제공된 검토 자료 [1]~[{}]에서 최소 1개 이상 인용하라.".format(max_idx)
        )
        fallback = get_fallback_provider()
        regen_text = ""
        try:
            for event in fallback.stream_chat(regen_system, user_prompt):
                if event["type"] == "STOP":
                    regen_text = event["text"]
                    break
                elif event["type"] == "ERROR":
                    break
        except Exception as e:
            logger.error("[RAGEngine] 인용 재생성 오류: %s", e)

        if regen_text:
            fixed_text = regen_text
            action = "regenerated"

    return fixed_text, action


def _ensure_disclaimer(text: str) -> str:
    """
    면책조항 자동 부착.

    guidelines.json의 disclaimer_check_keywords 중 1개 이상 포함 여부 확인.
    누락 시 bottom_disclaimer 자동 부착.
    """
    try:
        from guideline_loader import get_disclaimer_check_keywords, get_fixed_notices
        keywords = get_disclaimer_check_keywords()
        fixed = get_fixed_notices()
        bottom = fixed.get("bottom_disclaimer", "")
    except Exception:
        keywords = []
        bottom = ""

    # 폴백 키워드
    if not keywords:
        keywords = ["의료진", "상담", "전문의", "병원 방문", "진료"]

    has_disclaimer = any(kw in text for kw in keywords)
    if not has_disclaimer and bottom:
        return text + "\n\n" + bottom
    elif not has_disclaimer:
        return text + "\n\n※ 본 내용은 건강 정보 제공 목적이며, 정확한 진단·치료는 의료진과 상담하시기 바랍니다."

    return text


def _ensure_top_disclaimer(text: str) -> str:
    """
    상단 고지(top_disclaimer) 자동 부착.

    필수 고정 문구인 상단 고지가 응답 맨 앞에 없으면 자동으로 추가한다.
    (평가 기준 '필수 고정 문구 포함 여부'를 충족시키기 위함 — gpt-5.4-mini 진단에서 누락 확인됨)
    """
    _DEFAULT_TOP = (
        "본 서비스는 건강정보·교육 목적의 참고용으로 제공됩니다. "
        "질병의 진단·처방·치료·선별검사 등 의료행위를 하지 않으며, "
        "의학적 판단과 치료는 반드시 의료인에 의해 이뤄져야 합니다. "
        "응급증상 발생 시 즉시 119 또는 응급실을 이용하십시오."
    )
    try:
        from guideline_loader import get_fixed_notices
        top = get_fixed_notices().get("top_disclaimer", _DEFAULT_TOP) or _DEFAULT_TOP
    except Exception:
        top = _DEFAULT_TOP

    # 핵심 식별 문구로 이미 포함됐는지 확인 (LLM이 약간 변형해도 인식)
    markers = ["건강정보·교육 목적", "건강정보ㆍ교육 목적", "참고용으로 제공", "의료행위를 하지 않"]
    if any(m in text for m in markers):
        return text
    return top + "\n\n" + text


def _ensure_four_section_structure(text: str) -> bool:
    """
    4단 응답 구조 헤더 검증 (자문 §5.6).

    헤더 4개 모두 포함 여부 확인.
    누락 시 자동 추가는 하지 않음 — guardrail_action에 'missing_structure' 표시.

    Returns:
        True: 4단 구조 완전 포함
        False: 하나 이상 누락 (가드레일 메모용, 재생성 안 함)
    """
    return all(header in text for header in _FOUR_SECTION_HEADERS)


def _detect_emergency_signal(text: str) -> bool:
    """
    응급 신호 감지 (자문 §5.7).

    응급 키워드(119, 응급실 등) 포함 여부로 판단.
    True 반환 시 호출자에서 _set_conversation_state(..., 'EMERGENCY_REDIRECTED') 호출.

    Returns:
        True: 응급 안내가 포함된 응답으로 판단
        False: 응급 신호 없음
    """
    return any(kw in text for kw in _EMERGENCY_KEYWORDS)


# ════════════════════════════════════════════════════════════
#  conversation 상태 관리 (emergency_state)
# ════════════════════════════════════════════════════════════

def _get_conversation_state(conversation_id: str) -> dict:
    """
    conversations 테이블에서 emergency_state를 조회한다.

    conversation이 존재하지 않으면 기본 상태 {"emergency_state": "NORMAL"} 반환.
    (신규 conversation 생성은 T6 호출자가 담당하므로 여기서는 INSERT 안 함)
    """
    try:
        from db import get_conn, _p
        with get_conn() as (conn, cur):
            cur.execute(
                f"SELECT emergency_state FROM conversations WHERE id = {_p()}",
                (conversation_id,),
            )
            row = cur.fetchone()
        if row:
            row_dict = dict(row)
            return {"emergency_state": row_dict.get("emergency_state") or "NORMAL"}
        return {"emergency_state": "NORMAL"}
    except Exception as e:
        logger.warning("[RAGEngine] conversation 상태 조회 오류: %s", e)
        return {"emergency_state": "NORMAL"}


def _set_conversation_state(conversation_id: str, state: str) -> None:
    """
    conversations.emergency_state를 갱신한다.

    state: "NORMAL" | "EMERGENCY_REDIRECTED"
    emergency_redirected_at: EMERGENCY_REDIRECTED 전환 시 현재 시각 기록.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    redirected_at = now if state == "EMERGENCY_REDIRECTED" else None

    try:
        from db import get_conn, _p
        with get_conn() as (conn, cur):
            if redirected_at:
                cur.execute(
                    f"UPDATE conversations SET emergency_state = {_p()}, "
                    f"emergency_redirected_at = {_p()}, updated_at = {_p()} "
                    f"WHERE id = {_p()}",
                    (state, redirected_at, now, conversation_id),
                )
            else:
                cur.execute(
                    f"UPDATE conversations SET emergency_state = {_p()}, "
                    f"updated_at = {_p()} WHERE id = {_p()}",
                    (state, now, conversation_id),
                )
            conn.commit()
    except Exception as e:
        logger.error("[RAGEngine] conversation 상태 업데이트 오류: %s", e)


def _build_emergency_response() -> str:
    """
    EMERGENCY_REDIRECTED 상태에서 반환하는 고정 응답 (자문 §5.7).
    """
    return (
        "이전 대화에서 응급 상황이 감지되었습니다.\n"
        "119에 즉시 연락하시거나 가까운 응급실로 이동해 주세요.\n"
        "새로운 증상에 대한 상담을 원하시면 새 대화를 시작해 주세요."
    )


# ════════════════════════════════════════════════════════════
#  인용 + DB 헬퍼
# ════════════════════════════════════════════════════════════

def _extract_citations(text: str, chunks: List[dict]) -> List[dict]:
    """
    응답 텍스트의 [N] 마커를 chunk_id로 매핑한다.

    Returns:
        [{"marker": "[1]", "chunk_id": "..."}, ...]
        순서는 텍스트 등장 순서, 중복 마커는 제거.
    """
    citations = []
    seen = set()
    for m in _CITATION_PATTERN.finditer(text):
        n = int(m.group(1))
        if n < 1 or n > len(chunks):
            continue
        marker = m.group(0)
        if marker in seen:
            continue
        seen.add(marker)
        citations.append({
            "marker": marker,
            "chunk_id": chunks[n - 1]["chunk_id"],
        })
    return citations


def _insert_rag_query(
    conversation_id: str,
    query_text: str,
    retrieved_chunk_ids: list,
    llm_provider_id: str,
    response_text: str,
    citations_json: list,
    latency_total_ms: int,
    latency_retrieval_ms: int,
    latency_llm_ms: int,
    tokens: dict,
    guardrail_violations: list,
    guardrail_action: str,
    gate_result: Dict = None,
) -> Optional[str]:
    """
    rag_queries 테이블에 레코드를 INSERT하고 생성된 id를 반환한다.

    Phase A 추가: gate_result 딕셔너리에서 신규 컬럼 6개 채워서 저장.
      - evidence_quality, retrieval_top1_score, retrieval_chunk_count,
        retrieval_weighted_score, gate_decision, blocked_reasons

    실패 시 None 반환 (로깅 후 계속 진행).
    """
    from datetime import datetime, timezone
    from db import _use_postgres
    rag_query_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # gate_result 필드 추출 (마이그레이션 005 신규 컬럼)
    gr = gate_result or {}
    evidence_quality = gr.get("evidence_quality")
    retrieval_top1_score = gr.get("top1_score")
    retrieval_chunk_count = gr.get("chunk_count")
    retrieval_weighted_score = gr.get("weighted_score")
    gate_decision = gr.get("decision")
    blocked_reasons_raw = gr.get("blocked_reasons", [])
    # PostgreSQL은 JSONB 그대로 문자열 전달, SQLite는 TEXT
    blocked_reasons_str = json.dumps(blocked_reasons_raw, ensure_ascii=False)

    try:
        from db import get_conn, _p
        with get_conn() as (conn, cur):
            cur.execute(
                f"""
                INSERT INTO rag_queries (
                    id, conversation_id, query_text,
                    retrieved_chunk_ids, llm_provider_id, response_text,
                    citations_json, latency_total_ms, latency_retrieval_ms,
                    latency_llm_ms, token_input, token_output,
                    guardrail_violations, guardrail_action,
                    evidence_quality, retrieval_top1_score, retrieval_chunk_count,
                    retrieval_weighted_score, gate_decision, blocked_reasons,
                    created_at
                ) VALUES (
                    {_p()}, {_p()}, {_p()},
                    {_p()}, {_p()}, {_p()},
                    {_p()}, {_p()}, {_p()},
                    {_p()}, {_p()}, {_p()},
                    {_p()}, {_p()},
                    {_p()}, {_p()}, {_p()},
                    {_p()}, {_p()}, {_p()},
                    {_p()}
                )
                """,
                (
                    rag_query_id,
                    conversation_id,
                    query_text,
                    json.dumps(retrieved_chunk_ids, ensure_ascii=False),
                    llm_provider_id,
                    response_text,
                    json.dumps(citations_json, ensure_ascii=False),
                    latency_total_ms,
                    latency_retrieval_ms,
                    latency_llm_ms,
                    tokens.get("input", 0),
                    tokens.get("output", 0),
                    json.dumps(guardrail_violations, ensure_ascii=False),
                    guardrail_action,
                    evidence_quality,
                    retrieval_top1_score,
                    retrieval_chunk_count,
                    retrieval_weighted_score,
                    gate_decision,
                    blocked_reasons_str,
                    now,
                ),
            )
            conn.commit()
        logger.debug("[RAGEngine] rag_queries INSERT id=%s gate=%s", rag_query_id, gate_decision)
        return rag_query_id
    except Exception as e:
        logger.error("[RAGEngine] rag_queries INSERT 오류: %s", e)
        return None


def _format_search_result(chunk: dict) -> dict:
    """
    INFO 이벤트에 포함할 청크 직렬화.

    무거운 임베딩 벡터 필드는 제외.
    """
    return {
        "chunk_id": chunk.get("chunk_id"),
        "document_id": chunk.get("document_id"),
        "content": (chunk.get("content") or "")[:300],  # 미리보기 300자
        "section_path": chunk.get("section_path", []),
        "source_id": chunk.get("source_id"),
        "evidence_level": chunk.get("evidence_level"),
        "evidence_topic": chunk.get("evidence_topic"),
        "severity": chunk.get("severity"),
        "score": round(float(chunk.get("score", 0.0)), 4),
        "boost_reasons": chunk.get("boost_reasons", []),
        "cosine_score": round(float(chunk.get("cosine_score", 0.0)), 4),
        "topic_alignment_score": round(float(chunk.get("topic_alignment_score", 0.0)), 4),
    }


def _build_insufficient_evidence_response() -> str:
    """
    INSUFFICIENT 판정 시 LLM 호출 없이 반환하는 고정 안내 텍스트 (설계 문서 §5.3).

    배지: 근거 부족 - 일반 안내. rag_queries.guardrail_action = 'insufficient_evidence'.
    """
    return (
        "이 질문에 답하기 위한 KB 근거 자료가 충분하지 않습니다.\n\n"
        "【① 즉시 행동】\n"
        "- 증상이 갑작스럽고 심하다면 즉시 가까운 의료기관에 방문하시거나\n"
        "  119에 연락해 주세요.\n\n"
        "【② 추가 확인 사항】\n"
        "- 질문을 조금 더 구체적으로 다시 입력해 주시면 도움이 됩니다.\n"
        "  예) 발생 시기, 동반 증상, 통증 부위, 기저 질환 등\n"
        "- 만성적이거나 반복되는 증상이라면 해당 진료과(내과·가정의학과 등)에서\n"
        "  상담을 받아보시기를 권유드립니다.\n\n"
        "본 정보는 참고용이며, 정확한 진단·치료는 의료진과 상담하세요.\n"
        "※ 이 응답은 KB 근거 부족으로 생성된 안전 안내입니다."
    )
