"""
collect_public_kb.precheck_violations() 단위 테스트.
KB 콘텐츠 컨텍스트(공공 출처)와 환자 응답 컨텍스트 분기를 검증.
Option B: prescription 카테고리 명령형/설명형 구분 완화 검증 포함.
"""

import sys
import os

# 프로젝트 루트를 sys.path에 추가
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from collect_public_kb import (
    precheck_violations,
    KB_CONTENT_VIOLATION_CATEGORIES,
    PATIENT_RESPONSE_VIOLATION_CATEGORIES,
    _is_prescription_kb_safe,
    _KB_COMMAND_FORM_RE,
)


def test_public_source_informational_passes():
    """공공 출처의 정보성 질환 설명 — 위반 없음 (통과)."""
    text = "당뇨병은 인슐린 분비 부족으로 발생하는 만성질환입니다."
    violations = precheck_violations(text, source_id="health_kdca")
    assert violations == [], (
        f"공공 출처 정보성 문서가 잘못 차단됨: {violations}"
    )


def test_public_source_prescription_blocked():
    """공공 출처라도 처방 지시 패턴은 차단."""
    text = "이 환자는 메트포르민 500mg을 복용하세요."
    violations = precheck_violations(text, source_id="health_kdca")
    assert len(violations) > 0, (
        "처방 지시 패턴이 공공 출처에서 차단되지 않음"
    )


def test_patient_response_diagnosis_blocked():
    """환자 응답 모드 (source_id=None) — 진단 단정은 차단."""
    text = "당신은 당뇨병입니다."
    violations = precheck_violations(text, source_id=None)
    assert len(violations) > 0, (
        "환자 응답 모드에서 진단 단정 패턴이 차단되지 않음"
    )


def test_public_source_diagnosis_not_blocked():
    """공공 출처 정보성 문서에서 질환명 언급은 차단하지 않음."""
    text = "고혈압은 수축기 혈압이 140mmHg 이상인 상태를 말합니다. 예방을 위해 운동을 권장합니다."
    violations = precheck_violations(text, source_id="nemc")
    assert violations == [], (
        f"공공 출처 질환 설명이 잘못 차단됨: {violations}"
    )


def test_public_source_false_efficacy_blocked():
    """공공 출처라도 허위/과대 효능 주장("100% 완치")은 차단."""
    text = "이 방법만으로 100% 완치됩니다."
    violations = precheck_violations(text, source_id="mfds")
    assert len(violations) > 0, (
        "공공 출처에서 허위 효능 패턴이 차단되지 않음"
    )


def test_category_set_sizes():
    """KB_CONTENT와 PATIENT_RESPONSE 카테고리 집합 크기 검증."""
    assert len(KB_CONTENT_VIOLATION_CATEGORIES) == 3, (
        f"KB_CONTENT 카테고리가 3개여야 함: {KB_CONTENT_VIOLATION_CATEGORIES}"
    )
    assert len(PATIENT_RESPONSE_VIOLATION_CATEGORIES) == 12, (
        f"PATIENT_RESPONSE 카테고리가 12개여야 함: {PATIENT_RESPONSE_VIOLATION_CATEGORIES}"
    )


# ── Option B 신규 테스트 ──────────────────────────────────────────────────────

def test_kb_content_informational_examination_passes():
    """
    [Option B] 검사/처방 설명 문서가 차단되지 않아야 한다.
    "의사가 처방합니다", "복용합니다", "하루 N회" 등 설명형 표현은 허용.
    """
    informational_texts = [
        "갑상선 검사는 의사가 진단을 내리기 위해 시행하는 검사입니다.",
        "고혈압 치료제로 암로디핀을 복용합니다. 하루 1회 투여가 일반적입니다.",
        "인슐린은 당뇨병 환자에게 투여합니다. 의사의 처방에 따라 사용합니다.",
        "해열제는 38도 이상의 발열 시 사용됩니다. 타이레놀(아세트아미노펜)이 대표적입니다.",
        "항생제는 세균 감염 치료에 사용됩니다. 의사가 처방한 경우에만 복용합니다.",
        "메트포르민은 당뇨병 1차 치료제로 복용합니다. 식사와 함께 복용하는 것이 권장됩니다.",
        "하루 3번 식후에 복용합니다. 복용 후 검사 결과 변화를 관찰합니다.",
    ]
    for text in informational_texts:
        violations = precheck_violations(text, source_id="health_kdca")
        assert violations == [], (
            f"정보성 검사/처방 설명이 잘못 차단됨: {text!r}\n위반: {violations}"
        )


def test_kb_content_command_form_blocked():
    """
    [Option B] 명령형 처방 지시는 공공 출처에서도 여전히 차단되어야 한다.
    "복용하세요", "드세요", "투여하세요" 등 직접 명령형은 차단 유지.
    """
    command_texts = [
        "메트포르민 500mg을 복용하세요.",
        "이 약을 복용하세요. 하루 2번 식후에 드세요.",
        "인슐린을 투여하세요. 의사 지시 없이 용량을 변경하지 마세요.",
        "타이레놀을 복용하세요. 하루 3번 이상 드시기 바랍니다.",
    ]
    for text in command_texts:
        violations = precheck_violations(text, source_id="health_kdca")
        assert len(violations) > 0, (
            f"명령형 처방 지시가 공공 출처에서 차단되지 않음: {text!r}"
        )


def test_is_prescription_kb_safe_descriptive():
    """
    _is_prescription_kb_safe: 설명형 context는 safe=True 반환.
    """
    # 설명형 표현 — 명령형 서술어 없음
    safe_snippets = [
        "암로디핀을 복용합니다",
        "인슐린을 투여합니다",
        "하루 1회 복용하는 것이 일반적입니다",
        "의사가 처방하는 약물",
        "복용 후 검사 결과 변화를 확인합니다",
        "항생제는 의사의 처방에 따라 복용합니다",
    ]
    for text in safe_snippets:
        result = _is_prescription_kb_safe(text, 0, len(text))
        assert result is True, (
            f"설명형 표현이 KB-safe로 판별되지 않음: {text!r}"
        )


def test_is_prescription_kb_safe_command():
    """
    _is_prescription_kb_safe: 명령형 context는 safe=False 반환.
    """
    # 명령형 표현 — 차단 필요
    command_snippets = [
        "타이레놀을 복용하세요",
        "메트포르민 500mg을 복용하세요",
        "하루 2번 드세요",
        "인슐린을 투여하세요",
        "약을 시작하세요",
        "항생제를 드시기 바랍니다",
    ]
    for text in command_snippets:
        result = _is_prescription_kb_safe(text, 0, len(text))
        assert result is False, (
            f"명령형 표현이 KB-safe로 잘못 판별됨: {text!r}"
        )


def test_patient_response_prescription_still_blocked():
    """
    [Option B 비적용] 환자 응답 컨텍스트(source_id=None)에서는
    설명형 처방 표현도 기존대로 차단되어야 한다. (Option B는 KB 전용)
    """
    text = "이 약을 복용하세요. 메트포르민 500mg을 처방합니다."
    violations = precheck_violations(text, source_id=None)
    assert len(violations) > 0, (
        "환자 응답 컨텍스트에서 처방 표현이 차단되지 않음"
    )


if __name__ == "__main__":
    tests = [
        test_public_source_informational_passes,
        test_public_source_prescription_blocked,
        test_patient_response_diagnosis_blocked,
        test_public_source_diagnosis_not_blocked,
        test_public_source_false_efficacy_blocked,
        test_category_set_sizes,
        # Option B 신규 테스트
        test_kb_content_informational_examination_passes,
        test_kb_content_command_form_blocked,
        test_is_prescription_kb_safe_descriptive,
        test_is_prescription_kb_safe_command,
        test_patient_response_prescription_still_blocked,
    ]

    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n결과: {passed}/{len(tests)} 통과")
    sys.exit(0 if failed == 0 else 1)
