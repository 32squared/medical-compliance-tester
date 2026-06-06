"""
consultation_loader.py — consultation_checklists.json 단일 로더 (저장소 분리 Phase 2-B)
=========================================================================================
호스트(db.py, collect_public_kb.py)와 RAG(rag_engine.py)가 각자 하드코딩 경로로
consultation_checklists.json 을 로드하던 것을 단일 모듈로 통일한다.
반환 형태는 호출처에 따라 다르므로 두 함수로 제공한다(형태별 동작 보존).

향후(Phase 4): compliance-rules 공유 패키지에 동봉.
"""

import os
import json

# 단일 경로 소스 (하드코딩 4곳 제거)
CHECKLISTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "consultation_checklists.json"
)


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
