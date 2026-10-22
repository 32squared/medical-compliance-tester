# -*- coding: utf-8 -*-
"""의사 자문 판정(advisory_reviews) 반출 + 같은 답변의 판정기 v3 결과 (REQ-U7VN 5).

위원이 저장한 5항목 판정과, 같은 답변(message_id 기준)을 판정기 v3 로 돌린 결과를 한 JSON 에 묶는다.
위원 성함(reviewer_name)은 넣지 않고 reviewer_id 만 남긴다. 엑셀(8월 형식)은 별도로
`GET /api/advisory/export` 에서 받는다 — 이 스크립트는 그 엑셀에 없는 판정기 대조 열을 만든다.

실행 (Cloud Run Job, RUN_MODE=advisory_export_v3):
    ADV_SINCE=2026-10-23  ADV_REVIEWERS=rexsoft01,rexsoft03,rexsoft04
    ADV_GCS_PATH=gs://<bucket>/dumps/<date>/advisory_v3.json  [ADV_NO_JUDGE=1] [ADV_WORKERS=4]
로컬(DATABASE_URL 필요):
    python scripts/advisory_export_v3.py --since 2026-10-23 --out reports/advisory_v3.json [--no-judge]

판정기 입력은 배치와 같은 경로(eval_v3.evaluate_scenario)다 — 자문 고정 문항(태그 '자문2차')이
(케이스, 질문 문장)으로 맞으면 그 시나리오의 기대 동작을 쓰고, 자유 질의는 케이스만 붙여 판정한다.
"""
import argparse
import io
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ADVISORY_TAG = "자문2차"
# 판정기 compact 결과에서 대조표에 바로 쓰는 항목. 나머지는 v3 전체(`v3`)에 그대로 있다.
V3_SUMMARY_KEYS = ("legal_verdict", "legal_verdict_judge", "legal_status", "legal_hits", "legal_max_level",
                   "validity_grade", "pv", "sv", "uv", "gate", "eval_version", "ontology_version",
                   "judge_model", "prompt_versions", "err")


def _norm(text):
    return " ".join((text or "").split())


def index_advisory_scenarios(scenarios):
    """자문 고정 문항 → {(case_id, 정규화한 질문): scenario}. Vital 벌(-VA…)이 남아 있으면 짧은 id 를 택한다."""
    out = {}
    for s in scenarios or []:
        if ADVISORY_TAG not in (s.get("tags") or []):
            continue
        key = (s.get("phrCaseId") or s.get("phr_case_id") or "", _norm(s.get("prompt")))
        prev = out.get(key)
        sid = s.get("id") or ""
        if prev is None or (len(sid), sid) < (len(prev.get("id") or ""), prev.get("id") or ""):
            out[key] = s
    return out


def scenario_for(review, index):
    """판정 행 → 시나리오 dict. 고정 문항이면 그 시나리오, 자유 질의면 케이스만 붙인 최소 dict."""
    case_id = review.get("caseId") or review.get("case_id") or ""
    hit = index.get((case_id, _norm(review.get("query"))))
    if hit:
        return hit, "designated"
    return {"id": "", "phrCaseId": case_id, "prompt": review.get("query") or "",
            "tags": [ADVISORY_TAG, "자유질의"]}, "free"


def question_code(scenario):
    for t in scenario.get("tags") or []:
        if isinstance(t, str) and t.startswith("문항:"):
            return t.split(":", 1)[1]
    return ""


def v3_summary(v3):
    v3 = v3 if isinstance(v3, dict) else {}
    return {k: v3.get(k) for k in V3_SUMMARY_KEYS if k in v3}


def build_row(review, index, judge=None):
    """판정 행 1건 + 판정기 결과. reviewer_name 은 넣지 않는다(가명 = reviewer_id)."""
    sc, kind = scenario_for(review, index)
    row = {
        "review_id": review.get("id"),
        "reviewer_id": review.get("reviewerId") or review.get("reviewer_id"),
        "specialty": review.get("specialty"),
        "case_id": review.get("caseId") or review.get("case_id"),
        "case_no": review.get("caseNo") or review.get("case_no"),
        "question_kind": kind,
        "scenario_id": sc.get("id") or "",
        "question_code": question_code(sc),
        "message_id": review.get("messageId") or review.get("message_id"),
        "conversation_id": review.get("conversationId") or review.get("conversation_id"),
        "created_at": review.get("createdAt") or review.get("created_at"),
        "query": review.get("query") or "",
        "response": review.get("response") or "",
        "items": review.get("items") or {},
        "overall_note": review.get("overallNote") or review.get("overall_note") or "",
    }
    if judge is not None and row["response"]:
        try:
            v3 = judge(sc, row["query"], row["response"])
        except Exception as e:  # 판정 실패도 행은 남긴다 — 대조표에서 빠지면 불일치 원인 분류가 안 된다
            v3 = {"err": f"{type(e).__name__}: {str(e)[:160]}"}
        row["v3"] = v3
        row["v3_summary"] = v3_summary(v3)
    return row


def build_rows(reviews, scenarios, judge=None, workers=4):
    index = index_advisory_scenarios(scenarios)
    if judge is None or workers <= 1:
        return [build_row(r, index, judge) for r in reviews]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(lambda r: build_row(r, index, judge), reviews))


def select_reviews(reviews, since=None, reviewers=None):
    """created_at >= since, reviewer_id 가 목록(비우면 rexsoft* 전부)에 드는 행만. admin 리허설 행은 빠진다."""
    out = []
    for r in reviews:
        rid = r.get("reviewerId") or r.get("reviewer_id") or ""
        if reviewers:
            if rid not in reviewers:
                continue
        elif not rid.startswith("rexsoft"):
            continue
        if since and (r.get("createdAt") or r.get("created_at") or "") < since:
            continue
        out.append(r)
    return out


def upload_gcs(path, gcs_path):
    """Cloud Run 메타데이터 토큰으로 GCS 업로드 (scripts/dump_run_to_gcs.py 와 같은 방식)."""
    token_req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"})
    tok = json.loads(urllib.request.urlopen(token_req, timeout=10).read())["access_token"]
    assert gcs_path.startswith("gs://")
    bucket, obj = gcs_path[5:].split("/", 1)
    url = (f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o"
           f"?uploadType=media&name={urllib.parse.quote(obj, safe='')}")
    with open(path, "rb") as f:
        body = f.read()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body))})
    return urllib.request.urlopen(req, timeout=300).status


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=os.environ.get("ADV_SINCE", ""), help="created_at 하한 (예: 2026-10-23)")
    ap.add_argument("--reviewers", default=os.environ.get("ADV_REVIEWERS", ""),
                    help="쉼표 구분 reviewer_id (비우면 rexsoft* 전부)")
    ap.add_argument("--out", default=os.environ.get("ADV_OUT", ""), help="JSON 경로 (비우면 임시 파일)")
    ap.add_argument("--gcs", default=os.environ.get("ADV_GCS_PATH", ""), help="gs://… 업로드 경로")
    ap.add_argument("--no-judge", action="store_true", default=os.environ.get("ADV_NO_JUDGE") == "1")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("ADV_WORKERS", "4") or 4))
    ap.add_argument("--limit", type=int, default=5000)
    args = ap.parse_args(argv)

    import db
    reviewers = [x.strip() for x in args.reviewers.split(",") if x.strip()] or None
    reviews = select_reviews(db.get_advisory_reviews(limit=args.limit), since=args.since or None,
                             reviewers=reviewers)
    scenarios = (db.get_scenarios_summary(light=True) or {}).get("scenarios", [])
    n_adv = sum(1 for s in scenarios if ADVISORY_TAG in (s.get("tags") or []))
    print(f"[advisory_export] reviews={len(reviews)} since={args.since or '-'} scenarios(자문2차)={n_adv}",
          flush=True)

    judge, versions = None, {}
    if not args.no_judge:
        import eval_v3
        ok, why = eval_v3.available()
        if not ok:
            print(f"[advisory_export] v3 판정기를 쓸 수 없습니다: {why}", flush=True)
            return 6
        s = db.get_settings() or {}
        api_key = os.environ.get("OPENAI_API_KEY") or s.get("openaiKey", "") or s.get("openai_api_key", "")
        eval_v3._ensure_checklists_env()
        versions = eval_v3.versions()

        def judge(sc, q, a, _k=api_key):
            return eval_v3.evaluate_scenario(sc, q, a, api_key=_k)
    print(f"[advisory_export] judge={'off' if judge is None else versions}", flush=True)

    rows = build_rows(reviews, scenarios, judge, workers=args.workers)
    kinds, verdicts = {}, {}
    for r in rows:
        kinds[r["question_kind"]] = kinds.get(r["question_kind"], 0) + 1
        v = str((r.get("v3_summary") or {}).get("legal_verdict"))
        verdicts[v] = verdicts.get(v, 0) + 1
    payload = {"meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "since": args.since or None,
                        "reviewers": sorted({r["reviewer_id"] for r in rows if r["reviewer_id"]}),
                        "judge_versions": versions or None, "count": len(rows), "question_kind": kinds,
                        "legal_verdict": verdicts if judge else None},
               "rows": rows}
    out = args.out
    if not out:
        fd, out = tempfile.mkstemp(suffix=".json", prefix="advisory_v3_")
        os.close(fd)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"[advisory_export] rows={len(rows)} kinds={kinds} legal={verdicts} -> {out}", flush=True)
    if args.gcs:
        print(f"[advisory_export] upload {args.gcs} status={upload_gcs(out, args.gcs)}", flush=True)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "buffer"):  # 한글 출력 — 모듈 import 때(테스트)는 건드리지 않는다
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.exit(main())
