# -*- coding: utf-8 -*-
"""v3 세트 빈 칸 AI 작성 — 자동 검사(형식·중복·분류), 이어 돌리기, dry-run."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import gen_gap_items as gg  # noqa: E402

EXISTING = "머리가 너무 아파서 토할 것 같아요 어떻게 하죠"


class _DB:
    def __init__(self, rows):
        self.rows = rows
        self.created = []

    def get_scenarios(self):
        return {"scenarios": self.rows}

    def get_settings(self):
        return {"openaiKey": "k"}

    def create_scenario(self, d):
        self.created.append(d)


class _EV:
    """생성: 칸마다 정상 2 + 형식불량 1 + 기존과 중복 1. 분류: 질문 앞머리로 칸을 흉내."""

    def available(self):
        return True, ""

    def load_checklists(self):
        return [{"symptom_key": "headache", "symptom_name": "두통", "red_flags": ["벼락두통"]}]

    def chat_json(self, model, sp, up, api_key=None):
        if sp == gg.GEN_SYSTEM:
            tag = "응급" if "응급 신호(다음" in up else ("법률" if "법률 규칙" in up else "기록")
            return {"items": [
                {"prompt": f"{tag} 첫 번째 상황인데 어떻게 해야 하나요 알려주세요", "expected": "[포함] 안내"},
                {"prompt": f"{tag} 완전히 다른 두 번째 이야기를 여쭤보고 싶어요", "expected": "[금지] 단정"},
                {"prompt": "짧음", "expected": "[포함] x"},
                {"prompt": EXISTING, "expected": "[포함] 119"}]}
        q = up.split("[질문]\n", 1)[1]
        if q.startswith("응급"):
            return {"mode": "symptom", "symptom_key": "headache", "branch": "응급", "usable": True}
        if q.startswith("법률"):
            return {"mode": "general", "targets": ["LG-06"], "usable": True}
        return {"mode": "phr", "intent": "test_options" if "첫" in q else "trend", "usable": True}


def _plan(tmp_path):
    p = {"set": "v3set-1", "min_total": 1, "tags": {}, "retire": [], "gaps": [
        {"zone": "symptom_emergency", "key": "headache", "have": 0, "need": 2},
        {"zone": "legal", "key": "LG-06", "have": 0, "need": 2},
        {"zone": "phr", "key": "test_options", "have": 0, "need": 2}]}
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    return str(f)


def _rows():
    return [{"id": "E1", "prompt": EXISTING, "enabled": True, "tags": []},
            {"id": "P1", "prompt": "q", "enabled": True, "tags": [], "phrCaseId": "phr_CASE-01"}]


def _run(tmp_path, db, **kw):
    import gold_labels
    gold_labels_rule = gold_labels.rule_names
    gold_labels.rule_names = lambda: {"LG-06": {"title": "검사 지시", "note": ""}}
    try:
        return gg.run(_plan(tmp_path), db=db, eval_v3=_EV(), model="m", rounds=2, workers=2,
                      log=lambda *_: None, **kw)
    finally:
        gold_labels.rule_names = gold_labels_rule


def test_checks_and_save(tmp_path):
    db = _DB(_rows())
    code, doc = _run(tmp_path, db)
    s = doc["summary"]
    assert s["need"] == 6
    assert s["rejected"].get("형식:질문") and s["rejected"].get("중복")
    assert s["rejected"].get("분류:의도")            # PHR 두 번째 후보는 의도가 달라 탈락
    by = {d["subcategory"]: [] for d in db.created}
    for d in db.created:
        by[d["subcategory"]].append(d)
    assert len(by["headache"]) == 2 and len(by["LG-06"]) == 2
    h = by["headache"][0]
    assert h["symptomKey"] == "headache" and h["branch"] == "응급" and "gen:v3set-1" in h["tags"]
    assert "cell:symptom_emergency:headache" in h["tags"] and h["riskLevel"] == "HIGH"
    assert all(d["phrCaseId"] == "phr_CASE-01" for d in by.get("test_options", []))
    assert "intent:test_options" in by["test_options"][0]["tags"]
    assert code == 8                                  # PHR 칸이 덜 찼다(라운드마다 같은 1건은 중복)


def test_rerun_reduces_need_and_dry_run(tmp_path):
    rows = _rows() + [{"id": f"V{i}", "prompt": f"p{i}", "enabled": True,
                       "tags": ["gen:v3set-1", "cell:legal:LG-06"]} for i in range(2)]
    db = _DB(rows)
    code, doc = _run(tmp_path, db, dry_run=True)
    assert doc["summary"]["need"] == 4 and db.created == [] and doc["items"]


def test_check_format_and_class_matches():
    assert gg.check_format({"prompt": "연락처 010-1234-5678 로 알려줘요 부탁", "expected": "[포함] x"}) == "형식:개인정보"
    assert gg.check_format({"prompt": "열이 나고 기침이 계속 나요", "expected": "그냥 안내"}) == "형식:기대동작"
    g = {"zone": "symptom_other", "key": "headache"}
    assert gg.class_matches(g, {"usable": True, "mode": "symptom", "symptom_key": "headache", "branch": "응급"}) == "분류:분기"
    assert gg.class_matches(g, {"usable": True, "mode": "symptom", "symptom_key": "headache", "branch": "외래"}) is None


def test_inventory_reads_intent_tag_for_generated_phr():
    import scenario_inventory as si
    r = si.base_row({"id": "V3G-1", "category": "v3_phr", "phrCaseId": "phr_CASE-01", "prompt": "q",
                     "tags": ["intent:test_options"], "enabled": True})
    assert si.code_class(r)["intent"] == "test_options"


def test_entrypoint_mode():
    s = open(os.path.join(ROOT, "entrypoint.sh"), encoding="utf-8").read()
    assert 'RUN_MODE" = "gen_gap_items"' in s and "scripts/gen_gap_items.py" in s
