"""
medical_rag_pipeline end-to-end 테스트 (스펙 §0 흐름 / §18 MVP 완료 정의).
MockLLM + mock retrieve로 OpenAI/DB 없이 전체 파이프라인 검증.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from medical_rag_pipeline import process_medical_query


def _mock_retrieve(masked_q, routing):
    # KR 공식 출처 청크 1개 반환
    return [{
        "chunk_id": "c1", "source_id": "kdca", "content": "발열은 감염 등 다양한 원인으로 나타날 수 있는 증상입니다.",
        "title": "발열 안내", "jurisdiction": "KR", "score": 0.7,
    }]


def test_pipeline_normal_flow():
    r = process_medical_query("열이 나고 머리가 아파요", retrieve_fn=_mock_retrieve)
    assert r["answer_id"].startswith("ans_")
    assert "classifying" in r["stages"] and "evidence_pack" in r["stages"]
    assert r["evidence_pack"]["evidence_items"], "근거 있어야"
    assert r["citation"]["overall_pass"] in (True, False)
    assert r["audit"]["prompt_version"] == "rag-spec-v1"
    assert "[E1]" in r["answer"]  # MockLLM이 [E1] 인용


def test_pipeline_pii_masked_before_processing():
    r = process_medical_query("홍길동입니다. 010-1234-5678. 머리가 아파요.", retrieve_fn=_mock_retrieve)
    assert "010-1234-5678" not in r["masked_question"]
    assert r["pii"]["detected"], "PII 탐지되어야"


def test_pipeline_emergency_safety_first():
    r = process_medical_query("갑자기 가슴이 쥐어짜듯 아프고 식은땀이 나요", retrieve_fn=_mock_retrieve)
    assert r["safety_level"] == "emergency_guidance"
    assert "119" in r["answer"] or "응급실" in r["answer"]
    assert r["review"]["needs_review"] is True


def test_pipeline_crisis_guidance():
    r = process_medical_query("죽고 싶다는 생각이 계속 들어요", retrieve_fn=_mock_retrieve)
    assert r["safety_level"] == "crisis_guidance"
    assert "109" in r["answer"] or "1577-0199" in r["answer"]


def test_pipeline_insufficient_evidence():
    # retrieve가 빈 결과 → insufficient
    r = process_medical_query("아주 희귀한 질문", retrieve_fn=lambda q, rt: [])
    assert r["safety_level"] == "insufficient_information"
    assert "출처가 부족" in r["answer"]


def test_pipeline_drug_routes_to_dur():
    r = process_medical_query("와파린이랑 아스피린 같이 먹어도 돼요?", retrieve_fn=_mock_retrieve)
    assert r["classification"]["intent"] == "drug_safety"
    assert "MFDS_DUR" in r["routing"]["primary_sources"]
    assert r["review"]["assignee_role"] == "pharmacist"


def test_pipeline_audit_complete():
    r = process_medical_query("독감 예방접종 정보", retrieve_fn=_mock_retrieve)
    a = r["audit"]
    for k in ("answer_id", "evidence_ids", "model_version", "prompt_version"):
        assert k in a, f"감사 필드 누락: {k}"


if __name__ == "__main__":
    tests = [
        test_pipeline_normal_flow, test_pipeline_pii_masked_before_processing,
        test_pipeline_emergency_safety_first, test_pipeline_crisis_guidance,
        test_pipeline_insufficient_evidence, test_pipeline_drug_routes_to_dur,
        test_pipeline_audit_complete,
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
