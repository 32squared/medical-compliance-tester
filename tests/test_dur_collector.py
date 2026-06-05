"""dur_collector 파싱·청크매핑 단위 테스트 (스펙 §3.2 / EPIC A-3). fixture 기반, 네트워크 불필요."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from dur_collector import parse_dur_items, dur_item_to_chunk, DUR_CATEGORIES

# data.go.kr 표준 응답 fixture (병용금기)
_FIXTURE_USJNT = {
    "body": {
        "items": [
            {"INGR_KOR_NAME": "와파린", "MIXTURE_INGR_KOR_NAME": "아스피린",
             "PROHBT_CONTENT": "출혈 위험 증가로 병용 금기", "ITEM_NAME": "쿠마딘정"},
            {"INGR_KOR_NAME": "심바스타틴", "MIXTURE_INGR_KOR_NAME": "이트라코나졸",
             "PROHBT_CONTENT": "횡문근융해증 위험"},
        ]
    }
}
_FIXTURE_PWNM = {
    "body": {"items": {"item": {"INGR_KOR_NAME": "이부프로펜",
                                "PROHBT_CONTENT": "임신 말기 투여 금기"}}}
}


def test_parse_list():
    items = parse_dur_items(_FIXTURE_USJNT)
    assert len(items) == 2


def test_parse_single_item_dict():
    items = parse_dur_items(_FIXTURE_PWNM)
    assert len(items) == 1
    assert items[0]["INGR_KOR_NAME"] == "이부프로펜"


def test_usjnt_chunk_mapping():
    item = parse_dur_items(_FIXTURE_USJNT)[0]
    c = dur_item_to_chunk("병용금기", item)
    assert c["source_id"] == "mfds_dur"
    assert c["source_priority"] == 1
    assert c["chunk_type"] == "contraindication"
    assert c["evidence_level"] == "A"
    assert "drug_interaction" in c["risk_tags"]
    assert "와파린" in c["content"] and "아스피린" in c["content"]


def test_pwnm_population_tag():
    item = parse_dur_items(_FIXTURE_PWNM)[0]
    c = dur_item_to_chunk("임부금기", item)
    assert "pregnancy" in c["population_tags"]
    assert "이부프로펜" in c["content"]


def test_elderly_population_tag():
    c = dur_item_to_chunk("노인주의", {"INGR_KOR_NAME": "디아제팜", "PROHBT_CONTENT": "낙상 위험"})
    assert "elderly" in c["population_tags"]


def test_categories_have_ops():
    for cat, meta in DUR_CATEGORIES.items():
        assert meta["op"].startswith("get")
        assert "risk" in meta


def test_empty_item_returns_none():
    assert dur_item_to_chunk("병용금기", {}) is None


if __name__ == "__main__":
    tests = [
        test_parse_list, test_parse_single_item_dict, test_usjnt_chunk_mapping,
        test_pwnm_population_tag, test_elderly_population_tag, test_categories_have_ops,
        test_empty_item_returns_none,
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
