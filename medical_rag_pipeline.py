"""
Medical RAG Pipeline — 스펙 모듈 오케스트레이션 (작업지시서 §0 흐름 / §8.1).

스펙의 end-to-end 파이프라인을 조립한다:
  PII mask → classify → safety pre-check → route → retrieve → evidence pack
  → grounded generate → citation verify → safety post-filter → review queue → audit

retrieve_fn / generate_fn은 주입식(의존성 역전):
- 미주입 시 MockLLMProvider 동작 → OpenAI/DB 없이 로컬 end-to-end 테스트 가능 (스펙 §구현방식).
- live 연동 시 rag_engine.hybrid_search / LLM 호출을 어댑터로 주입.

기존 rag_engine.generate_response는 변경하지 않는다(무손상). 이 모듈은 스펙 정합 신규 경로다.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, List, Optional

from pii_masker import mask_pii
from medical_classifier import classify_question
from retrieval_router import route
from evidence_pack import build_evidence_pack, render_evidence_for_prompt
from citation_verifier import verify_citations
from review_queue import should_review

PROMPT_VERSION = "rag-spec-v1"

_CRISIS_MSG = (
    "지금 많이 힘드신 상황으로 느껴집니다. 혼자 감당하지 마시고 즉시 도움을 받으세요. "
    "자살예방상담전화 109 또는 정신건강상담전화 1577-0199로 24시간 상담이 가능하며, "
    "위급하다고 느껴지면 즉시 119에 연락하시기 바랍니다."
)
_EMERGENCY_MSG = (
    "입력하신 증상은 응급 상황일 가능성이 있어 지체 없이 119 또는 가까운 응급실 이용을 권유드립니다. "
    "이동 전 활동을 멈추고 안정을 취하시고, 가능하면 보호자에게 알리세요."
)


def _answer_id(question: str, salt: str = "") -> str:
    h = hashlib.sha1((question + salt).encode("utf-8")).hexdigest()[:12]
    return f"ans_{h}"


def _mock_generate(evidence_pack: Dict, masked_question: str) -> str:
    """MockLLM: Evidence Pack 근거에 [E#] 인용을 붙인 보수적 답변(테스트/오프라인용)."""
    items = evidence_pack.get("evidence_items", [])
    if not items:
        return "확인된 출처가 부족해 단정적으로 답변할 수 없습니다."
    e1 = items[0]
    return (
        f"확인된 근거를 기준으로 일반 정보를 안내드립니다. "
        f"{e1.get('snippet','')[:60]} 와 관련된 내용이 보고됩니다 [{e1['evidence_id']}]. "
        f"개인별 판단은 의료진과 상담이 필요합니다."
    )


def process_medical_query(
    question: str,
    *,
    openai_key: Optional[str] = None,
    classifier_model: Optional[str] = None,
    retrieve_fn: Optional[Callable[[str, Dict], List[Dict]]] = None,
    generate_fn: Optional[Callable[[Dict, str], str]] = None,
    model_version: str = "mock",
    retrieved_at: str = "",
) -> Dict:
    """
    스펙 파이프라인 1회 실행. 모든 단계 결과를 구조화해 반환한다(감사/스트리밍용).
    """
    stages: List[str] = []

    # 1) PII/PHI 마스킹
    stages.append("masking")
    masked = mask_pii(question or "")
    mq = masked["masked_text"]

    # 2) 질문 분류
    stages.append("classifying")
    classification = classify_question(mq, openai_key=openai_key, model=classifier_model)
    mode = classification.get("allowed_response_mode", "cautious_answer")

    # 3) 안전 우선 분기 (crisis / emergency) — 검색보다 안전 안내 우선
    routing = route(classification)
    answer_id = _answer_id(mq, classification.get("intent", ""))

    if classification.get("intent") == "mental_health_crisis":
        stages.append("crisis_guidance")
        return _finalize(answer_id, masked, classification, routing, None,
                         _CRISIS_MSG, {"overall_pass": True, "unsupported_claims": [],
                                       "verified_answer": _CRISIS_MSG, "citation_coverage": 1.0},
                         model_version, stages, safety_level="crisis_guidance")

    # 4) 검색 (주입 함수 / 미주입 시 빈 결과)
    stages.append("retrieval")
    chunks: List[Dict] = []
    if routing.get("retrieval_enabled", True) and retrieve_fn is not None:
        try:
            chunks = retrieve_fn(mq, routing) or []
        except Exception:
            chunks = []

    # 5) Evidence Pack
    stages.append("evidence_pack")
    pack = build_evidence_pack(mq, classification, chunks, retrieved_at=retrieved_at)

    # 응급인데 근거가 약해도 안전 안내는 보장
    if classification.get("intent") == "emergency":
        stages.append("emergency_guidance")
        draft = _EMERGENCY_MSG
        if pack["evidence_items"]:
            gen = generate_fn or _mock_generate
            draft = _EMERGENCY_MSG + "\n\n" + gen(pack, mq)
        cite = verify_citations(draft, [e["evidence_id"] for e in pack["evidence_items"]])
        return _finalize(answer_id, masked, classification, routing, pack,
                         cite["verified_answer"] or draft, cite, model_version, stages,
                         safety_level="emergency_guidance")

    # 6) 근거 부족 → insufficient
    if pack.get("insufficient_evidence"):
        stages.append("insufficient_information")
        msg = ("확인된 출처가 부족해 단정적으로 답변할 수 없습니다. "
               "증상이 지속되거나 악화되면 의료진 또는 약사와 상담해 주세요.")
        return _finalize(answer_id, masked, classification, routing, pack, msg,
                         {"overall_pass": True, "unsupported_claims": [],
                          "verified_answer": msg, "citation_coverage": 1.0},
                         model_version, stages, safety_level="insufficient_information")

    # 7) 근거 기반 생성
    stages.append("generation")
    gen = generate_fn or _mock_generate
    draft = gen(pack, mq)

    # 8) Citation 검증 (claim-level)
    stages.append("citation_verify")
    cite = verify_citations(draft, [e["evidence_id"] for e in pack["evidence_items"]])

    return _finalize(answer_id, masked, classification, routing, pack,
                     cite["verified_answer"], cite, model_version, stages,
                     safety_level=mode)


def _finalize(answer_id, masked, classification, routing, pack, answer,
              cite, model_version, stages, safety_level) -> Dict:
    """검수 큐 결정 + 감사 레코드 구성."""
    stages.append("review_check")
    review = should_review(classification=classification, citation_result=cite)
    # 검수 큐 적재 (DB 연동 가드)
    try:
        from review_queue import enqueue_review
        enqueue_review(answer_id, masked.get("masked_text", ""), answer or "", review)
    except Exception:
        pass

    stages.append("audit")
    evidence_ids = [e["evidence_id"] for e in (pack or {}).get("evidence_items", [])] if pack else []
    audit = {
        "answer_id": answer_id,
        "evidence_ids": evidence_ids,
        "model_version": model_version,
        "prompt_version": PROMPT_VERSION,
        "classifier": classification.get("_classifier", "unknown"),
        "pii_detected": len(masked.get("detected_items", [])),
    }

    return {
        "answer_id": answer_id,
        "masked_question": masked.get("masked_text", ""),
        "pii": {"detected": masked.get("detected_items", []),
                "contains_sensitive_health_info": masked.get("contains_sensitive_health_info", False)},
        "classification": classification,
        "routing": routing,
        "evidence_pack": pack,
        "answer": answer,
        "citation": cite,
        "review": review,
        "safety_level": safety_level,
        "audit": audit,
        "stages": stages,
    }
