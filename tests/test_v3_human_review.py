# -*- coding: utf-8 -*-
"""eval_v3.apply_human_review — 사람 검토 정정: 원래 판정 보존, status·finalScore·집계 재계산."""
import copy
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import eval_v3  # noqa: E402


def _fail(sid, grade="B"):
    return {"scenarioId": sid, "status": "fail", "finalScore": 0, "finalSource": "v3",
            "category": "phr_case",
            "evalV3": {"legal_verdict": "fail", "legal_hits": ["LG-04"], "validity_grade": grade,
                       "judge_escalation": {"verdict": "FAIL", "model": "gpt-5.4"}}}


def _pass(sid):
    return {"scenarioId": sid, "status": "pass", "finalScore": 100, "finalSource": "v3",
            "category": "phr_case", "evalV3": {"legal_verdict": "pass", "legal_hits": [], "validity_grade": "A"}}


REV = [{"scenarioId": "B1", "verdict": "pass", "reason": "기록 권고 재전달(L3)"}]


def test_score_table_matches_batch_executor():
    from batch_executor import BatchExecutor
    assert eval_v3.V3_SCORE == BatchExecutor.V3_SCORE


def test_override_to_pass_keeps_original():
    res = [_fail("B1", "B"), _pass("B2")]
    changed, errors = eval_v3.apply_human_review(res, REV, by="검토자", at="2026-09-21T00:00:00+00:00")
    assert (changed, errors) == (["B1"], [])
    r = res[0]
    assert r["status"] == "pass" and r["finalScore"] == 85
    v = r["evalV3"]
    assert v["legal_verdict"] == "pass" and v["legal_hits"] == []
    assert v["judge_original"] == {"legal_verdict": "fail", "legal_hits": ["LG-04"],
                                   "status": "fail", "finalScore": 0}
    assert v["human_review"]["judge_verdict"] == "fail" and r["humanReview"]["by"] == "검토자"
    assert v["judge_escalation"]["verdict"] == "FAIL"          # 판정기 기록은 그대로
    assert eval_v3.count_status(res) == (2, 0)
    s = eval_v3.run_summary(res)
    assert s["gate"] == {"pass": 2, "fail": 0, "review": 0} and s["human_review"] == 1


def test_second_review_does_not_overwrite_original_and_can_revert():
    res = [_fail("B1", "C")]
    eval_v3.apply_human_review(res, REV, by="a", at="t1")
    eval_v3.apply_human_review(res, [{"scenarioId": "B1", "verdict": "fail", "reason": "재검토"}], by="b", at="t2")
    v = res[0]["evalV3"]
    assert v["judge_original"]["legal_verdict"] == "fail"
    assert v["legal_hits"] == ["LG-04"] and res[0]["status"] == "fail" and res[0]["finalScore"] == 0


def test_errors_reported():
    res = [_fail("B1"), {"scenarioId": "B3", "status": "error", "evalV3": {"error": "x"}}]
    before = copy.deepcopy(res)
    changed, errors = eval_v3.apply_human_review(res, [
        {"scenarioId": "NOPE", "verdict": "pass", "reason": "r"},
        {"scenarioId": "B3", "verdict": "pass", "reason": "r"},
        {"scenarioId": "B1", "verdict": "maybe", "reason": "r"},
        {"scenarioId": "B1", "verdict": "pass", "reason": " "},
    ], by="a", at="t")
    assert changed == [] and len(errors) == 4 and res == before


def test_db_roundtrip_keeps_run_meta():
    os.environ["DATABASE_URL"] = ""
    import db
    import dbcommon
    path = tempfile.mktemp(suffix="_review.db")
    old = (dbcommon._use_postgres, dbcommon._pg_pool, dbcommon.DB_PATH, db._use_postgres, db.DB_PATH)
    try:
        dbcommon._use_postgres, dbcommon._pg_pool, dbcommon.DB_PATH = False, None, path
        db._use_postgres, db.DB_PATH = False, path
        db.init_db(path)
        db.save_test_run({"id": "phr350-v3-x", "runAt": "2026-09-21T08:20:00Z", "total": 2, "passed": 1,
                          "failed": 1, "env": "prod", "guidelineVersion": "v18", "tester": "job",
                          "results": [_fail("B1"), _pass("B2")], "status": "completed"})
        r = db.get_test_run("phr350-v3-x")
        results = r["results"]
        eval_v3.apply_human_review(results, REV, by="a", at="t")
        p, f = eval_v3.count_status(results)
        db.save_test_run({"id": "phr350-v3-x", "runAt": r["runAt"], "total": r["total"], "passed": p,
                          "failed": f, "env": r["env"], "guidelineVersion": r["guidelineVersion"],
                          "tester": r["tester"], "results": results, "status": r["status"]})
        r2 = db.get_test_run("phr350-v3-x")
        assert (r2["passed"], r2["failed"], r2["env"], r2["tester"], r2["runAt"]) == \
               (2, 0, "prod", "job", "2026-09-21T08:20:00Z")
        assert r2["results"][0]["evalV3"]["judge_original"]["legal_verdict"] == "fail"
    finally:
        (dbcommon._use_postgres, dbcommon._pg_pool, dbcommon.DB_PATH, db._use_postgres, db.DB_PATH) = old
        if os.path.exists(path):
            os.unlink(path)



_HANDLER_SCRIPT = r"""
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], 'tests'))
os.environ['DATABASE_URL'] = ''
import db, dbcommon
path = tempfile.mktemp(suffix='_review_h.db')
dbcommon._use_postgres, dbcommon._pg_pool, dbcommon.DB_PATH = False, None, path
db._use_postgres, db.DB_PATH = False, path
db.init_db(path)
import proxy_server as ps
from test_v3_human_review import _fail, _pass, REV
try:
    db.save_test_run({'id': 'phr350-v3-y', 'runAt': '2026-09-21T08:20:00Z', 'total': 2, 'passed': 1,
                      'failed': 1, 'env': 'prod', 'tester': 'job',
                      'results': [_fail('B1'), _pass('B2')], 'status': 'completed'})
    sent = []
    h = ps.ProxyHandler.__new__(ps.ProxyHandler)
    h._send_json = lambda code, obj: sent.append((code, obj))
    h._send_error = lambda code, msg: sent.append((code, msg))
    ps._V3_RUN_CACHE['phr350-v3-y'] = ('stale', None)

    bad = {'by': 'a', 'reviews': REV + [{'scenarioId': 'NOPE', 'verdict': 'pass', 'reason': 'r'}]}
    h._review_history_run('phr350-v3-y', json.dumps(bad).encode())
    assert sent[-1][0] == 400 and db.get_test_run('phr350-v3-y')['passed'] == 1, sent[-1]

    h._review_history_run('phr350-v3-y', json.dumps({'by': 'a', 'reviews': REV}).encode())
    code, obj = sent[-1]
    assert code == 200 and obj['changed'] == ['B1'] and obj['passed'] == [1, 2] and obj['failed'] == [1, 0], sent[-1]
    r = db.get_test_run('phr350-v3-y')
    assert (r['passed'], r['failed'], r['env'], r['tester']) == (2, 0, 'prod', 'job'), r
    assert 'phr350-v3-y' not in ps._V3_RUN_CACHE

    h._review_history_run('phr350-v3-y', json.dumps({'reviews': REV}).encode())
    assert sent[-1][0] == 400, sent[-1]
    h._review_history_run('nope', json.dumps({'by': 'a', 'reviews': REV}).encode())
    assert sent[-1][0] == 404, sent[-1]
    print('HANDLER_OK')
finally:
    try:
        os.unlink(path)
    except OSError:
        pass
"""


def test_handler_review_endpoint(tmp_path):
    """POST /api/history/<runId>/review 핸들러. proxy_server import 는 stdout 을 바꾸므로 별도 프로세스에서."""
    import subprocess
    script = tmp_path / "handler_check.py"
    script.write_text(_HANDLER_SCRIPT, encoding="utf-8")
    env = dict(os.environ, DATABASE_URL="", PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, str(script), ROOT], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=120)
    assert p.returncode == 0 and "HANDLER_OK" in p.stdout, (p.stdout[-2000:], p.stderr[-3000:])


def test_apply_script_dry_run_and_apply():
    """scripts/apply_v3_review.py — dry-run 은 쓰지 않고, 실제 적용은 메타 보존·재집계."""
    import scripts.apply_v3_review as ap  # noqa: E402

    class FakeDB:
        def __init__(self):
            self.row = {"id": "R", "runAt": "t0", "total": 2, "passed": 1, "failed": 1, "env": "prod",
                        "guidelineVersion": "", "tester": "job", "status": "completed",
                        "results": [_fail("B1"), _pass("B2")]}
            self.saved = []

        def get_test_run(self, rid):
            return copy.deepcopy(self.row) if rid == "R" else None

        def save_test_run(self, d):
            self.saved.append(d)
            self.row = dict(self.row, passed=d["passed"], failed=d["failed"], results=d["results"])

    spec = {"runId": "R", "by": "a", "reviews": REV}
    fdb = FakeDB()
    code, log = ap.apply(spec, dry_run=True, db=fdb, eval_v3=eval_v3)
    assert code == 0 and not fdb.saved and "dry-run" in log[-1]
    code, log = ap.apply(spec, db=fdb, eval_v3=eval_v3)
    assert code == 0 and fdb.saved[0]["env"] == "prod" and fdb.saved[0]["runAt"] == "t0"
    assert (fdb.row["passed"], fdb.row["failed"]) == (2, 0)
    code, _ = ap.apply({"runId": "R", "by": "a", "reviews": [{"scenarioId": "X", "verdict": "pass", "reason": "r"}]},
                       db=fdb, eval_v3=eval_v3)
    assert code == 3
    assert ap.apply({"runId": "nope", "by": "a", "reviews": REV}, db=fdb, eval_v3=eval_v3)[0] == 4


def test_review_file_is_valid():
    import json
    p = os.path.join(ROOT, "scripts", "reviews", "phr350-v3-20260921-0819.json")
    spec = json.load(open(p, encoding="utf-8"))
    ids = [r["scenarioId"] for r in spec["reviews"]]
    assert spec["runId"] == "phr350-v3-20260921-0819" and len(set(ids)) == 5
    assert all(r["verdict"] == "pass" and r["reason"].strip() for r in spec["reviews"])
    sc = json.load(open(os.path.join(ROOT, "scripts", "scenarios_phr_case_350.json"), encoding="utf-8"))
    sc = sc if isinstance(sc, list) else sc.get("scenarios", [])
    known = {s["id"] for s in sc}
    assert set(ids) <= known, set(ids) - known          # 실제 적재된 시나리오 id 여야 한다
