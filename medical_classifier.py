"""
Question Classifier — 의료 질문 분류기 (작업지시서 §5.1, §7.1 / EPIC B-1).

사용자 질문을 intent / risk_level / jurisdiction / retrieval_routes 등으로 분류한다.

두 경로:
- LLM 경로: OpenAI 키가 있으면 §7.1 프롬프트로 분류 (작은 모델 권장, 비용규칙 C2).
- 규칙 경로(fallback): 키워드 휴리스틱. 키 없이 로컬 동작·테스트 가능, p95<300ms.

반환 스키마 (스펙 §7.1):
{
  "intent": "...", "risk_level": "...", "jurisdiction": "KR|global|unknown",
  "medical_domains": [...], "population_tags": [...], "red_flags": [...],
  "medical_law_risk": bool, "requires_citation": true,
  "requires_clinician_consult": bool, "allowed_response_mode": "...",
  "retrieval_routes": [...], "reason_brief": "..."
}
"""

from __future__ import annotations

import json
import os
import re
import ssl
from typing import Dict, List
from urllib.request import Request, urlopen

# OpenAI API 베이스 URL (env화, P4) — 미설정 시 공식 엔드포인트 사용
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://api.openai.com")

INTENTS = [
    "general_health", "symptom_info", "drug_safety", "lab_interpretation",
    "vaccination", "infection", "emergency", "diagnosis_request",
    "prescription_request", "mental_health_crisis", "legal_privacy", "unknown",
]
RISK_LEVELS = ["low", "medium", "high", "very_high", "crisis"]
RESPONSE_MODES = [
    "answer", "cautious_answer", "refuse_with_guidance",
    "emergency_guidance", "crisis_guidance", "insufficient_information",
]

# ── 키워드 사전 (규칙 기반) ──────────────────────────────────────────────────
_KW = {
    "emergency": [
        "흉통", "가슴 통증", "가슴이 아", "가슴이 답답", "쥐어짜", "호흡곤란",
        "숨이 안", "숨쉬기 힘", "숨이 차", "숨차", "숨이 막", "숨 쉬기",
        "의식", "쓰러", "실신", "기절", "편측", "한쪽 마비", "한쪽 팔", "한쪽 다리",
        "발음", "말이 안", "경련", "발작", "심한 출혈", "토혈", "각혈", "아나필락시스",
        "갑자기 심한", "망치로", "심정지",
    ],
    "mental_health_crisis": ["자살", "자해", "죽고 싶", "목숨", "극단적 선택", "약을 다 먹"],
    "drug_safety": [
        "약", "복용", "먹어도", "끊어도", "항생제", "진통제", "해열제", "타이레놀",
        "이부프로펜", "아스피린", "와파린", "혈압약", "당뇨약", "인슐린", "스테로이드",
        "병용", "같이 먹", "용량", "증량", "감량", "부작용",
    ],
    "prescription_request": ["무슨 약", "약 추천", "어떤 약", "약 좀", "처방", "약 먹으면 돼"],
    "diagnosis_request": ["나 ~야", "이거 암", "암이야", "당뇨야", "무슨 병", "병이야", "진단", "정상이", "정상인가"],
    "vaccination": ["예방접종", "백신", "접종", "독감주사", "예방주사"],
    "infection": ["감염", "전염", "코로나", "독감", "인플루엔자", "결핵", "장염", "식중독", "전염병"],
    "lab_interpretation": ["검사 결과", "수치", "혈압이", "혈당", "콜레스테롤", "간수치", "정상범위", "비정상"],
}
_DRUG_NAMES_RE = re.compile(r"타이레놀|이부프로펜|아스피린|와파린|메트포르민|아목시실린|인슐린|스타틴|statin")
_POP = {
    "pregnancy": ["임신", "임산부", "임부", "수유"],
    "lactation": ["수유", "모유"],
    "child": ["아이", "소아", "유아", "아기", "어린이", "살 아이", "개월"],
    "elderly": ["노인", "어르신", "70대", "80대", "고령"],
}


def _has(text: str, words: List[str]) -> bool:
    return any(w in text for w in words)


def classify_rule_based(text: str) -> Dict:
    """키워드 휴리스틱 분류 (LLM 없이 동작)."""
    t = (text or "").strip()
    tl = t.lower()

    red_flags: List[str] = []
    intent = "general_health"
    risk = "low"
    mode = "answer"
    routes: List[str] = ["KR_GUIDELINE"]
    domains: List[str] = []
    clinician = False
    law_risk = False

    # 우선순위: crisis > emergency > prescription/diagnosis > drug > infection/vaccination > symptom
    if _has(t, _KW["mental_health_crisis"]):
        intent, risk, mode = "mental_health_crisis", "crisis", "crisis_guidance"
        red_flags.append("suicidal_ideation")
        clinician = True
        routes = ["LEGAL_POLICY", "KR_GUIDELINE"]
    elif _has(t, _KW["emergency"]):
        intent, risk, mode = "emergency", "very_high", "emergency_guidance"
        clinician = True
        routes = ["KR_GUIDELINE", "KDCA"]
        for kw in ("흉통", "가슴", "호흡곤란", "숨", "의식", "마비", "경련", "출혈", "아나필락시스"):
            if kw in t:
                red_flags.append({
                    "흉통": "chest_pain", "가슴": "chest_pain", "호흡곤란": "dyspnea",
                    "숨": "dyspnea", "의식": "loss_of_consciousness", "마비": "stroke_symptoms",
                    "경련": "seizure", "출혈": "severe_bleeding",
                    "아나필락시스": "severe_allergic_reaction",
                }[kw])
        red_flags = list(dict.fromkeys(red_flags))
    elif _has(t, _KW["prescription_request"]):
        intent, risk, mode = "prescription_request", "high", "refuse_with_guidance"
        clinician, law_risk = True, True
        routes = ["MFDS_DUR", "HIRA_DUR"]
        domains = ["drug"]
    elif _has(t, _KW["diagnosis_request"]):
        intent, risk, mode = "diagnosis_request", "high", "refuse_with_guidance"
        clinician, law_risk = True, True
        routes = ["KR_GUIDELINE"]
    elif _has(t, _KW["drug_safety"]) or _DRUG_NAMES_RE.search(tl):
        intent, risk, mode = "drug_safety", "high", "cautious_answer"
        clinician, law_risk = True, True
        routes = ["MFDS_DUR", "HIRA_DUR", "KR_GUIDELINE"]
        domains = ["drug"]
    elif _has(t, _KW["vaccination"]):
        intent, risk, mode = "vaccination", "low", "answer"
        routes = ["KDCA", "WHO", "CDC"]
        domains = ["vaccination"]
    elif _has(t, _KW["infection"]):
        intent, risk, mode = "infection", "medium", "answer"
        routes = ["KDCA", "WHO", "CDC"]
        domains = ["infection"]
    elif _has(t, _KW["lab_interpretation"]):
        intent, risk, mode = "lab_interpretation", "medium", "cautious_answer"
        clinician = True
        routes = ["KR_GUIDELINE"]
        domains = ["lab"]
    else:
        # 증상 서술이면 symptom_info, 아니면 general_health
        if re.search(r"아프|통증|증상|열|기침|어지|저림|붓|발진|설사|구토|두통|복통", t):
            intent, risk, mode = "symptom_info", "medium", "cautious_answer"
        else:
            intent, risk, mode = "general_health", "low", "answer"

    population = [tag for tag, kws in _POP.items() if _has(t, kws)]
    if "pregnancy" in population or "child" in population:
        # 임신/소아는 위험도·임상상담 상향
        if risk in ("low", "medium"):
            risk = "high"
        clinician = True

    return {
        "intent": intent,
        "risk_level": risk,
        "jurisdiction": "KR",
        "medical_domains": domains,
        "population_tags": population,
        "red_flags": red_flags,
        "medical_law_risk": law_risk,
        "requires_citation": True,
        "requires_clinician_consult": clinician,
        "allowed_response_mode": mode,
        "retrieval_routes": routes,
        "reason_brief": f"rule-based: intent={intent}, risk={risk}",
        "_classifier": "rule_based",
    }


def build_classifier_prompt() -> str:
    """LLM 분류기 시스템 프롬프트 (스펙 §7.1)."""
    return (
        "너는 한국어 의료정보 서비스의 질문 분류기다.\n"
        "사용자 질문을 읽고 아래 JSON만 출력하라. 의학적 조언을 생성하지 말고 분류 결과만 출력하라.\n\n"
        f"intent enum: {', '.join(INTENTS)}\n"
        f"risk_level enum: {', '.join(RISK_LEVELS)}\n"
        f"allowed_response_mode enum: {', '.join(RESPONSE_MODES)}\n"
        "retrieval_routes enum: KDCA, MFDS_DUR, HIRA_DUR, KR_GUIDELINE, WHO, CDC, NICE, PUBMED, PMC_OA, LEGAL_POLICY\n\n"
        "규칙:\n"
        "- 약물 복용/중단/병용 질문은 drug_safety + retrieval_routes에 MFDS_DUR/HIRA_DUR 우선.\n"
        "- 진단 확정 요청(나 ~병이야?)은 diagnosis_request + refuse_with_guidance.\n"
        "- 처방 요청(무슨 약 먹어?)은 prescription_request + refuse_with_guidance.\n"
        "- 흉통·호흡곤란·의식저하·편측마비 등은 emergency + emergency_guidance.\n"
        "- 자살/자해 언급은 mental_health_crisis + crisis_guidance.\n"
        "- 한국 사용자이므로 jurisdiction은 기본 KR.\n\n"
        "출력 JSON schema:\n"
        '{"intent":"...","risk_level":"...","jurisdiction":"KR|global|unknown",'
        '"medical_domains":["..."],"population_tags":["adult|child|elderly|pregnancy|lactation|unknown"],'
        '"red_flags":["..."],"medical_law_risk":true,"requires_citation":true,'
        '"requires_clinician_consult":true,"allowed_response_mode":"...",'
        '"retrieval_routes":["..."],"reason_brief":"한 문장 이내"}'
    )


def _classify_llm(text: str, openai_key: str, model: str = None) -> Dict:
    """OpenAI로 분류 (작은 모델 권장)."""
    body = json.dumps({
        "model": model or "gpt-5.4-mini",
        "messages": [
            {"role": "system", "content": build_classifier_prompt()},
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = Request(
        url=f"{OPENAI_API_BASE}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {openai_key}"},
        method="POST",
    )
    ctx = ssl.create_default_context()
    resp = urlopen(req, context=ctx, timeout=30)
    result = json.loads(resp.read().decode("utf-8"))
    parsed = json.loads(result["choices"][0]["message"]["content"])
    parsed.setdefault("requires_citation", True)
    parsed.setdefault("jurisdiction", "KR")
    parsed["_classifier"] = "llm:" + (model or "gpt-5.4-mini")
    return parsed


def classify_question(text: str, openai_key: str = None, model: str = None) -> Dict:
    """질문 분류 — LLM 우선, 실패/키없음 시 규칙 기반 fallback."""
    if openai_key:
        try:
            return _classify_llm(text, openai_key, model)
        except Exception:
            pass
    return classify_rule_based(text)
