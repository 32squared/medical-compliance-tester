"""
Retrieval Router — 질문 intent별 소스 라우팅 (작업지시서 §5.2 / EPIC B-2).

분류 결과(intent)에 따라 검색할 출처와 우선순위를 결정한다.
순수 로직 — LLM/DB 없이 로컬 테스트 가능.

핵심 규칙 (스펙 §5.2):
- infection      → KDCA 우선, WHO/CDC 보조
- vaccination    → KDCA/NIP 우선, CDC/WHO 보조
- drug_safety    → MFDS_DUR/HIRA_DUR/허가사항 우선, PubMed 제한적
- lab_interpretation → 국내 지침/학회 우선
- general_health → 국내 공공자료/지침 우선
- symptom_info   → 국내 지침/공공 우선
- emergency      → red-flag 정책 우선, 안전 안내가 검색보다 우선
- diagnosis_request   → 진단 불가, 일반 정보 + 의료진 상담
- prescription_request→ 처방 불가, 약물 일반정보 + 의사/약사 상담
"""

from __future__ import annotations

from typing import Dict, List

# source_id ↔ priority_rank (작업지시서 §3.1, 낮을수록 우선)
SOURCE_PRIORITY = {
    "LEGAL_POLICY": 1, "KDCA": 1, "MFDS_DUR": 1, "HIRA_DUR": 1,
    "KR_GUIDELINE": 2, "NIP": 2,
    "WHO": 3, "CDC": 3, "NICE": 3, "USPSTF": 3,
    "DAILYMED": 4,
    "COCHRANE": 5,
    "PUBMED": 6, "PMC_OA": 6,
}

# 현 KB의 실제 source_id 매핑 (라우트 라벨 → kb_sources.source_id 후보)
ROUTE_TO_KB_SOURCE = {
    "KDCA": ["kdca", "kdca_api", "health_kdca"],
    "MFDS_DUR": ["mfds", "mfds_dur"],
    "HIRA_DUR": ["hira", "hira_dur"],
    "KR_GUIDELINE": ["guideline", "kmle"],
    "NEMC": ["nemc"],
    "PUBMED": ["pubmed"],
    "PMC_OA": ["pmc_oa"],
}

_ROUTING_TABLE = {
    "infection":          {"primary": ["KDCA"], "secondary": ["WHO", "CDC"], "allow_papers": True},
    "vaccination":        {"primary": ["KDCA", "NIP"], "secondary": ["CDC", "WHO"], "allow_papers": False},
    "drug_safety":        {"primary": ["MFDS_DUR", "HIRA_DUR"], "secondary": ["DAILYMED", "KR_GUIDELINE"], "allow_papers": False},
    "lab_interpretation": {"primary": ["KR_GUIDELINE"], "secondary": ["NICE"], "allow_papers": True},
    "general_health":     {"primary": ["KR_GUIDELINE", "KDCA"], "secondary": ["NICE", "WHO"], "allow_papers": True},
    "symptom_info":       {"primary": ["KR_GUIDELINE", "KDCA"], "secondary": ["NICE", "CDC"], "allow_papers": True},
    "emergency":          {"primary": ["KR_GUIDELINE", "KDCA"], "secondary": [], "allow_papers": False},
    "diagnosis_request":  {"primary": ["KR_GUIDELINE"], "secondary": [], "allow_papers": False},
    "prescription_request": {"primary": ["MFDS_DUR", "HIRA_DUR"], "secondary": ["KR_GUIDELINE"], "allow_papers": False},
    "mental_health_crisis": {"primary": ["LEGAL_POLICY", "KR_GUIDELINE"], "secondary": [], "allow_papers": False},
    "legal_privacy":      {"primary": ["LEGAL_POLICY"], "secondary": [], "allow_papers": False},
    "unknown":            {"primary": ["KR_GUIDELINE", "KDCA"], "secondary": ["WHO"], "allow_papers": True},
}

# 검색보다 안전 안내가 우선인 intent (스펙: emergency/crisis는 근거검색보다 안전 우선)
_SAFETY_FIRST = {"emergency", "mental_health_crisis"}


def route(classification: Dict) -> Dict:
    """
    분류 결과 → 검색 라우팅 계획.

    Returns:
    {
      "intent": str,
      "primary_sources": [...],     # 라우트 라벨
      "secondary_sources": [...],
      "allow_papers": bool,
      "kb_source_ids": [...],       # 현 KB source_id 후보 (메타 필터용)
      "ranked_routes": [...],       # priority_rank 오름차순 정렬
      "safety_first": bool,         # True면 안전 안내 우선, 검색은 보조
      "retrieval_enabled": bool,    # crisis는 검색 스킵 가능
    }
    """
    intent = (classification or {}).get("intent", "unknown")
    if intent not in _ROUTING_TABLE:
        intent = "unknown"

    # 분류기가 retrieval_routes를 명시했으면 그것을 1차로 존중
    explicit = (classification or {}).get("retrieval_routes") or []
    table = _ROUTING_TABLE[intent]
    primary = list(dict.fromkeys(explicit + table["primary"])) if explicit else list(table["primary"])
    secondary = list(table["secondary"])

    all_routes = primary + [s for s in secondary if s not in primary]
    ranked = sorted(all_routes, key=lambda r: SOURCE_PRIORITY.get(r, 9))

    kb_ids: List[str] = []
    for r in ranked:
        kb_ids.extend(ROUTE_TO_KB_SOURCE.get(r, []))
    kb_ids = list(dict.fromkeys(kb_ids))

    return {
        "intent": intent,
        "primary_sources": primary,
        "secondary_sources": secondary,
        "allow_papers": table["allow_papers"],
        "kb_source_ids": kb_ids,
        "ranked_routes": ranked,
        "safety_first": intent in _SAFETY_FIRST,
        # crisis는 검색을 스킵하고 위기 안내 우선 / emergency는 검색은 하되 안전 우선
        "retrieval_enabled": intent != "mental_health_crisis",
    }


def source_priority_for(source_id: str) -> int:
    """kb_sources.source_id → priority_rank (reranker 가중용, 낮을수록 우선)."""
    sid = (source_id or "").lower()
    for route_label, kb_ids in ROUTE_TO_KB_SOURCE.items():
        if sid in kb_ids:
            return SOURCE_PRIORITY.get(route_label, 6)
    return 6  # 기본: 논문 수준
