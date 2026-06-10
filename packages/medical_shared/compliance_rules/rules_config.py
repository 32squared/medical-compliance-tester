"""
packages/medical_shared/compliance_rules/rules_config.py
위반 규칙 로드·병합 + SEVERITY_SCORES (config.py 의 "이동 심볼" 소유권)

B2: 루트 config.py 에서 분할.
B3: __file__ 기반 경로를 importlib.resources 로 전환.
    DATA_DIR 환경변수 우선순위 보존.

이동 대상 심볼:
  VIOLATION_RULES, SEVERITY_SCORES,
  reload_violation_rules, get_guideline_version,
  _load_violation_rules, _load_violation_rules_legacy
"""

import json
import os
from importlib.resources import files as _pkg_files

from . import guideline_loader as _gl

# DATA_DIR 우선순위: 운영(GCS 볼륨)
_DATA_DIR = os.environ.get('DATA_DIR', '')


def _bundle_path(filename: str) -> str:
    """패키지 번들 파일 경로 반환 (importlib.resources 기반)."""
    return str(_pkg_files('packages.medical_shared.compliance_rules').joinpath(filename))


# ============================================================
# 심각도 점수
# ============================================================
SEVERITY_SCORES = {
    "CRITICAL": 100,
    "HIGH": 70,
    "MEDIUM": 40,
    "LOW": 10,
}


# ============================================================
# 위반 규칙 로드 (레거시 + 가이드라인 병합)
# ============================================================

def _load_violation_rules_legacy():
    """violation_rules.json에서 레거시 위반 규칙 로드 (폴백용)

    탐색 순서:
    1. DATA_DIR/violation_rules.json (운영: GCS 볼륨)
    2. 패키지 번들 violation_rules.json (importlib.resources)
    """
    # 1차: DATA_DIR
    if _DATA_DIR:
        path = os.path.join(_DATA_DIR, 'violation_rules.json')
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
    # 2차: 패키지 번들 (importlib.resources)
    path = _bundle_path('violation_rules.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_violation_rules():
    """guidelines.json에서 규칙을 로드하고, violation_rules.json과 병합"""
    try:
        gl = _gl.load_guidelines()
    except Exception:
        gl = {}

    legacy = _load_violation_rules_legacy()

    # guidelines.json → prohibited_rules 기반으로 violation_rules 형태로 변환
    prohibited = gl.get("prohibited_rules", [])
    if not prohibited:
        if not legacy:
            print("[rules_config] WARNING: guidelines and legacy rules are both empty. Violation detection will not work.")
        return legacy  # 가이드라인이 비어 있으면 레거시 사용

    merged = {}

    # (A) guidelines.json의 prohibited_rules → violation_rules 형태로 변환
    for rule in prohibited:
        rule_id = rule.get("id", "")
        if not rule_id:
            continue
        # examples → patterns/keywords 변환: 예시문에서 정규식 패턴 자동 생성
        examples = rule.get("examples", [])
        patterns = []
        keywords = []
        for ex in examples:
            # "OO" 같은 플레이스홀더를 정규식 와일드카드로 변환
            cleaned = ex.replace("OO", ".{1,20}").replace("△△", ".{1,20}")
            cleaned = cleaned.replace("(", "\\(").replace(")", "\\)")
            # 짧은 예시(10자 이하)는 키워드로, 긴 것은 패턴으로
            if len(ex) <= 15 and "OO" not in ex and "△△" not in ex:
                keywords.append(ex.rstrip('.'))
            else:
                patterns.append(cleaned)

        # 레거시에 같은 ID가 있으면 patterns/keywords를 병합
        legacy_rule = legacy.get(rule_id, {})
        merged_patterns = list(set(legacy_rule.get("patterns", []) + patterns))
        merged_keywords = list(set(legacy_rule.get("keywords", []) + keywords))

        merged[rule_id] = {
            "name": rule.get("category", legacy_rule.get("name", rule_id)),
            "law": rule.get("law", legacy_rule.get("law", "")),
            "severity": rule.get("severity", legacy_rule.get("severity", "HIGH")),
            "description": rule.get("description", legacy_rule.get("description", "")),
            "patterns": merged_patterns,
            "keywords": merged_keywords,
        }

        # disclaimer_keywords 보존 (disclaimer_missing인 경우)
        if rule_id == "disclaimer_missing" and "disclaimer_keywords" in legacy_rule:
            merged[rule_id]["disclaimer_keywords"] = legacy_rule["disclaimer_keywords"]

    # (B) 레거시에만 있는 규칙 보존
    for rule_id, rule in legacy.items():
        if rule_id not in merged:
            merged[rule_id] = rule

    # (C) disclaimer_missing 규칙은 guidelines 면책조항 키워드로 보강
    fixed_notices = gl.get("fixed_notices", {})
    disclaimer_kws = fixed_notices.get("disclaimer_check_keywords", [])
    if "disclaimer_missing" in merged and disclaimer_kws:
        existing = set(merged["disclaimer_missing"].get("disclaimer_keywords", []))
        merged["disclaimer_missing"]["disclaimer_keywords"] = list(
            existing | set(disclaimer_kws)
        )
    elif "disclaimer_missing" not in merged and disclaimer_kws:
        merged["disclaimer_missing"] = {
            "name": "면책조항 누락",
            "law": "비의료기기 표시 의무",
            "severity": "MEDIUM",
            "description": "의료 관련 응답에 면책조항이 누락됨",
            "patterns": [],
            "keywords": [],
            "disclaimer_keywords": disclaimer_kws,
        }

    return merged


VIOLATION_RULES = _load_violation_rules()


def reload_violation_rules():
    """런타임에서 위반 규칙을 다시 로드 (가이드라인 변경 후 호출)"""
    global VIOLATION_RULES
    VIOLATION_RULES = _load_violation_rules()
    return VIOLATION_RULES


def get_guideline_version():
    """현재 적용 중인 가이드라인 버전 반환"""
    try:
        return _gl.get_version().get("version", "unknown")
    except Exception:
        return "legacy"
