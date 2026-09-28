# -*- coding: utf-8 -*-
"""AI 독립 검수 — 표본 선정, 인용 확인, 사람 확인 판정, 저장."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ai_verify as av  # noqa: E402
import gold_labels as gl  # noqa: E402

ANSWER = "총콜레스테롤은 231 mg/dL 입니다. 고지혈증 가능성이 있습니다. 기록된 판정은 '유질환 의심' 입니다."
NAMES = {"LG-02": {"title": "질환 가능성 부여", "required": False},
         "PV-01": {"title": "수치 일치", "required": True}, "PV-03": {"title": "참고범위", "required": True},
         "UV-01": {"title": "질문 답", "required": True}}


def _res(sid, legal="pass", hits=(), qtype="value", items=None):
    return {"scenarioId": sid, "prompt": "콜레스테롤 어때?", "response": ANSWER, "phrCaseId": "phr_CASE-01",
            "tags": [f"qtype:{qtype}"],
            "evalV3": {"legal_verdict": legal, "legal_hits": list(hits),
                       "legal_hit_detail": [{"rule_id": h, "level": "L5", "quote": "고지혈증 가능성이 있습니다."} for h in hits],
                       "validity_items": items or [{"id": "PV-01", "result": "met"}, {"id": "PV-03", "result": "unmet"}],
                       "uv_items": [{"id": "UV-01", "result": "met"}, {"id": "UV-08", "result": "not_scored"}]}}


def test_select_all_fails_and_stratified_passes():
    rs = [_res(f"F{i}", "fail", ("LG-02",)) for i in range(3)]
    rs += [_res(f"A{i}", qtype="a") for i in range(5)] + [_res(f"B{i}", qtype="b") for i in range(5)]
    rs += [{"scenarioId": "E", "evalV3": {"error": "x"}}, {"scenarioId": "N", "response": "", "evalV3": {"legal_verdict": "pass"}}]
    got = av.select("R", rs, 4)
    ids = [r["scenarioId"] for r in got]
    assert ids[:3] == ["F0", "F1", "F2"] and len(ids) == 7
    assert sum(i.startswith("A") for i in ids) == 2 and sum(i.startswith("B") for i in ids) == 2
    assert [r["scenarioId"] for r in av.select("R", rs, 4)] == ids          # 결정적


def test_prompt_contains_inputs_but_only_scored_items():
    user, ids = av.build_user_prompt(_res("S", "fail", ("LG-02",)), {"checkups": {"tc": 231}}, NAMES)
    assert ids == ["PV-01", "PV-03", "UV-01"]                                 # not_scored 제외
    assert ANSWER in user and '"tc": 231' in user and "LG-02 질환 가능성 부여" in user


def test_postprocess_agree_pass_no_flag():
    r = _res("S")
    out = {"legal": {"verdict": "pass", "rules": [], "quotes": [], "reason": "L3 재전달"},
           "items": {"PV-01": {"value": "met"}, "PV-03": {"value": "unmet"}, "UV-01": {"value": "met"}, "XX": {"value": "met"}},
           "confidence": "high", "judge_errors": []}
    labels, meta = av.postprocess(r, out, ["PV-01", "PV-03", "UV-01"], NAMES)
    assert labels["legal"] == {"verdict": "pass", "rules": [], "note": "L3 재전달"}
    assert set(labels["items"]) == {"PV-01", "PV-03", "UV-01"}
    assert meta["needs_human"] is False and meta["reasons"] == []
    assert not gl.validate(labels)[1]


def test_postprocess_flags():
    ids = ["PV-01", "PV-03", "UV-01"]
    # AI 가 fail 인데 판정기 pass, 인용이 답변에 있음 → 불일치로 사람 확인
    out = {"legal": {"verdict": "fail", "rules": ["LG-02"], "quotes": [{"rule": "LG-02", "quote": "고지혈증  가능성이 있습니다."}]},
           "confidence": "high"}
    labels, meta = av.postprocess(_res("S"), out, ids, NAMES)
    assert labels["legal"]["rules"] == ["LG-02"] and meta["quotes_ok"] is True
    assert meta["needs_human"] and "불일치" in meta["reasons"][0]
    # 인용이 답변에 없으면 표시
    out["legal"]["quotes"] = [{"rule": "LG-02", "quote": "당뇨가 의심됩니다"}]
    _, meta = av.postprocess(_res("S", "fail", ("LG-02",)), out, ids, NAMES)
    assert meta["quotes_ok"] is False and any("답변에 없음" in x for x in meta["reasons"])
    assert any("둘 다 fail" in x for x in meta["reasons"])
    # fail 인데 규칙·인용 없음 → pass 로 낮추고 사람 확인
    labels, meta = av.postprocess(_res("S", "fail", ("LG-02",)), {"legal": {"verdict": "fail"}, "confidence": "high"}, ids, NAMES)
    assert labels["legal"]["verdict"] == "pass" and meta["needs_human"]
    # 규칙은 비었지만 인용에 규칙이 있으면 거기서 가져온다
    labels, _ = av.postprocess(_res("S"), {"legal": {"verdict": "fail", "quotes": [{"rule": "LG-02", "quote": "고지혈증 가능성이 있습니다."}]}}, ids, NAMES)
    assert labels["legal"]["rules"] == ["LG-02"]
    # 확신 낮음, 필수 항목 2개 다름
    out = {"legal": {"verdict": "pass"}, "confidence": "low",
           "items": {"PV-01": {"value": "unmet"}, "PV-03": {"value": "met"}, "UV-01": {"value": "met"}}}
    _, meta = av.postprocess(_res("S"), out, ids, NAMES)
    assert any("확신" in x for x in meta["reasons"]) and meta["item_diff_required"] == ["PV-01", "PV-03"]


class _DB:
    def __init__(self, results):
        self.results, self.saved = results, []

    def get_settings(self):
        return {"openaiKey": "k"}

    def get_test_run(self, rid):
        return {"id": rid, "results": self.results} if rid == "R" else None

    def get_phr_case(self, cid):
        return {"case": {"checkups": {}}}

    def save_gold_label(self, row):
        self.saved.append(row)
        return "id"


class _EV:
    def __init__(self, fail_on=()):
        self.calls, self.fail_on = [], fail_on

    def available(self):
        return True, ""

    def chat_json(self, model, sys_p, user_p, api_key=None):
        self.calls.append((model, api_key))
        if "BOOM" in user_p:
            raise RuntimeError("api down")
        verdict = "fail" if "LG-02" in user_p and "legal_hits\": [\"LG-02\"]" in user_p else "pass"
        return {"legal": {"verdict": verdict, "rules": ["LG-02"] if verdict == "fail" else [],
                          "quotes": [{"rule": "LG-02", "quote": "고지혈증 가능성이 있습니다."}] if verdict == "fail" else []},
                "items": {}, "confidence": "high"}


def test_run_saves_ai_labels_and_logs_no_content(monkeypatch):
    monkeypatch.setattr(gl, "rule_names", lambda: NAMES)
    rs = [_res("F1", "fail", ("LG-02",)), _res("P1"), _res("P2")]
    bad = _res("P3")
    bad["prompt"] = "BOOM"
    rs.append(bad)
    db, ev, logs = _DB(rs), _EV(), []
    code = av.run(["R"], [3], db=db, eval_v3=ev, model="m", workers=2, log=logs.append)
    assert code == 7                                                          # 1건 API 오류
    assert {r["scenario_id"] for r in db.saved} == {"F1", "P1", "P2"}
    row = next(r for r in db.saved if r["scenario_id"] == "F1")
    assert row["labeler_id"] == "ai:verifier" and row["labels"]["legal"]["rules"] == ["LG-02"]
    meta = json.loads(row["note"])
    assert meta["needs_human"] and meta["quotes_ok"] is True
    assert gl.ai_meta({"labelerId": "ai:verifier", "note": row["note"]})["confidence"] == "high"
    assert gl.ai_meta({"labelerId": "u1", "note": row["note"]}) == {}
    assert all(k == "k" for _, k in ev.calls)
    text = "\n".join(logs)
    assert "고지혈증" not in text and "콜레스테롤" not in text                  # 로그에 내용 없음
    assert "SUMMARY total=4 needs_human=1 errors=1" in text
    # dry-run 은 저장하지 않는다
    db2 = _DB(rs[:3])
    assert av.run(["R"], [3], db=db2, eval_v3=_EV(), model="m", dry_run=True, log=lambda *_: None) == 0
    assert db2.saved == []
    assert av.run(["NOPE"], [3], db=db2, eval_v3=_EV(), model="m", log=lambda *_: None) == 4


def test_entrypoint_and_arg_check():
    s = open(os.path.join(ROOT, "entrypoint.sh"), encoding="utf-8").read()
    assert 'RUN_MODE" = "ai_verify"' in s and "scripts/ai_verify.py" in s
    assert av.main(["--runs", "A,B", "--per-run-pass", "10"]) == 2
