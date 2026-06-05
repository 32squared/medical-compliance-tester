"""rag_legal_eval 단위 테스트 — 프롬프트 빌더(순수). 키/네트워크 불필요."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from rag_legal_eval import build_legal_system_prompt, evaluate_legal_rag, LEGAL_EVAL_VERSION


def test_prompt_allows_emergency_guidance():
    p = build_legal_system_prompt()
    assert "119" in p
    assert "응급 안내는 필수" in p
    # 응급안내를 위반으로 잡지 말라는 명시
    assert "위반으로 잡지" in p or "위반(내원 지시 등)으로 잡지 마라" in p


def test_prompt_allows_hedged_and_specialty():
    p = build_legal_system_prompt()
    assert "의심됩니다" in p          # 헷지 감별 허용
    assert "가능성" in p
    assert "진료과 안내는 허용" in p  # 진료과 안내 허용


def test_prompt_keeps_real_violations_strict():
    p = build_legal_system_prompt()
    assert "확정 진단 단정" in p
    assert "구체적 처방" in p or "용량 지시" in p
    assert "과대" in p and "허위" in p
    assert "병원 안 가도 됩니다" in p  # 위험한 안심


def test_prompt_has_json_contract():
    p = build_legal_system_prompt()
    for key in ('"score"', '"grade"', '"violations"', '"has_disclaimer"'):
        assert key in p


def test_evaluate_returns_none_without_key():
    assert evaluate_legal_rag("q", "a", "", model="gpt-4o-mini") is None
    assert evaluate_legal_rag("q", "", "sk-x", model="gpt-4o-mini") is None


def test_version_constant():
    assert LEGAL_EVAL_VERSION == "rag-legal-v1"


if __name__ == "__main__":
    tests = [
        test_prompt_allows_emergency_guidance, test_prompt_allows_hedged_and_specialty,
        test_prompt_keeps_real_violations_strict, test_prompt_has_json_contract,
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
