"""
Evidence Pack Builder — 정식 Evidence Pack JSON 생성 (작업지시서 §6 / EPIC B-3).

검색된 청크 + 분류 결과 → LLM에 제공할 Evidence Pack을 구성한다.
LLM은 이 Evidence Pack의 근거만 사용해야 한다 (P1/P2).

순수 로직 — DB/LLM 없이 청크 dict 리스트만으로 동작·테스트 가능.

스펙 §6.2 생성 규칙:
- E1. source_priority 높은(=rank 낮은) 출처 우선
- E2. KR 출처 우선
- E3. 약물 질문은 MFDS/DUR/HIRA를 PubMed보다 우선
- E4. 지침 > 논문
- E6. 질문에 직접 답하지 않으면 제외 (호출 측에서 relevance 필터)
- E8. 근거 부족(0개) → answer_mode=insufficient_information
"""

from __future__ import annotations

import hashlib
from typing import Dict, List

from retrieval_router import source_priority_for

# evidence 최종 개수 (스펙 §5.4: 4~8개)
_MIN_EVIDENCE = 1
_MAX_EVIDENCE = 8


def _qid(question: str) -> str:
    h = hashlib.sha1((question or "").encode("utf-8")).hexdigest()[:10]
    return f"q_{h}"


def _answer_constraints(classification: Dict) -> Dict:
    risk = (classification or {}).get("risk_level", "medium")
    high = risk in ("high", "very_high", "crisis")
    return {
        "must_cite_every_medical_claim": True,
        "must_not_diagnose": True,
        "must_not_prescribe": True,
        "must_not_reassure_emergency": True,
        "must_include_clinician_consult_when_high_risk": high,
        "max_answer_tokens": 1200,
    }


def build_evidence_pack(
    question: str,
    classification: Dict,
    chunks: List[Dict],
    retrieved_at: str = "",
) -> Dict:
    """
    검색 청크 → Evidence Pack JSON (스펙 §6.1).

    chunks 항목 기대 필드(있는 것만 사용, 없으면 안전 기본값):
      chunk_id, source_id, content/snippet, title/document_title,
      evidence_level, published_at, revised_at, url, score
    """
    classification = classification or {}
    items: List[Dict] = []

    # source_priority 오름차순(우선) → score 내림차순 정렬
    def _sort_key(c: Dict):
        sp = c.get("source_priority")
        if sp is None:
            sp = source_priority_for(c.get("source_id", ""))
        return (sp, -float(c.get("score") or c.get("cosine_score") or 0.0))

    ranked = sorted(chunks or [], key=_sort_key)[:_MAX_EVIDENCE]

    for i, c in enumerate(ranked, start=1):
        sp = c.get("source_priority")
        if sp is None:
            sp = source_priority_for(c.get("source_id", ""))
        snippet = (c.get("snippet") or c.get("content") or "").strip()
        if len(snippet) > 600:
            snippet = snippet[:600] + "..."
        limitations: List[str] = []
        # 약물/임신/소아/응급은 limitation 필수 (스펙 §7.5 규칙3)
        pop = classification.get("population_tags", [])
        if classification.get("intent") == "drug_safety" or "pregnancy" in pop or "child" in pop:
            limitations.append("개인별 복용·적용 가능 여부는 단정할 수 없으며 의료진·약사 확인이 필요합니다.")
        # 해외/오래된 근거 표시 (스펙 §7.5 규칙4)
        juris = c.get("jurisdiction", "KR")
        if juris and juris != "KR":
            limitations.append(f"해외({juris}) 근거로 국내 기준과 다를 수 있습니다.")

        items.append({
            "evidence_id": f"E{i}",
            "chunk_id": c.get("chunk_id", ""),
            "source_id": c.get("source_id", ""),
            "source_name": c.get("source_name") or c.get("source_id", ""),
            "source_type": c.get("source_type", ""),
            "institution": c.get("institution", ""),
            "jurisdiction": juris or "KR",
            "source_priority": sp,
            "document_title": c.get("document_title") or c.get("title", ""),
            "published_at": c.get("published_at"),
            "revised_at": c.get("revised_at"),
            "retrieved_at": retrieved_at,
            "url": c.get("url"),
            "snippet": snippet,
            "supported_claims": c.get("supported_claims", []),
            "limitations": limitations,
            "confidence": round(float(c.get("score") or c.get("cosine_score") or 0.0), 3),
        })

    insufficient = len(items) < _MIN_EVIDENCE
    return {
        "question_id": _qid(question),
        "user_question": question,
        "classification": {
            "intent": classification.get("intent", "unknown"),
            "risk_level": classification.get("risk_level", "medium"),
            "jurisdiction": classification.get("jurisdiction", "KR"),
            "population_tags": classification.get("population_tags", []),
            "allowed_response_mode": (
                "insufficient_information" if insufficient
                else classification.get("allowed_response_mode", "cautious_answer")
            ),
        },
        "evidence_items": items,
        "conflicts": _detect_conflicts(items),
        "insufficient_evidence": insufficient,
        "answer_constraints": _answer_constraints(classification),
    }


def _detect_conflicts(items: List[Dict]) -> List[Dict]:
    """국내 vs 해외 출처 혼재 시 충돌 메모 (스펙 E4: 지침/국내 우선)."""
    jurisdictions = {it.get("jurisdiction", "KR") for it in items}
    if "KR" in jurisdictions and any(j not in ("KR", "", None) for j in jurisdictions):
        return [{
            "description": "국내 출처와 해외 출처가 함께 검색됨. 국내 공식 기준을 우선 적용.",
            "resolution_policy": "KR_official_source_first",
        }]
    return []


def render_evidence_for_prompt(pack: Dict) -> str:
    """Evidence Pack → LLM 사용자 프롬프트용 텍스트 ([E1] 인용 형식)."""
    lines = ["## 검토 자료 (Evidence Pack — 이 근거만 사용)"]
    for it in pack.get("evidence_items", []):
        meta = f"출처: {it['source_name']}"
        if it.get("jurisdiction"):
            meta += f", {it['jurisdiction']}"
        if it.get("revised_at") or it.get("published_at"):
            meta += f", 개정/발행: {it.get('revised_at') or it.get('published_at')}"
        lines.append(f"[{it['evidence_id']}] {it['snippet']} ({meta})")
        for lim in it.get("limitations", []):
            lines.append(f"    · 한계: {lim}")
    if pack.get("insufficient_evidence"):
        lines.append("(확인된 근거가 부족합니다 — 근거 부족을 명시하고 단정하지 마시오.)")
    return "\n".join(lines)
