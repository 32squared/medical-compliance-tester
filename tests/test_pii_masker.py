"""
pii_masker 단위 테스트 (작업지시서 §7.2 / EPIC D-1).
pytest stdout 캡처 충돌 회피 위해 __main__ 직접 실행 지원.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pii_masker import mask_pii, is_masking_required


def _types(result):
    return {d["type"] for d in result["detected_items"]}


def test_rrn_masked():
    r = mask_pii("제 주민번호는 900101-1234567 입니다")
    assert "rrn" in _types(r), r
    assert "900101-1234567" not in r["masked_text"]
    assert "[RRN]" in r["masked_text"]


def test_phone_masked():
    r = mask_pii("연락처는 010-1234-5678 이에요")
    assert "phone" in _types(r)
    assert "010-1234-5678" not in r["masked_text"]


def test_email_masked():
    r = mask_pii("이메일 hong.gildong@example.com 으로 보내주세요")
    assert "email" in _types(r)
    assert "hong.gildong@example.com" not in r["masked_text"]


def test_patient_id_masked():
    r = mask_pii("환자번호 12345678 조회해주세요")
    assert "patient_id" in _types(r)
    assert "12345678" not in r["masked_text"]
    assert "환자번호" in r["masked_text"]  # 라벨은 유지


def test_name_masked():
    r = mask_pii("제 이름은 홍길동입니다. 머리가 아파요.")
    assert "name" in _types(r)
    assert "홍길동" not in r["masked_text"]
    assert "머리가 아파요" in r["masked_text"]  # 증상은 유지


def test_health_signal_flag():
    r = mask_pii("가슴이 아프고 혈압이 높아요")
    assert r["contains_sensitive_health_info"] is True


def test_clean_text_unchanged():
    r = mask_pii("두통이 3일째 지속됩니다. 어떻게 해야 하나요?")
    assert r["detected_items"] == []
    assert r["masked_text"] == "두통이 3일째 지속됩니다. 어떻게 해야 하나요?"
    assert r["safe_for_llm"] is True


def test_is_masking_required():
    assert is_masking_required("010-1234-5678") is True
    assert is_masking_required("주민번호 900101-1234567") is True
    assert is_masking_required("그냥 머리가 아파요") is False


def test_symptom_preserved_with_pii():
    """PII는 마스킹하되 의료 맥락(증상)은 보존되어야 한다."""
    r = mask_pii("홍길동입니다. 010-1234-5678. 어제부터 가슴이 답답하고 숨이 차요.")
    assert "가슴이 답답하고 숨이 차요" in r["masked_text"]
    assert "010-1234-5678" not in r["masked_text"]
    assert "홍길동" not in r["masked_text"]


if __name__ == "__main__":
    tests = [
        test_rrn_masked, test_phone_masked, test_email_masked,
        test_patient_id_masked, test_name_masked, test_health_signal_flag,
        test_clean_text_unchanged, test_is_masking_required,
        test_symptom_preserved_with_pii,
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
