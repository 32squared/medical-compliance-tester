# -*- coding: utf-8 -*-
"""v3 시험 세트 — 구성(build_v3_set) 과 반영(apply_scenario_set)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import apply_scenario_set as ap  # noqa: E402
import build_v3_set as bs  # noqa: E402


def _r(i, mode, enabled=True, expected="free", dup=None, **cls):
    return {"id": i, "enabled": enabled, "retired": False, "expected": expected, "dup_group": dup,
            "category": "x", "cls": dict({"mode": mode, "usable": True}, **cls)}


def test_build_cells_dedupe_retire_and_gaps():
    rows = [_r(f"P{i}", "phr", intent="trend", expected="v3_rubric", dup="g0") for i in range(3)]
    rows += [_r(f"S{i}", "symptom", symptom_key="headache", branch="응급") for i in range(10)]
    rows += [_r("D1", "general", targets=["LG-01"], dup="g1", expected="none"),
             _r("D2", "general", targets=["LG-01"], dup="g1", expected="free"),
             _r("L1", "general", targets=["LG-01", "LG-07"]),
             _r("G1", "general"), _r("HB-1", "hb"), _r("OFF", "general", enabled=False),
             _r("BAD", "general", usable=False)]
    p = bs.build({"rows": rows}, symptom_keys=("headache",))
    t = p["tags"]
    assert all(f"P{i}" in t for i in range(3))                 # PHR 은 중복이어도 모두
    assert sum(1 for i in range(10) if f"S{i}" in t) == 8      # 응급 칸 최대 8
    assert "D2" in t and "D1" not in t and "D1" in p["dropped_dup"]   # 기대동작 형식 좋은 대표
    assert p["cells"]["legal:LG-07"] == 1                      # 후보가 적은 규칙 칸에 센다
    assert "sym:headache" in t["S0"] and "branch:응급" in t["S0"] and "zone:symptom" in t["S0"]
    assert "target:LG-01" in t["L1"] and "target:LG-07" in t["L1"]
    assert "HB-1" not in p["retire"] and "OFF" not in p["retire"] and "BAD" in p["not_eligible"]
    assert {"BAD", "D1"} <= set(p["retire"]) and sum(1 for i in range(10) if f"S{i}" in p["retire"]) == 2
    gaps = {(g["zone"], g["key"]): g for g in p["gaps"]}
    assert gaps[("phr", "trend")]["need"] == 17
    assert gaps[("legal", "LG-01")]["have"] == 2               # 세트 전체에서 유도 문항 수
    assert gaps[("symptom_other", "headache")]["need"] == 4
    assert ("symptom_emergency", "headache") not in gaps


class _DB:
    def __init__(self, rows):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.calls = []

    def get_scenarios(self):
        return {"scenarios": [dict(r) for r in self.rows.values()]}

    def update_scenario(self, sid, data):
        self.calls.append((sid, data))
        self.rows[sid].update(data)


def _plan(tmp_path, **kw):
    p = dict({"set": "v3set-1", "min_total": 1,
              "tags": {"A": ["set:v3set-1", "zone:symptom", "sym:headache", "branch:응급"]},
              "retire": ["B"]}, **kw)
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    return str(f)


def test_apply_tags_columns_and_retire(tmp_path):
    db = _DB([{"id": "A", "enabled": False, "tags": ["set:old", "keep", "retired:v3set-1-unselected"],
               "symptomKey": "", "branch": ""},
              {"id": "B", "enabled": True, "tags": ["qtype:T3"]}])
    logs = []
    assert ap.run(_plan(tmp_path), db=db, dry_run=True, log=logs.append) == 0 and db.calls == []
    assert ap.run(_plan(tmp_path), db=db, log=logs.append) == 0
    a, b = db.rows["A"], db.rows["B"]
    assert a["enabled"] is True and a["symptomKey"] == "headache" and a["branch"] == "응급"
    assert a["tags"] == ["set:v3set-1", "zone:symptom", "sym:headache", "branch:응급", "keep"]
    assert b["enabled"] is False and b["tags"] == ["retired:v3set-1-unselected", "qtype:T3"]
    db.calls.clear()
    assert ap.run(_plan(tmp_path), db=db, log=logs.append) == 0 and db.calls == []   # 다시 돌려도 그대로


def test_apply_stops_on_missing_or_small(tmp_path):
    db = _DB([{"id": "A", "enabled": True, "tags": []}])
    assert ap.run(_plan(tmp_path), db=db, log=lambda *_: None) == 3 and db.calls == []
    db = _DB([{"id": "A", "enabled": True, "tags": []}, {"id": "B", "enabled": True, "tags": []}])
    assert ap.run(_plan(tmp_path, min_total=1000), db=db, log=lambda *_: None) == 4 and db.calls == []


def test_merge_tags_limit():
    assert len(ap.merge_tags([f"t{i}" for i in range(30)], ["set:x"])) == 20


def test_committed_plan_meets_minimum_and_has_no_text():
    p = json.load(open(os.path.join(ROOT, "scripts", "v3set_1_plan.json"), encoding="utf-8"))
    assert p["total"] >= 1000 and len(p["tags"]) == p["total"]
    assert not set(p["tags"]) & set(p["retire"])
    assert not any(k in p for k in ("rows", "prompt"))


def test_entrypoint_mode():
    s = open(os.path.join(ROOT, "entrypoint.sh"), encoding="utf-8").read()
    assert 'RUN_MODE" = "apply_scenario_set"' in s and "scripts/apply_scenario_set.py" in s
