"""review_queue.should_review 결정 로직 단위 테스트 (스펙 §13 E-2)."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from review_queue import should_review


def test_low_risk_no_review():
    d = should_review(
        classification={"intent": "general_health", "risk_level": "low", "medical_domains": []},
        citation_result={"overall_pass": True, "citation_coverage": 1.0},
        safety_result={"safe_to_send": True, "risk_flags": []},
    )
    assert d["needs_review"] is False
    assert d["assignee_role"] == "none"


def test_drug_safety_to_pharmacist():
    d = should_review(
        classification={"intent": "drug_safety", "risk_level": "high",
                        "medical_domains": ["drug"], "medical_law_risk": True},
        citation_result={"overall_pass": True, "citation_coverage": 1.0},
    )
    assert d["needs_review"] is True
    assert d["assignee_role"] == "pharmacist"


def test_emergency_high_priority():
    d = should_review(classification={"intent": "emergency", "risk_level": "very_high"})
    assert d["needs_review"] is True
    assert d["priority"] == "high"


def test_citation_fail_triggers_review():
    d = should_review(
        classification={"intent": "symptom_info", "risk_level": "medium"},
        citation_result={"overall_pass": False, "citation_coverage": 0.5},
    )
    assert d["needs_review"] is True
    assert any("citation" in r for r in d["reasons"])


def test_safety_block_high_priority():
    d = should_review(
        classification={"intent": "symptom_info", "risk_level": "medium"},
        safety_result={"safe_to_send": False, "risk_flags": ["diagnosis"]},
    )
    assert d["needs_review"] is True
    assert d["priority"] == "high"


def test_legal_assignee():
    d = should_review(classification={"intent": "legal_privacy", "risk_level": "medium",
                                      "medical_law_risk": True})
    assert d["assignee_role"] == "legal"


if __name__ == "__main__":
    tests = [
        test_low_risk_no_review, test_drug_safety_to_pharmacist, test_emergency_high_priority,
        test_citation_fail_triggers_review, test_safety_block_high_priority, test_legal_assignee,
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
