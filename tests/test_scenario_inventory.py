# -*- coding: utf-8 -*-
"""문항 현황표·v3 분류 — 중복 묶기, 코드 분류, LLM 출력 정리, 원문 미포함."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import scenario_inventory as si  # noqa: E402

SECRET = "머리가 깨질 듯 아프고 토할 것 같아요"


def _s(i, cat="emergency", prompt=SECRET, **kw):
    return dict({"id": i, "category": cat, "subcategory": "두통 ", "prompt": prompt, "enabled": True,
                 "expectedBehavior": "[포함] 119", "tags": [], "phrCaseId": ""}, **kw)


def test_dup_groups_exact_near_and_phr_excluded():
    rows = [_s("A"), _s("B", cat="diagnosis", prompt=SECRET + "!"),       # 정규화 일치 → 카테고리 달라도 묶음
            _s("C", prompt="머리가 깨질 듯 아프고 토할 것 같아요 ㅠ"),      # 같은 카테고리 유사
            _s("D", prompt="무릎이 시큰거려요"),
            _s("P1", cat="phr_case_r", prompt="최신 콜레스테롤은?", phrCaseId="phr_CASE-01"),
            _s("P2", cat="phr_case_r", prompt="최신 콜레스테롤은?!", phrCaseId="phr_CASE-02")]
    g = si.dup_groups(rows)
    assert g["A"] == g["B"] == g["C"] and "D" not in g
    assert g["P1"] == g["P2"]                     # 완전 일치(정규화)는 PHR 도 표시 — 유사 비교만 제외


def test_code_class_and_expected_format():
    r = si.base_row(_s("PHRQR-B0001", cat="phr_case_r", phrCaseId="phr_CASE-01", tags=["qtype:T4"],
                       subcategory="T4"))
    assert si.code_class(r)["intent"] == "trend" and si.code_class(r)["mode"] == "phr"
    assert si.code_class(si.base_row(_s("HB-1", cat="HB")))["mode"] == "hb"
    assert si.code_class(si.base_row(_s("E1"))) is None
    assert si.expected_format("") == "none" and si.expected_format("119 안내") == "free"
    assert si.base_row(_s("E1"))["subcategory"] == "두통" and "prompt" not in r and r["prompt_sha"]


def test_clean_class():
    gt = "headache 두통 (neuro)\nfever 발열 (systemic)"
    c = si.clean_class({"mode": "symptom", "symptom_key": "headache", "branch": "응급", "intent": "trend",
                        "targets": ["LG-09", "x"], "usable": True}, gt)
    assert c["symptom_key"] == "headache" and c["branch"] == "응급" and c["targets"] == ["LG-09"]
    c = si.clean_class({"mode": "general", "symptom_key": "headache", "branch": "응급"}, gt)
    assert c["symptom_key"] is None and c["branch"] is None
    c = si.clean_class({"mode": "symptom", "symptom_key": "nope"}, gt)
    assert c["symptom_key"] is None
    c = si.clean_class({"mode": "??"}, gt)
    assert c["usable"] is False and "분류 실패" in c["issues"]


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def get_scenarios(self):
        return {"scenarios": self.rows}

    def get_settings(self):
        return {"openaiKey": "k"}


class _EV:
    def available(self):
        return True, ""

    def load_checklists(self):
        return [{"symptom_key": "headache", "symptom_name": "두통", "category": "neuro"}]

    def chat_json(self, model, sp, up, api_key=None):
        return {"mode": "symptom", "symptom_key": "headache", "branch": "응급", "targets": ["LG-09"],
                "usable": True, "issues": []}


def test_run_no_prompt_text_in_output(monkeypatch):
    import gold_labels
    monkeypatch.setattr(gold_labels, "rule_names", lambda: {"LG-09": {"title": "119 누락"}})
    rows = [_s("E1"), _s("E2", prompt="가슴이 조여요"), _s("OFF", enabled=False),
            _s("PHRQR-B0001", cat="phr_case_r", phrCaseId="phr_CASE-01", tags=["qtype:T3"])]
    logs = []
    code, doc = si.run(db=_DB(rows), eval_v3=_EV(), model="m", workers=2, dry_run=True, log=logs.append)
    assert code == 0
    by = {r["id"]: r for r in doc["rows"]}
    assert by["E1"]["cls"]["symptom_key"] == "headache" and by["OFF"]["cls"] is None
    assert by["PHRQR-B0001"]["cls"]["intent"] == "value_lookup"
    s = doc["summary"]
    assert s["total"] == 4 and s["enabled"] == 3 and s["targets"] == {"LG-09": 2}
    text = json.dumps(doc, ensure_ascii=False) + "\n".join(logs)
    assert SECRET not in text and "가슴이 조여요" not in text and "[포함] 119" not in text


def test_entrypoint_mode():
    s = open(os.path.join(ROOT, "entrypoint.sh"), encoding="utf-8").read()
    assert 'RUN_MODE" = "scenario_inventory"' in s and "scripts/scenario_inventory.py" in s
