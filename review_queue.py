"""
Review Queue — 고위험 답변 검수 큐 (작업지시서 §13 EPIC E-2 / §11).

고위험·안전 플래그가 있는 답변을 의사/약사/법무 검수 큐에 자동 적재할지 결정한다.
결정 로직은 순수 함수(로컬 테스트 가능). DB 적재는 db 모듈 통해 수행(가드).
"""

from __future__ import annotations

from typing import Dict, List, Optional

# 검수 큐 자동 적재 트리거
_HIGH_RISK_LEVELS = {"high", "very_high", "crisis"}
_HIGH_RISK_INTENTS = {
    "drug_safety", "diagnosis_request", "prescription_request",
    "emergency", "mental_health_crisis", "lab_interpretation",
}


def should_review(
    classification: Optional[Dict] = None,
    citation_result: Optional[Dict] = None,
    safety_result: Optional[Dict] = None,
) -> Dict:
    """
    답변을 검수 큐에 넣을지 결정.

    Returns:
    {"needs_review": bool, "priority": "low|medium|high", "reasons": [...], "assignee_role": "doctor|pharmacist|legal|none"}
    """
    reasons: List[str] = []
    classification = classification or {}
    citation_result = citation_result or {}
    safety_result = safety_result or {}

    intent = classification.get("intent", "unknown")
    risk = classification.get("risk_level", "low")

    if risk in _HIGH_RISK_LEVELS:
        reasons.append(f"risk_level={risk}")
    if intent in _HIGH_RISK_INTENTS:
        reasons.append(f"intent={intent}")
    if classification.get("medical_law_risk"):
        reasons.append("medical_law_risk")

    # 인용 검증 실패 / 커버리지 부족
    if citation_result.get("overall_pass") is False:
        reasons.append("citation_verify_fail")
    cov = citation_result.get("citation_coverage")
    if cov is not None and cov < 0.95:
        reasons.append(f"low_citation_coverage={cov}")

    # 안전 후처리 위험 플래그
    if safety_result.get("safe_to_send") is False:
        reasons.append("safety_block")
    for f in safety_result.get("risk_flags", []) or []:
        reasons.append(f"safety_flag:{f}")

    needs = bool(reasons)

    # 검수자 배정
    if intent in ("drug_safety", "prescription_request") or "drug" in classification.get("medical_domains", []):
        assignee = "pharmacist"
    elif intent in ("legal_privacy",) or classification.get("medical_law_risk"):
        assignee = "legal"
    elif needs:
        assignee = "doctor"
    else:
        assignee = "none"

    # 우선순위
    if risk in ("crisis", "very_high") or "safety_block" in reasons or intent == "emergency":
        priority = "high"
    elif needs:
        priority = "medium"
    else:
        priority = "low"

    return {
        "needs_review": needs,
        "priority": priority,
        "reasons": reasons,
        "assignee_role": assignee,
    }


def enqueue_review(
    answer_id: str,
    question: str,
    answer: str,
    decision: Dict,
    rag_query_id: str = None,
) -> Optional[str]:
    """
    검수 큐에 적재 (review_queue_items). db 모듈에 add_review_item 있으면 호출.
    DB 미연동/오류 시 None 반환 (호출 흐름 비차단).
    """
    if not decision.get("needs_review"):
        return None
    try:
        import db as _db
        if hasattr(_db, "add_review_item"):
            return _db.add_review_item({
                "answer_id": answer_id,
                "rag_query_id": rag_query_id,
                "question": question,
                "answer": answer,
                "priority": decision.get("priority", "medium"),
                "assignee_role": decision.get("assignee_role", "doctor"),
                "reasons": decision.get("reasons", []),
                "status": "pending",
            })
    except Exception:
        pass
    return None
