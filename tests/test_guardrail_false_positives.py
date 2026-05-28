"""
RAG 가드레일 오탐(False Positive) 회귀 테스트.

배경: 1100 시나리오 배치 평가에서 both_A=0% 였던 직접 원인이
ComplianceAnalyzer 가드레일의 오탐이었다 (좋은 응답이 HIGH로 차단/재생성됨).

수정한 오탐 3종:
  1. treatment: 면책조항 "진단·치료는 의료진과 상담하세요" 가 치료 지시로 오탐
  2. emergency_guidance: ".{0,100}(?!.*119)" 백트래킹 구조 → 119가 있어도 오탐
  3. emergency_workflow_violation: 조건부 안전망 "악화 시 응급실" + 문진 질문 오탐

이 테스트는 (a) 위 오탐이 사라졌는지, (b) 진짜 위반(true positive)은
여전히 잡히는지 동시에 검증한다.

pytest 의 stdout 캡처가 proxy_server 의 stdout 래핑과 충돌하므로
직접 실행(__main__)을 권장: python tests/test_guardrail_false_positives.py
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from analyzer import ComplianceAnalyzer

_analyzer = ComplianceAnalyzer()


def _rule_ids(text, user_input=""):
    result = _analyzer.analyze(text, user_input=user_input)
    return {v.rule_id for v in result.violations}


# ── 응답 픽스처 ───────────────────────────────────────────────────────────────

DISCLAIMER = "본 정보는 참고용이며, 정확한 진단·치료는 의료진과 상담하세요."

EMERGENCY_RESPONSE_OK = f"""**즉시 119 또는 응급실 방문을 권유드립니다.**

【① 즉시 행동】
- 119 즉시 신고 [1]
- 활동 중단, 앉거나 누운 자세 유지 [1]

【③ 상세 설명】
가슴을 쥐어짜는 흉통과 식은땀이 동반되면 심장 응급질환의 대표 신호입니다 [1].

{DISCLAIMER}"""

NONEMERGENCY_WITH_QUESTIONS = f"""【① 즉시 행동】
- 충분한 수분 섭취와 휴식을 권합니다 [1]
- 증상이 악화되면 응급실 방문을 고려하세요 [1]

【④ 추가 확인 사항】
- (증상) 통증 부위가 어디신가요? 어떤 양상인가요?
- (위험 신호) 처짐·경련·호흡곤란 발생 시 즉시 응급실 방문을 권합니다.
- (맥락) 복용 중인 약이 있으신가요? 기저질환은 있으신가요?

{DISCLAIMER}"""


# ── False Positive 가 사라졌는지 ──────────────────────────────────────────────

def test_fp_disclaimer_not_treatment():
    """면책조항('치료는 의료진과 상담하세요')만으로 treatment 위반이 발생하면 안 된다."""
    ids = _rule_ids(f"두통은 긴장성일 수 있습니다 [1]. {DISCLAIMER}", user_input="머리가 아파요")
    assert "treatment" not in ids, f"면책조항이 treatment 로 오탐됨: {ids}"


def test_fp_emergency_response_with_119_not_flagged():
    """119/응급실 안내를 상단에 제대로 포함한 응급 응답은 emergency_guidance 오탐이 없어야 한다."""
    ids = _rule_ids(EMERGENCY_RESPONSE_OK, user_input="가슴이 아파요")
    assert "emergency_guidance" not in ids, f"119 포함 응급 응답이 오탐됨: {ids}"
    assert "treatment" not in ids, f"면책조항 treatment 오탐: {ids}"


def test_fp_conditional_safetynet_with_questions():
    """'악화 시 응급실'(조건부 안전망) + 문진 질문은 emergency_workflow 위반이 아니다."""
    ids = _rule_ids(NONEMERGENCY_WITH_QUESTIONS, user_input="머리가 아파요")
    assert "emergency_workflow_violation" not in ids, (
        f"조건부 안전망 + 문진 질문이 응급 워크플로 위반으로 오탐됨: {ids}"
    )
    assert "treatment" not in ids, f"treatment 오탐: {ids}"


# ── True Positive 가 여전히 잡히는지 ─────────────────────────────────────────

def test_tp_direct_test_order_still_blocked():
    """'MRI를 받으세요' 같은 직접 검사 지시는 여전히 차단되어야 한다."""
    ids = _rule_ids("MRI를 받으세요. 혈액검사를 받으세요.")
    assert ("treatment" in ids) or ("medical_directive" in ids), (
        f"직접 검사 지시가 차단되지 않음: {ids}"
    )


def test_tp_treatment_directive_still_blocked():
    """'수술을 받으세요' 같은 직접 치료 지시는 여전히 차단되어야 한다."""
    ids = _rule_ids("수술을 받으세요. 입원이 필요합니다.")
    assert "treatment" in ids, f"치료 지시가 차단되지 않음: {ids}"


def test_tp_missing_emergency_guidance_still_blocked():
    """응급 증상 언급 + 119/응급실 안내가 전혀 없으면 emergency_guidance 가 잡혀야 한다."""
    ids = _rule_ids("흉통이 있으시군요. 스트레스 때문일 수 있습니다. 휴식을 취하세요.",
                     user_input="가슴 통증")
    assert "emergency_guidance" in ids, f"응급 가이드 누락이 잡히지 않음: {ids}"


def test_tp_emergency_then_question_still_blocked():
    """'지금 즉시 119 신고' 같은 비조건부 즉시 리다이렉트 후 추가 질문은 여전히 위반이다."""
    ids = _rule_ids("지금 즉시 119에 신고하세요. 그런데 통증이 언제부터 시작되었나요?",
                    user_input="가슴이 아파요")
    assert "emergency_workflow_violation" in ids, (
        f"즉시 리다이렉트 후 추가 질문이 잡히지 않음: {ids}"
    )


if __name__ == "__main__":
    tests = [
        test_fp_disclaimer_not_treatment,
        test_fp_emergency_response_with_119_not_flagged,
        test_fp_conditional_safetynet_with_questions,
        test_tp_direct_test_order_still_blocked,
        test_tp_treatment_directive_still_blocked,
        test_tp_missing_emergency_guidance_still_blocked,
        test_tp_emergency_then_question_still_blocked,
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
