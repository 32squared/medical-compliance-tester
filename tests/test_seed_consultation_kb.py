"""seed_consultation_kb.build_consultation_documents 단위 테스트 (키/DB 불필요)."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from seed_consultation_kb import build_consultation_documents

_CHK = [
    {
        "symptom_key": "fever", "symptom_name": "발열", "category": "systemic",
        "detail": "미열, 고열, 오한", "department": "내과",
        "required_questions": [{"label": "지속 기간", "keywords": ["지속"]}],
        "red_flags": [{"label": "의식 변화", "keywords": ["의식"]},
                      {"label": "호흡곤란", "keywords": ["호흡곤란"]}],
        "context_questions": [{"label": "복용약물", "keywords": ["약"]}],
        "age_specific": {"child": {"items": ["39도 이상 지속", "경련 여부"]}},
    },
]


def test_one_doc_per_symptom():
    docs = build_consultation_documents(_CHK)
    assert len(docs) == 1
    assert docs[0]["title"] == "증상 문진 가이드 — 발열"


def test_content_has_sections():
    md = build_consultation_documents(_CHK)[0]["content_md"]
    assert "증상 정밀화" in md and "지속 기간" in md
    assert "위험 신호" in md and "의식 변화" in md and "호흡곤란" in md
    assert "환자 맥락" in md and "복용약물" in md
    assert "연령별" in md and "소아" in md and "39도 이상 지속" in md
    assert "내과" in md


def test_metadata():
    d = build_consultation_documents(_CHK)[0]
    assert d["source_id"] == "consultation_checklist"
    assert d["metadata"]["chunk_type"] == "consultation_guide"
    assert d["metadata"]["source_priority"] == 2
    assert d["metadata"]["symptom_key"] == "fever"
    assert "의식 변화" in d["metadata"]["risk_tags"]
    assert d["evidence_topic"] == "consultation_systemic"
    assert d["regulatory_korea"] is False


def test_topic_keywords_include_name():
    d = build_consultation_documents(_CHK)[0]
    assert "발열" in d["topic_keywords"]
    assert "내과" in d["topic_keywords"]


def test_empty():
    assert build_consultation_documents([]) == []


if __name__ == "__main__":
    tests = [test_one_doc_per_symptom, test_content_has_sections, test_metadata,
             test_topic_keywords_include_name, test_empty]
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
