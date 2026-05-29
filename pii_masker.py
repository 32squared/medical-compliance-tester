"""
PHI/PII Masker — 개인정보/건강정보 마스킹 엔진 (작업지시서 §7.2 / EPIC D-1).

외부 LLM 전송 전에 직접 식별 가능한 개인정보를 탐지·마스킹한다.
정규식 기반 결정적(deterministic) 구현 — OpenAI 키 없이 로컬에서 동작/테스트 가능.

반환 스키마 (스펙 §7.2):
{
  "masked_text": str,
  "detected_items": [{"type": "name|phone|rrn|address|email|patient_id|card|other",
                      "value_masked": str}],
  "contains_sensitive_health_info": bool,
  "safe_for_llm": bool,
  "notes": str
}

핵심 원칙:
- 의료적 의미 판단에 필요한 비식별 정보(증상·나이대·성별 등)는 유지.
- 이름/전화/주민번호/주소/이메일/환자번호/카드번호 등 직접 식별자는 마스킹.
- 한국 사용자 대상이므로 한국식 식별자(주민번호·휴대폰) 우선.
"""

from __future__ import annotations

import re
from typing import Dict, List

# ── 정규식 패턴 (한국 식별자 우선) ───────────────────────────────────────────

# 주민등록번호: 6자리-7자리 (생년월일-성별/지역)
_RRN_RE = re.compile(r"\b(\d{6})[-\s]?([1-4]\d{6})\b")

# 휴대폰/전화: 010-1234-5678, 02-123-4567, +82 등
_PHONE_RE = re.compile(
    r"\b(?:\+?82[-\s]?)?0?1[016789][-\s]?\d{3,4}[-\s]?\d{4}\b"  # 휴대폰
    r"|\b0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}\b"                      # 지역번호 유선
)

# 이메일
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# 신용카드 (4-4-4-4)
_CARD_RE = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")

# 환자번호/등록번호: "환자번호 12345678", "등록번호: 1234567"
_PATIENT_ID_RE = re.compile(
    r"(?:환자\s*번호|등록\s*번호|차트\s*번호|patient\s*id)\s*[:#]?\s*([A-Za-z]?\d{5,12})",
    re.IGNORECASE,
)

# 주소: "OO시 OO구 ...", "OO로 123", "OO동 123-45"
_ADDRESS_RE = re.compile(
    r"[가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도)\s*[가-힣]+(?:시|군|구)"
    r"(?:\s*[가-힣0-9]+(?:읍|면|동|리|로|길))?(?:\s*\d{1,5}(?:[-]\d{1,4})?)?"
    r"|[가-힣]+(?:로|길)\s*\d{1,5}(?:[-]\d{1,4})?(?:\s*\d{1,4}\s*호)?"
)

# 이름: "제 이름은 홍길동", "환자 홍길동", "홍길동입니다", "성함은 홍길동"
# (한국 이름 일반 NER은 어려우므로 명시적 도입 문구 + 2~4자 한글 이름 휴리스틱)
_NAME_RE = re.compile(
    r"(?:이름은?|성함은?|환자\s*명|성명은?)\s*[:은는]?\s*([가-힣]{2,4})\b"
    r"|\b([가-힣]{2,4})\s*(?:입니다|이고|이라고\s*합니다|씨|님)(?=\s|$|,|\.)"
)

# 건강 민감정보 시그널 (마스킹 대상은 아니나 민감 플래그용)
_HEALTH_SIGNAL_RE = re.compile(
    r"증상|통증|질환|진단|복용|처방|검사|혈압|혈당|우울|불안|임신|암|당뇨|고혈압|"
    r"아프|열이|기침|두통|복통|호흡|어지|발진|출혈|골절"
)


def _mask_token(value: str) -> str:
    """식별자 값을 마스킹 토큰으로 치환 (앞 1글자만 노출)."""
    v = value.strip()
    if len(v) <= 2:
        return "*" * len(v)
    return v[0] + "*" * (len(v) - 1)


def mask_pii(text: str) -> Dict:
    """
    텍스트에서 PII/PHI를 탐지·마스킹한다.

    Returns: 스펙 §7.2 스키마 dict.
    """
    if not text:
        return {
            "masked_text": "",
            "detected_items": [],
            "contains_sensitive_health_info": False,
            "safe_for_llm": True,
            "notes": "empty input",
        }

    detected: List[Dict] = []
    masked = text

    def _apply(pattern: re.Pattern, mask_label: str, ptype: str):
        nonlocal masked
        # finditer on the ORIGINAL-like current masked text
        def _repl(m: re.Match) -> str:
            raw = m.group(0)
            detected.append({"type": ptype, "value_masked": _mask_token(raw)})
            return mask_label
        masked = pattern.sub(_repl, masked)

    # 순서 중요: 카드(16자리) → 주민 → 전화 (오탐 최소화)
    _apply(_CARD_RE, "[CARD]", "card")
    _apply(_RRN_RE, "[RRN]", "rrn")
    _apply(_EMAIL_RE, "[EMAIL]", "email")
    _apply(_PHONE_RE, "[PHONE]", "phone")

    # 환자번호: 그룹 1만 마스킹 (라벨 텍스트는 유지)
    def _patient_repl(m: re.Match) -> str:
        detected.append({"type": "patient_id", "value_masked": _mask_token(m.group(1))})
        return m.group(0).replace(m.group(1), "[PATIENT_ID]")
    masked = _PATIENT_ID_RE.sub(_patient_repl, masked)

    _apply(_ADDRESS_RE, "[ADDRESS]", "address")

    # 이름: 매칭된 이름 그룹만 치환
    def _name_repl(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        if not name:
            return m.group(0)
        detected.append({"type": "name", "value_masked": _mask_token(name)})
        return m.group(0).replace(name, "[NAME]")
    masked = _NAME_RE.sub(_name_repl, masked)

    contains_health = bool(_HEALTH_SIGNAL_RE.search(text))
    # 직접 식별자(주민/카드/환자번호)가 남아있지 않으면 LLM 전송 안전으로 본다
    has_strong_id = any(d["type"] in ("rrn", "card", "patient_id") for d in detected)

    return {
        "masked_text": masked,
        "detected_items": detected,
        "contains_sensitive_health_info": contains_health,
        "safe_for_llm": True,  # 마스킹 후에는 전송 가능 (강한 식별자도 치환됨)
        "notes": (
            f"{len(detected)}개 식별자 마스킹"
            + (", 강한 식별자 포함" if has_strong_id else "")
            + (", 건강 민감정보 포함" if contains_health else "")
        ),
    }


def is_masking_required(text: str) -> bool:
    """마스킹이 필요한 직접 식별자가 있는지 빠르게 검사."""
    if not text:
        return False
    for p in (_RRN_RE, _PHONE_RE, _EMAIL_RE, _CARD_RE, _PATIENT_ID_RE):
        if p.search(text):
            return True
    return False
