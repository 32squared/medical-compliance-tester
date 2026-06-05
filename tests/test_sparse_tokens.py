"""
_korean_meaningful_tokens 단위 테스트 — sparse 검색 0건 버그 수정 회귀.
배경: 기존 ILIKE fallback이 전 어절을 AND로 묶고(조사·어미 포함) tsvector도 plainto AND라
HealthBench 질의 대부분 sparse 0건 → 의미토큰(조사 제거) + OR 매칭으로 수정.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from rag_engine import _korean_meaningful_tokens as T


def test_strips_particles():
    toks = T("가슴이 답답하고 숨이 차요")
    assert "가슴" in toks  # '가슴이' → '가슴'
    assert "답답" in toks  # '답답하고' → '답답'
    assert "가슴이" not in toks


def test_strips_irang_particle():
    toks = T("와파린이랑 아스피린 같이 먹어도 돼요?")
    assert "와파린" in toks  # '와파린이랑' → '와파린'
    assert "아스피린" in toks


def test_drops_stopwords():
    toks = T("그것은 정말 너무 갑자기 아파요")
    assert "그것은" not in toks and "정말" not in toks
    assert "갑자기" not in toks  # stopword


def test_caps_token_count():
    toks = T("머리 가슴 배 다리 팔 목 어깨 무릎 손목 발목 허리")
    assert len(toks) <= 6


def test_dedup():
    toks = T("두통 두통이 두통은")
    assert toks.count("두통") == 1


def test_empty():
    assert T("") == []
    assert T("?? !! ..") == []


def test_no_all_and_zero_bug():
    # 핵심 회귀: 긴 구어체 질의도 의미토큰이 1개 이상 추출되어야 (과거엔 AND로 0건)
    toks = T("50대인데 가슴 한가운데를 쥐어짜는 것처럼 아파요. 왼팔까지 저려요.")
    assert len(toks) >= 2
    assert any(k in toks for k in ("가슴", "왼팔", "쥐어짜는", "한가운데"))


if __name__ == "__main__":
    tests = [
        test_strips_particles, test_strips_irang_particle, test_drops_stopwords,
        test_caps_token_count, test_dedup, test_empty, test_no_all_and_zero_bug,
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
