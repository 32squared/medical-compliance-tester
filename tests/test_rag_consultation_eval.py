"""rag_consultation_eval 단위 테스트 — 프롬프트 빌더(순수). 키/네트워크 불필요."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from rag_consultation_eval import (
    build_consultation_system_prompt, evaluate_consultation_rag, CONSULT_EVAL_VERSION,
)


def test_prompt_recognizes_4stage_no_penalty():
    p = build_consultation_system_prompt()
    assert "4단" in p
    # 정보 선행 후 질문을 감점하지 말라는 명시
    assert "감점하지 마라" in p or "감점 금지" in p
    assert "structuredApproach" in p


def test_prompt_emergency_skip_not_penalized():
    p = build_consultation_system_prompt()
    assert "응급" in p and ("생략" in p and "감점하지" in p)


def test_prompt_has_five_axes():
    p = build_consultation_system_prompt()
    for ax in ("symptomExploration", "redFlagScreening", "patientContext",
               "structuredApproach", "appropriateGuidance"):
        assert ax in p


def test_prompt_json_contract_and_grade():
    p = build_consultation_system_prompt()
    assert '"totalScore"' in p and '"axes"' in p
    assert "A(≥85)" in p


def test_evaluate_returns_none_without_key():
    assert evaluate_consultation_rag("q", "a", "") is None
    assert evaluate_consultation_rag("q", "", "sk-x") is None


def test_version_constant():
    assert CONSULT_EVAL_VERSION == "rag-consult-v1"


if __name__ == "__main__":
    tests = [
        test_prompt_recognizes_4stage_no_penalty, test_prompt_emergency_skip_not_penalized,
        test_prompt_has_five_axes, test_prompt_json_contract_and_grade,
        test_evaluate_returns_none_without_key, test_version_constant,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn(); print(f"  PASS  {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}"); failed += 1
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}"); failed += 1
    print(f"\n결과: {passed}/{len(tests)} 통과")
    sys.exit(0 if failed == 0 else 1)
