# -*- coding: utf-8 -*-
"""저장된 답변을 v3 판정기로 다시 판정해 새 이력으로 남긴다 (Cloud Run Job RUN_MODE=rejudge_v3 용).

판정기(온톨로지·사전)만 바뀌었을 때 답변을 새로 받지 않고 판정만 다시 돌린다. 답변을 다시 받으면
답변이 달라져 판정기 변화와 답변 변화가 섞인다(2026-09-22 평가체계 개선 계획 0단계).

- 원본 이력은 고치지 않는다. 새 이력(--new-run)에 저장하고, 각 결과에 rejudgeOf(원본 run·판정)를 남긴다.
- 새 이력은 판정기 결과만 담는다. 원본의 사람 검토는 priorHumanReview 로 옮기고 agreesWithReview 에
  새 판정이 검토와 같은지 남긴다 — 판정기 개선이 사람 판정에 얼마나 가까워졌는지 보는 용도.

    python scripts/rejudge_v3.py --source <runId> --new-run <newRunId> [--ids A,B] [--dry-run]
"""
import argparse
import copy
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _scenario_for(result, get_scenario):
    """판정 입력용 시나리오 — DB 의 현재 시나리오가 있으면 그것, 없으면 결과에 남은 필드."""
    sc = None
    try:
        sc = get_scenario(result.get("scenarioId"))
    except Exception:
        sc = None
    if not sc:
        sc = {k: result.get(k) for k in ("prompt", "expectedBehavior", "tags", "phrCaseId", "category",
                                         "subcategory")}
    return sc


def rejudge_one(result, source_id, *, evaluate, get_scenario, api_key, final_of):
    """결과 1건 → 다시 판정한 결과(복사본). 답변이 없으면 None."""
    answer = result.get("response") or ""
    if not answer:
        return None
    sc = _scenario_for(result, get_scenario)
    try:
        v3 = evaluate(sc, result.get("prompt") or sc.get("prompt") or "", answer, api_key=api_key)
    except Exception as e:
        v3 = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    old = result.get("evalV3") or {}
    out = copy.deepcopy(result)
    out["rejudgeOf"] = {"runId": source_id, "legal_verdict": old.get("legal_verdict"),
                        "legal_hits": old.get("legal_hits"), "validity_grade": old.get("validity_grade"),
                        "status": result.get("status"), "finalScore": result.get("finalScore"),
                        "versions": old.get("versions"), "judge_original": old.get("judge_original")}
    out["evalV3"] = v3
    # 사람 검토는 정답 기준으로만 옮긴다 — 다시 판정한 이력은 판정기 결과 그대로다(검토를 적용하지 않음).
    out.pop("humanReview", None)
    review = old.get("human_review") or result.get("humanReview")
    if review and review.get("verdict") in ("pass", "fail"):
        out["priorHumanReview"] = review
        out["agreesWithReview"] = (isinstance(v3, dict) and v3.get("legal_verdict") == review["verdict"])
    if out.get("finalSource") == "v3" and out.get("status") != "error":
        fin = final_of(v3)
        if fin is not None:
            out["finalScore"], passed = fin
            out["status"] = "pass" if passed else "fail"
    return out


def rejudge(source_id, new_id, *, ids=None, dry_run=False, db=None, eval_v3=None, api_key=None,
            workers=4, log=print):
    """반환: (종료코드, 새 결과 목록)."""
    if db is None:
        import db as db  # noqa: F811
    if eval_v3 is None:
        import eval_v3  # noqa: F811
    if not source_id or not new_id or source_id == new_id:
        log("[rejudge] --source 와 --new-run 은 서로 다른 값이어야 합니다")
        return 2, []
    src = db.get_test_run(source_id)
    if not src:
        log(f"[rejudge] 이력 없음: {source_id}")
        return 4, []
    if db.get_test_run(new_id):
        log(f"[rejudge] 새 이력 id 가 이미 있습니다(덮어쓰지 않음): {new_id}")
        return 5, []
    results = [r for r in (src.get("results") or []) if isinstance(r, dict)]
    if ids:
        want = set(ids)
        results = [r for r in results if r.get("scenarioId") in want]
        miss = sorted(want - {r.get("scenarioId") for r in results})
        if miss:
            log(f"[rejudge] 원본에 없는 id {len(miss)}건: {miss[:10]}")
            return 3, []
    if api_key is None:
        s = db.get_settings() or {}
        api_key = s.get("openaiKey", "") or s.get("openai_api_key", "")
    ok, why = eval_v3.available()
    if not ok:
        log(f"[rejudge] v3 판정기를 쓸 수 없습니다: {why}")
        return 6, []
    if not eval_v3._ensure_checklists_env():
        log("[rejudge] 경고: SV 체크리스트 없음 — 증상 상담 항목이 na 로 나온다")
    log(f"[rejudge] source={source_id} → new={new_id} n={len(results)} versions={eval_v3.versions()}")

    def one(r):
        return rejudge_one(r, source_id, evaluate=eval_v3.evaluate_scenario, get_scenario=db.get_scenario,
                           api_key=api_key, final_of=eval_v3.final_of)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        new = [x for x in ex.map(one, results) if x is not None]
    flips = []
    for r in new:
        a, b = (r["rejudgeOf"].get("legal_verdict"), (r.get("evalV3") or {}).get("legal_verdict"))
        if a != b:
            flips.append(r["scenarioId"])
        log(f"[rejudge] {r['scenarioId']} legal {a}→{b} hits {r['rejudgeOf'].get('legal_hits')}"
            f"→{(r.get('evalV3') or {}).get('legal_hits')} status {r['rejudgeOf'].get('status')}→{r.get('status')}")
    passed, failed = eval_v3.count_status(new)
    rv = [r for r in new if "agreesWithReview" in r]
    agree = f" review_agree={sum(1 for r in rv if r['agreesWithReview'])}/{len(rv)}" if rv else ""
    log(f"[rejudge] SUMMARY n={len(new)} flips={len(flips)} {flips[:20]} passed={passed} failed={failed}{agree}")
    if dry_run:
        log("[rejudge] dry-run: 저장하지 않음")
        return 0, new
    db.save_test_run({
        "id": new_id, "runAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(new), "passed": passed, "failed": failed, "env": src.get("env", "dev"),
        "guidelineVersion": src.get("guidelineVersion", ""), "tester": f"rejudge:{source_id}",
        "results": new, "status": "completed",
    })
    after = db.get_test_run(new_id)
    log(f"[rejudge] 저장 확인: {new_id} total={after.get('total')} passed={after.get('passed')}")
    return 0, new


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=os.environ.get("REJUDGE_SOURCE", ""))
    ap.add_argument("--new-run", default=os.environ.get("RUN_ID", ""))
    ap.add_argument("--ids", default=os.environ.get("SCENARIO_IDS_JSON", ""),
                    help="JSON 목록 또는 쉼표 구분. 비우면 원본 전체")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("REJUDGE_WORKERS", "4")))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    ids = None
    if a.ids.strip():
        t = a.ids.strip()
        ids = json.loads(t) if t.startswith("[") else [x.strip() for x in t.split(",") if x.strip()]
    code, new = rejudge(a.source, a.new_run, ids=ids, dry_run=a.dry_run, workers=a.workers)
    if code == 0 and new:
        try:  # 배치와 같은 [v3] 줄 — scripts/report_v3_run.py 가 그대로 읽는다
            import job_runner
            job_runner._v3_log_summary(new)
        except Exception as e:
            print(f"[rejudge] 요약 로그 실패: {e}")
    return code


if __name__ == "__main__":
    sys.exit(main())
