"""citation_verifier 단위 테스트 (스펙 §7.7 / EPIC C-2)."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from citation_verifier import verify_citations


def test_cited_claim_passes():
    r = verify_citations("발열은 감염의 흔한 증상입니다 [E1].", evidence_ids=["E1"])
    assert r["overall_pass"] is True
    assert r["citation_coverage"] == 1.0


def test_uncited_claim_flagged():
    r = verify_citations("발열은 세균 감염을 의미하는 증상입니다.")
    assert any(u["reason"] == "no_citation" for u in r["unsupported_claims"])
    assert r["citation_coverage"] < 1.0


def test_diagnosis_assertion_deleted():
    r = verify_citations("당신은 당뇨병입니다. 물을 충분히 드세요.")
    reasons = [u["reason"] for u in r["unsupported_claims"]]
    assert "medical_law_risk" in reasons
    assert r["overall_pass"] is False
    assert "당뇨병입니다" not in r["verified_answer"]


def test_prescription_deleted():
    r = verify_citations("타이레놀을 복용하세요.")
    assert any(u["action"] == "delete" for u in r["unsupported_claims"])
    assert "복용하세요" not in r["verified_answer"]


def test_emergency_reassurance_deleted():
    r = verify_citations("응급실에 안 가도 됩니다.")
    assert any(u["reason"] == "unsafe_reassurance" for u in r["unsupported_claims"])
    assert r["overall_pass"] is False


def test_questions_not_claims():
    # 문진 질문은 claim이 아니므로 인용 불필요
    r = verify_citations("증상이 언제부터 시작되셨나요? 복용 중인 약이 있으신가요?")
    assert r["unsupported_claims"] == []
    assert r["overall_pass"] is True


def test_disclaimer_not_claim():
    r = verify_citations("본 정보는 참고용이며, 정확한 진단·치료는 의료진과 상담하세요.")
    assert r["unsupported_claims"] == []


def test_out_of_range_citation():
    r = verify_citations("이 증상은 탈수와 관련된 질환일 가능성이 있습니다 [E5].", evidence_ids=["E1", "E2"])
    assert any(u["reason"] == "citation_not_supporting" for u in r["unsupported_claims"])


def test_overclaim_flagged():
    r = verify_citations("이 방법으로 100% 완치를 보장합니다.")
    assert any(u["reason"] == "overclaim" for u in r["unsupported_claims"])


if __name__ == "__main__":
    tests = [
        test_cited_claim_passes, test_uncited_claim_flagged, test_diagnosis_assertion_deleted,
        test_prescription_deleted, test_emergency_reassurance_deleted, test_questions_not_claims,
        test_disclaimer_not_claim, test_out_of_range_citation, test_overclaim_flagged,
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
