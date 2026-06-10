"""
packages/medical_shared/compliance_rules/consultation_loader.py
consultation_checklists.json 단일 로더

B2: 루트 consultation_loader.py 에서 이동.
B3: __file__ 기반 경로를 importlib.resources 로 전환.
    DATA_DIR 환경변수 우선순위 보존.
"""

import os
import json
from importlib.resources import files as _pkg_files


def _bundle_path(filename: str) -> str:
    """패키지 번들 파일 경로 반환 (importlib.resources 기반)."""
    return str(_pkg_files('packages.medical_shared.compliance_rules').joinpath(filename))


# DATA_DIR 설정 시 그쪽에서 먼저 탐색, 없으면 패키지 번들
_DATA_DIR = os.environ.get('DATA_DIR', '')

def _checklists_path() -> str:
    if _DATA_DIR:
        p = os.path.join(_DATA_DIR, 'consultation_checklists.json')
        if os.path.exists(p):
            return p
    return _bundle_path('consultation_checklists.json')

CHECKLISTS_PATH = _checklists_path()


def load_checklists_raw(path=None):
    """consultation_checklists.json 을 원본 list 그대로 로드. 실패/비-list 시 []."""
    p = path or CHECKLISTS_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def load_checklists_by_symptom(path=None):
    """symptom_key 로 키잉된 {"symptoms": {symptom_key: item}} 형태로 로드.
    파일이 이미 {"symptoms": {...}} dict 면 그대로 반환. 실패 시 {"symptoms": {}}.
    (rag_engine 의 기존 _load_checklists 동작을 그대로 보존)"""
    p = path or CHECKLISTS_PATH
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {"symptoms": {}}
    if isinstance(raw, list):
        return {
            "symptoms": {
                item["symptom_key"]: item
                for item in raw
                if isinstance(item, dict) and "symptom_key" in item
            }
        }
    if isinstance(raw, dict) and "symptoms" in raw:
        return raw
    return {"symptoms": {}}
