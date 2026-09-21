# -*- coding: utf-8 -*-
"""v3 법률 판정 사람 검토 정정을 이력 DB 에 적용한다 (Cloud Run Job RUN_MODE=apply_v3_review 용).

운영 DB 는 private IP 라 로컬에서 닿지 않는다. POST /api/history/<runId>/review 와 같은 함수
(eval_v3.apply_human_review)를 쓰므로 결과가 같다. 판정기 원래 값은 evalV3.judge_original 에 남는다.

    python scripts/apply_v3_review.py --file scripts/reviews/<runId>.json [--dry-run]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def apply(spec, *, dry_run=False, db=None, eval_v3=None):
    """정정본 1개 적용. 반환: (종료코드, 로그 줄 목록)."""
    if db is None:
        import db as db  # noqa: F811
    if eval_v3 is None:
        import eval_v3  # noqa: F811
    run_id, by, reviews = spec.get("runId"), spec.get("by"), spec.get("reviews")
    if not run_id or not by or not isinstance(reviews, list) or not reviews:
        return 2, ["정정본에 runId·by·reviews 가 필요합니다"]
    r = db.get_test_run(run_id)
    if not r:
        return 4, [f"이력 없음: {run_id}"]
    if (r.get("status") or "") == "running":
        return 5, [f"실행 중인 이력은 정정할 수 없습니다: {run_id}"]
    results = r.get("results") or []
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed, errors = eval_v3.apply_human_review(results, reviews, by=by, at=at)
    log = [f"[review] run={run_id} changed={changed}"]
    if errors:
        return 3, log + [f"[review] 오류(기록 안 함): {e}" for e in errors]
    passed, failed = eval_v3.count_status(results)
    log.append(f"[review] passed {r.get('passed')}→{passed} failed {r.get('failed')}→{failed}")
    for sid in changed:
        x = next(x for x in results if x.get("scenarioId") == sid)
        log.append(f"[review] {sid} status={x.get('status')} finalScore={x.get('finalScore')} "
                   f"judge={x['evalV3']['judge_original']['legal_verdict']} → {x['evalV3']['legal_verdict']}")
    if dry_run:
        return 0, log + ["[review] dry-run: 저장하지 않음"]
    db.save_test_run({
        "id": run_id, "runAt": r.get("runAt", ""), "total": r.get("total", 0),
        "passed": passed, "failed": failed, "env": r.get("env", "dev"),
        "guidelineVersion": r.get("guidelineVersion", ""), "tester": r.get("tester", ""),
        "results": results, "status": r.get("status", "completed"),
    })
    after = db.get_test_run(run_id)
    log.append(f"[review] 저장 확인: passed={after.get('passed')} failed={after.get('failed')}")
    return 0, log


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    with open(a.file, encoding="utf-8") as f:
        spec = json.load(f)
    code, log = apply(spec, dry_run=a.dry_run)
    for line in log:
        print(line, flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
