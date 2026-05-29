"""seed_dur.build_dur_documents 단위 테스트 (ingest 글루, 키/DB 불필요)."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from seed_dur import build_dur_documents

_CHUNKS = [
    {"dur_category": "병용금기", "content": "[DUR 병용금기] 와파린 + 아스피린: 출혈 위험",
     "risk_tags": ["drug_interaction"], "population_tags": []},
    {"dur_category": "병용금기", "content": "[DUR 병용금기] 심바스타틴 + 이트라코나졸: 횡문근융해",
     "risk_tags": ["drug_interaction"], "population_tags": []},
    {"dur_category": "임부금기", "content": "[DUR 임부금기] 이부프로펜: 임신 말기 금기",
     "risk_tags": ["pregnancy_contraindication"], "population_tags": ["pregnancy"]},
]


def test_groups_by_category():
    docs = build_dur_documents(_CHUNKS)
    cats = {d["metadata"]["dur_category"] for d in docs}
    assert cats == {"병용금기", "임부금기"}


def test_usjnt_doc_aggregates_items():
    docs = build_dur_documents(_CHUNKS)
    usjnt = [d for d in docs if d["metadata"]["dur_category"] == "병용금기"][0]
    assert usjnt["item_count"] == 2
    assert "와파린" in usjnt["content_md"] and "심바스타틴" in usjnt["content_md"]


def test_metadata_source_priority_and_type():
    docs = build_dur_documents(_CHUNKS)
    for d in docs:
        assert d["source_id"] == "mfds_dur"
        assert d["metadata"]["source_priority"] == 1
        assert d["metadata"]["chunk_type"] == "contraindication"
        assert d["metadata"]["evidence_level"] == "A"
        assert d["regulatory_korea"] is True
        assert d["evidence_country"] if "evidence_country" in d else True  # optional


def test_pregnancy_population_tag_propagated():
    docs = build_dur_documents(_CHUNKS)
    pwnm = [d for d in docs if d["metadata"]["dur_category"] == "임부금기"][0]
    assert "pregnancy" in pwnm["metadata"]["population_tags"]
    assert pwnm["evidence_topic"] == "pregnancy_drug_safety"


def test_empty_input():
    assert build_dur_documents([]) == []


if __name__ == "__main__":
    tests = [
        test_groups_by_category, test_usjnt_doc_aggregates_items,
        test_metadata_source_priority_and_type, test_pregnancy_population_tag_propagated,
        test_empty_input,
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
