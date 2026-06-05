"""medical_classifier 규칙 기반 분류 단위 테스트 (스펙 §5.1/§7.1)."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from medical_classifier import classify_rule_based, classify_question, INTENTS, RESPONSE_MODES


def test_emergency_chest_pain():
    r = classify_rule_based("갑자기 가슴이 쥐어짜듯 아프고 식은땀이 나요")
    assert r["intent"] == "emergency"
    assert r["risk_level"] in ("very_high", "crisis")
    assert r["allowed_response_mode"] == "emergency_guidance"
    assert "chest_pain" in r["red_flags"]


def test_crisis_suicidal():
    r = classify_rule_based("요즘 너무 우울해서 죽고 싶다는 생각이 들어요")
    assert r["intent"] == "mental_health_crisis"
    assert r["risk_level"] == "crisis"
    assert r["allowed_response_mode"] == "crisis_guidance"


def test_drug_safety_routes_to_dur():
    r = classify_rule_based("와파린이랑 아스피린 같이 먹어도 돼요?")
    assert r["intent"] == "drug_safety"
    assert "MFDS_DUR" in r["retrieval_routes"]
    assert r["requires_clinician_consult"] is True
    assert r["medical_law_risk"] is True


def test_prescription_request_refused():
    r = classify_rule_based("무슨 약 먹으면 돼요?")
    assert r["intent"] == "prescription_request"
    assert r["allowed_response_mode"] == "refuse_with_guidance"
    assert "MFDS_DUR" in r["retrieval_routes"]


def test_diagnosis_request_refused():
    r = classify_rule_based("저 당뇨야? 검사 결과 정상인가요")
    assert r["intent"] in ("diagnosis_request", "lab_interpretation")
    assert r["medical_law_risk"] is True


def test_vaccination_routes_kdca():
    r = classify_rule_based("독감 예방접종 언제 맞아야 하나요?")
    assert r["intent"] == "vaccination"
    assert "KDCA" in r["retrieval_routes"]


def test_pregnancy_raises_risk():
    r = classify_rule_based("임신 중 이부프로펜 먹어도 되나요?")
    assert r["intent"] == "drug_safety"
    assert "pregnancy" in r["population_tags"]
    assert r["risk_level"] in ("high", "very_high")
    assert r["requires_clinician_consult"] is True


def test_general_health_low_risk():
    r = classify_rule_based("건강검진은 몇 살부터 받는 게 좋아요?")
    assert r["intent"] == "general_health"
    assert r["risk_level"] == "low"


def test_schema_keys_present():
    r = classify_rule_based("머리가 아파요")
    for k in ("intent", "risk_level", "jurisdiction", "medical_domains",
              "population_tags", "red_flags", "medical_law_risk", "requires_citation",
              "requires_clinician_consult", "allowed_response_mode", "retrieval_routes"):
        assert k in r, f"누락 키: {k}"
    assert r["intent"] in INTENTS
    assert r["allowed_response_mode"] in RESPONSE_MODES
    assert r["requires_citation"] is True


def test_classify_question_fallback_without_key():
    # openai_key 없으면 규칙 기반으로 동작
    r = classify_question("가슴이 답답하고 숨이 차요", openai_key=None)
    assert r["intent"] == "emergency"
    assert r["_classifier"] == "rule_based"


if __name__ == "__main__":
    tests = [
        test_emergency_chest_pain, test_crisis_suicidal, test_drug_safety_routes_to_dur,
        test_prescription_request_refused, test_diagnosis_request_refused,
        test_vaccination_routes_kdca, test_pregnancy_raises_risk,
        test_general_health_low_risk, test_schema_keys_present,
        test_classify_question_fallback_without_key,
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
