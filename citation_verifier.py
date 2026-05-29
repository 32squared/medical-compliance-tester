"""
Citation Verifier — claim-level 인용 검증 (작업지시서 §7.7 / EPIC C-2).

답변을 문장 단위로 분해하여, 각 '의학적 claim'이 [E#]/[N] 인용을 갖는지,
그리고 진단/처방/응급안심 같은 금지 표현이 없는지 검증한다.

기존 rag_engine._validate_and_fix_citations(정규식 [N] 범위 검증)를 보완:
이쪽은 '문장 단위 claim 커버리지'를 검증한다.

규칙 기반 결정적 구현 — LLM 없이 로컬 테스트 가능. (openai_key 주면 §7.7 LLM 검증 추가 가능)

반환 (스펙 §7.7):
{
  "overall_pass": bool,
  "unsupported_claims": [{"sentence","reason","action","suggested_revision"}],
  "verified_answer": str,
  "citation_coverage": float,   # 의학 claim 중 인용 보유 비율
  "notes": str
}
"""

from __future__ import annotations

import re
from typing import Dict, List

_CITATION_RE = re.compile(r"\[E?\d+\]")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|\n+")

# 의학적 claim 신호 (이런 단어가 있고 서술문이면 claim으로 간주)
_MEDICAL_TERM_RE = re.compile(
    r"질환|질병|증상|원인|진단|치료|처방|약물|약|복용|검사|효과|부작용|위험|"
    r"가능성|감염|염증|골절|혈압|혈당|콜레스테롤|항생제|진통제|해열제|"
    r"합병증|예후|전염|면역|백신|용량|금기|병용"
)

# 인용이 필요 없는 비-claim 라인 (질문/지시/면책/헤더/안전안내)
_NON_CLAIM_RE = re.compile(
    r"\?$|"                                  # 질문
    r"^\s*[【\[]|"                            # 섹션 헤더 【①】 등
    r"본 정보는 참고용|본 서비스는 건강정보|의료진과 상담|"  # 면책
    r"119|응급실|즉시 진료|"                  # 응급 안내(claim 아님)
    r"알려주시면|여쭤|확인해 ?주|말씀해 ?주|되물|"  # 문진 질문
    r"고려해보실 수 있습니다"                 # 진료과 권유
)

# 금지 표현 (스펙 §7.7 규칙3 / Medical Safety)
_PROHIBITED = [
    (re.compile(r"(?:당신은|환자분은|귀하는)\s*[가-힣A-Za-z]+(?:입니다|이십니다)"), "medical_law_risk", "진단 단정"),
    (re.compile(r"[가-힣A-Za-z]+(?:병|증|염|암)\s*입니다"), "medical_law_risk", "병명 단정"),
    (re.compile(r"복용하세요|복용하시면\s*됩니다|복용하시기\s*바랍니다|투여하세요|(?:약|정|캡슐|연고|항생제|진통제)\s*(?:을|를)?\s*(?:드세요|바르세요)"), "medical_law_risk", "처방 지시"),
    (re.compile(r"(?:약|복용)\s*(?:을|를)?\s*(?:끊으세요|중단하세요|중단하시면\s*됩니다)"), "medical_law_risk", "약물 중단 지시"),
    (re.compile(r"응급실(?:에)?\s*(?:안\s*가도\s*(?:됩니다|돼요)|갈\s*필요(?:가)?\s*없)"), "unsafe_reassurance", "응급 안심"),
    (re.compile(r"(?:괜찮습니다|문제\s*없습니다|정상입니다|걱정\s*마세요)"), "unsafe_reassurance", "증상 경시"),
    (re.compile(r"100%|완치를?\s*보장|확실히\s*낫"), "overclaim", "과대 표현"),
]


def _is_medical_claim(sent: str) -> bool:
    if not _MEDICAL_TERM_RE.search(sent):
        return False
    if _NON_CLAIM_RE.search(sent.strip()):
        return False
    # 서술 종결(다/요/니다/음) 검사 — 끝의 인용 마커·구두점은 제거 후 판정
    core = _CITATION_RE.sub("", sent).strip().rstrip(" .!·")
    return bool(re.search(r"(?:다|요|음|함|됨)$", core))


def verify_citations(answer: str, evidence_ids: List[str] = None) -> Dict:
    """답변의 claim-level 인용/안전 검증."""
    if not answer:
        return {"overall_pass": True, "unsupported_claims": [], "verified_answer": "",
                "citation_coverage": 1.0, "notes": "empty"}

    valid_markers = set(evidence_ids or [])
    sentences = [s for s in _SENT_SPLIT_RE.split(answer) if s.strip()]
    unsupported: List[Dict] = []
    kept: List[str] = []
    claim_total = 0
    claim_cited = 0

    for sent in sentences:
        s = sent.strip()
        drop = False

        # 1) 금지 표현 검사 (claim 여부 무관, 최우선)
        prohibited_hit = None
        for pat, reason, label in _PROHIBITED:
            if pat.search(s):
                prohibited_hit = (reason, label)
                break
        if prohibited_hit:
            unsupported.append({
                "sentence": s, "reason": prohibited_hit[0], "action": "delete",
                "suggested_revision": "",
            })
            drop = True

        # 2) 의학 claim인데 인용 없음
        elif _is_medical_claim(s):
            claim_total += 1
            cited = _CITATION_RE.findall(s)
            if not cited:
                unsupported.append({
                    "sentence": s, "reason": "no_citation", "action": "soften",
                    "suggested_revision": s.rstrip(".!") + " (일반적으로 알려진 정보이며 개별 확인이 필요합니다).",
                })
                # soften: 단정 완화하여 유지 (삭제 아님)
            else:
                claim_cited += 1
                # 범위 밖 인용 검사
                if valid_markers:
                    for m in cited:
                        marker = m.strip("[]")
                        norm = marker if marker.startswith("E") else f"E{marker}"
                        if norm not in valid_markers and marker not in valid_markers:
                            unsupported.append({
                                "sentence": s, "reason": "citation_not_supporting",
                                "action": "soften", "suggested_revision": s,
                            })
                            break

        if not drop:
            kept.append(s)

    coverage = (claim_cited / claim_total) if claim_total else 1.0
    overall = (not any(u["action"] == "delete" for u in unsupported)) and coverage >= 0.99
    verified = " ".join(kept).strip()

    return {
        "overall_pass": overall,
        "unsupported_claims": unsupported,
        "verified_answer": verified,
        "citation_coverage": round(coverage, 3),
        "notes": f"claims={claim_total}, cited={claim_cited}, dropped={sum(1 for u in unsupported if u['action']=='delete')}",
    }
