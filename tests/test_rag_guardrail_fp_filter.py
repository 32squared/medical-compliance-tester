"""
RAG 전용 가드레일 오탐(FP) 필터 회귀 테스트.

배경: dev RAG 프로브에서 '해열제를 복용하면 도움이 될 수 있습니다' 같은
교육적/소프트 약물 언급이 prescription(CRITICAL)로 오탐되어 답변이 차단되거나,
treatment/medical_directive(HIGH)로 오탐되어 불필요한 재생성(2차 LLM=지연 2배)이
발생했다. _filter_guardrail_false_positives 는 공용 analyzer를 건드리지 않고
RAG 응답 후처리에서만 이런 오탐을 제거한다.

이 테스트는 (a) 교육적/면책/부정 문맥 오탐이 제거되는지,
(b) 실제 지시·구체 용량·단정 진단은 보존되는지 검증한다.

직접 실행 권장: python tests/test_rag_guardrail_fp_filter.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from analyzer import ComplianceAnalyzer
from rag_engine import _filter_guardrail_false_positives as _filt

_ana = ComplianceAnalyzer()
_DIRECTIVE = {"prescription", "diagnosis", "treatment", "medical_directive"}


def _violations(text, user_input=""):
    r = _ana.analyze(text, user_input=user_input)
    return [
        {
            "rule_id": v.rule_id,
            "severity": v.severity,
            "matched_text": v.matched_text,
            "context": getattr(v, "context", "") or "",
        }
        for v in r.violations
    ]


def _kept_directive_rules(text, user_input=""):
    kept, _dropped = _filt(_violations(text, user_input))
    return {v["rule_id"] for v in kept if v["rule_id"] in _DIRECTIVE}


# ── 오탐(FP)이 제거되는지 ────────────────────────────────────────────────────

def test_fp_soft_drug_mention_dropped():
    """'해열제를 복용하면 도움이 될 수 있습니다'(소프트/교육) → prescription 오탐 제거."""
    kept = _kept_directive_rules(
        "38도가 넘으면 해열제를 복용하면 도움이 될 수 있습니다 [1].", "열이 나요"
    )
    assert "prescription" not in kept, f"소프트 약물 언급이 오탐 유지됨: {kept}"


def test_fp_educational_drug_dropped():
    """'진통제가 사용되기도 합니다'(일반 정보) → 지시형 오탐 제거."""
    kept = _kept_directive_rules("일반적으로 감기에는 진통제가 사용되기도 합니다 [1].", "감기")
    assert not (kept & _DIRECTIVE), f"교육적 약물 정보가 오탐 유지됨: {kept}"


def test_fp_disclaimer_no_block():
    """표준 면책문구는 어떤 지시형 위반도 남기지 않아야 한다(차단/재생성 없음)."""
    kept = _kept_directive_rules(
        "본 서비스는 질병의 진단·처방·치료를 하지 않으며 참고용으로 제공됩니다.", ""
    )
    assert not (kept & _DIRECTIVE), f"면책문구가 지시형 위반으로 오탐됨: {kept}"


# ── 실제 위반(TP)은 보존되는지 ──────────────────────────────────────────────

def test_tp_prescription_with_dose_kept():
    """'타이레놀 500mg을 하루 3번 복용하세요'(구체 용량+명령형) → 보존."""
    kept = _kept_directive_rules("타이레놀 500mg을 하루 3번 복용하세요.", "두통")
    assert "prescription" in kept, f"구체 용량 처방 지시가 잘못 제거됨: {kept}"


def test_tp_imperative_drug_kept():
    """'항생제를 복용하세요'(명령형) → 보존."""
    kept = _kept_directive_rules("항생제를 복용하세요. 증상이 나으실 겁니다.", "인후염")
    assert "prescription" in kept, f"명령형 약물 지시가 잘못 제거됨: {kept}"


def test_tp_treatment_directive_kept():
    """'수술을 받으세요'(치료 지시) → 보존."""
    kept = _kept_directive_rules("수술을 받으세요. 입원이 필요합니다.", "복통")
    assert "treatment" in kept, f"치료 지시가 잘못 제거됨: {kept}"


def test_tp_test_directive_kept():
    """'MRI를 받으세요'(검사 지시) → 보존."""
    kept = _kept_directive_rules("MRI를 받으세요. 혈액검사를 받으세요.", "두통")
    assert kept & {"treatment", "medical_directive"}, f"검사 지시가 잘못 제거됨: {kept}"


def test_tp_definitive_diagnosis_kept():
    """'당신의 증상은 폐렴입니다'(단정 진단) → 보존."""
    kept = _kept_directive_rules("당신의 증상은 폐렴입니다.", "기침")
    assert "diagnosis" in kept, f"단정 진단이 잘못 제거됨: {kept}"


if __name__ == "__main__":
    tests = [
        test_fp_soft_drug_mention_dropped,
        test_fp_educational_drug_dropped,
        test_fp_disclaimer_no_block,
        test_tp_prescription_with_dose_kept,
        test_tp_imperative_drug_kept,
        test_tp_treatment_directive_kept,
        test_tp_test_directive_kept,
        test_tp_definitive_diagnosis_kept,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n결과: {passed}/{len(tests)} 통과")
    sys.exit(0 if failed == 0 else 1)
