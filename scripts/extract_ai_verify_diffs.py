# -*- coding: utf-8 -*-
"""AI 독립 검수 이견 추출 (REQ-E3FL · REQ-YM3P) — Cloud Run Job RUN_MODE=extract_diffs.

AI 검수 라벨(gold_labels labeler ai:verifier)과 저장된 판정기 결과(test_runs.results[].evalV3)를
맞대어 두 가지를 뽑는다.
  item_diffs   PV·SV·UV 항목에서 판정기와 AI 가 다른 행 전량 + 항목별 방향 요약(ai_verify ITEM 줄)
  legal_rows   법률(LG-05 제외): 판정기·AI 가 다르거나, 둘 중 하나라도 fail 이거나, AI 확신 낮음인 행
               판정기 hits(rule_id·claim_idx·level·detectors·evidence 의 basis·phrase_id·example_code·
               귀속 person_attributed·attrib_source·attrib_level) + AI rules·confidence·quotes_ok·이유
               + AI 인용이 가리키는 판정기 claim_idx(인용과 판정기 걸린 문장을 Job 안에서 맞대어 번호만)
가림: 답변 원문·AI 인용·판정기 걸린 문장(quote)·evidence 의 text·phrase·rationale·케이스 수치는 넣지 않는다.
이유 텍스트는 숫자 → #, 따옴표 안 문구 → 〈인용〉.
주장(claims) 전체는 호스트가 저장하지 않는다(compact: claim_count·claim_levels 만) — claim 의
subject·predicate·source 는 없고, 귀속 요지는 hits.evidence 의 attribution 행으로 대신한다.

    python scripts/extract_ai_verify_diffs.py --runs RUN1,RUN2 [--out gs://…/x.json | 파일] [--dry-run]
    DIFF_RUNS 항목이 "재판정이력=원본이력" 이면 판정은 앞, AI 라벨은 뒤 이력에서 읽는다.
    python scripts/extract_ai_verify_diffs.py --judge-runs REJUDGE1,REJUDGE2 [--judge-ids A,B] [--out …]
    env: DIFF_RUNS EXTRACT_OUT JUDGE_RUNS JUDGE_IDS
"""
import argparse
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from ai_verify import LABELER, judge_legal  # noqa: E402

EXCLUDE_RULES = {"LG-05"}
EV_SAFE = ("basis", "phrase_id", "id", "kind", "rule_id", "status", "example_code", "example_kind",
           "same_as_nearest", "person_attributed", "attrib_source", "attrib_level", "department")
_Q = "'\"‘’“”「」『』"


def mask(text):
    """숫자 → #, 따옴표 안 문구 → 〈인용〉."""
    t = str(text or "")
    t = re.sub(rf"[{_Q}][^{_Q}]{{1,200}}[{_Q}]", "〈인용〉", t)
    return re.sub(r"\d+(?:[.,]\d+)*", "#", t)


def _norm(s):
    return re.sub(r"[\s\W_]+", "", str(s or "")).lower()


def _note(lbl):
    n = lbl.get("note")
    if isinstance(n, dict):
        return n
    try:
        return json.loads(n or "{}")
    except (TypeError, ValueError):
        return {}


def _detectors(d):
    out = []
    for x in d or []:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            out.append({k: x[k] for k in ("name", "id", "kind", "phrase_id") if x.get(k) is not None})
    return out


def hit_rows(v3):
    rows = []
    for h in v3.get("legal_hit_detail") or []:
        if not isinstance(h, dict) or h.get("rule_id") in EXCLUDE_RULES:
            continue
        rows.append({"rule_id": h.get("rule_id"), "claim_idx": h.get("claim_idx"), "level": h.get("level"),
                     "severity": h.get("severity"), "status": h.get("status"), "review": h.get("review"),
                     "detectors": _detectors(h.get("detectors")),
                     "evidence": [{k: e[k] for k in EV_SAFE if e.get(k) not in (None, "", [])}
                                  for e in h.get("evidence") or [] if isinstance(e, dict)]})
    return rows


def quote_refs(meta, v3, answer):
    """AI 인용 → (규칙, 답변에 있음, 겹치는 판정기 hit 의 claim_idx). 문장은 내보내지 않는다."""
    hits = [(h.get("claim_idx"), _norm(h.get("quote"))) for h in v3.get("legal_hit_detail") or []
            if isinstance(h, dict) and h.get("quote")]
    ans = _norm(answer)
    out = []
    for q in meta.get("quotes") or []:
        if not isinstance(q, dict) or not q.get("quote") or q.get("rule") in EXCLUDE_RULES:
            continue
        n = _norm(q["quote"])
        m = [ci for ci, hq in hits if n and hq and (n in hq or hq in n)]
        out.append({"rule": q.get("rule"), "in_answer": bool(n) and n in ans, "judge_claim_idx": m or None})
    return out


def _dim(qtype, sc):
    return {"qtype": qtype, "branch": sc.get("branch") or "", "category": sc.get("category") or ""}


def extract(runs, *, db, log=print):
    scen = {s["id"]: s for s in ((db.get_scenarios() or {}).get("scenarios") or []) if s.get("id")}
    item_rows, legal_rows = [], []
    item_n, item_dir = Counter(), {}
    per_run = {}
    for spec in runs:
        # "재판정이력=원본이력" 이면 판정은 재판정 이력에서, AI 라벨은 원본 이력에서 읽는다(REQ-0013 (1)).
        rid, _, label_rid = spec.partition("=")
        run = db.get_test_run(rid)
        if not run:
            log(f"[extract] 이력 없음: {rid}")
            continue
        res = {r.get("scenarioId"): r for r in run.get("results") or [] if isinstance(r, dict)}
        labels = db.get_gold_labels(run_id=label_rid or rid, labeler_id=LABELER)
        per_run[rid] = {"results": len(res), "ai_labels": len(labels), "label_run": label_rid or rid}
        for lbl in labels:
            sid = lbl.get("scenarioId")
            r = res.get(sid) or {}
            v3 = r.get("evalV3") or {}
            sc = scen.get(sid) or {}
            qtype = next((t[6:] for t in sc.get("tags") or [] if isinstance(t, str) and t.startswith("qtype:")),
                         "") or sc.get("subcategory") or ""
            meta = _note(lbl)
            lab = lbl.get("labels") or {}
            reasons = meta.get("item_reasons") or {}
            judge = {it.get("id"): it for it in (v3.get("validity_items") or []) + (v3.get("uv_items") or [])
                     if isinstance(it, dict)}
            for k, av in sorted((lab.get("items") or {}).items()):
                item_n[k] += 1
                jv = (judge.get(k) or {}).get("result")
                if jv == av:
                    continue
                item_dir.setdefault(k, Counter())[f"{jv}→{av}"] += 1
                item_rows.append(dict(_dim(qtype, sc), run_id=rid, scenario_id=sid, uv_intent=v3.get("uv_intent"),
                                      item_id=k, judge_result=jv, judge_detail=mask((judge.get(k) or {}).get("detail")),
                                      judge_claim_idx=None, ai_value=av, ai_reason=mask(reasons.get(k)),
                                      ai_reason_kept=k in reasons))
            jl, al = judge_legal(r), (lab.get("legal") or {}).get("verdict")
            jh = [x for x in v3.get("legal_hits") or [] if x not in EXCLUDE_RULES]
            ar = [x for x in (lab.get("legal") or {}).get("rules") or [] if x not in EXCLUDE_RULES]
            conf = meta.get("confidence")
            if jl == al == "pass" and conf != "low":
                continue
            legal_rows.append(dict(
                _dim(qtype, sc), run_id=rid, scenario_id=sid,
                kind=("both_fail" if jl == al == "fail" else "judge_fail_ai_pass" if jl == "fail" else
                      "judge_pass_ai_fail" if al == "fail" else "low_confidence"),
                judge_legal=jl, judge_hits=jh, judge_review_hits=v3.get("legal_review_hits") or [],
                judge_hit_detail=hit_rows(v3), claim_count=v3.get("claim_count"),
                claim_levels=v3.get("claim_levels"), claims_stored=False,
                ai_legal=al, ai_rules=ar, ai_confidence=conf, ai_quotes_ok=meta.get("quotes_ok"),
                ai_quote_refs=quote_refs(meta, v3, r.get("response")),
                ai_reason=mask((lab.get("legal") or {}).get("note")),
                ai_judge_errors=[mask(e) for e in meta.get("judge_errors") or []],
                ai_review_rules=meta.get("review_rules"), needs_human=meta.get("needs_human"),
                human_reasons=[mask(x) for x in meta.get("reasons") or []]))
    item_summary = [{"item_id": k, "diff": sum(item_dir[k].values()), "labeled": item_n[k],
                     "directions": dict(item_dir[k].most_common()),
                     "line": f"ITEM {k} 이견 {sum(item_dir[k].values())}/{item_n[k]} (판정기→AI: "
                             + ", ".join(f"{d} {n}" for d, n in item_dir[k].most_common()) + ")"}
                    for k in sorted(item_dir, key=lambda k: (-sum(item_dir[k].values()), k))]
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "request": ["REQ-E3FL", "REQ-YM3P"], "runs": runs, "per_run": per_run, "labeler": LABELER,
        "excluded_rules": sorted(EXCLUDE_RULES),
        "notes": ["답변 원문·AI 인용·판정기 걸린 문장·케이스 수치 제외. 이유 텍스트는 숫자 #, 따옴표 안 〈인용〉.",
                  "호스트는 claims 전체를 저장하지 않는다(claim_count·claim_levels 만). 귀속 요지는 "
                  "judge_hit_detail[].evidence 의 person_attributed·attrib_source·attrib_level.",
                  "judge_claim_idx(항목)는 저장 형식에 없어 null. ai_reason_kept=false 는 라벨 note 길이 제한으로 "
                  "AI 이유가 잘려 없는 행.",
                  "ai_quote_refs.judge_claim_idx = AI 인용과 겹치는 판정기 hit 의 claim_idx(Job 안에서 대조)."],
        "counts": {"item_diff_rows": len(item_rows), "legal_rows": len(legal_rows),
                   "legal_kind": dict(Counter(x["kind"] for x in legal_rows))},
        "item_summary": item_summary,
        "item_diffs": sorted(item_rows, key=lambda d: (d["item_id"], d["run_id"], d["scenario_id"])),
        "legal_rows": sorted(legal_rows, key=lambda d: (d["run_id"], d["scenario_id"])),
    }


def judge_rows(runs, *, db, ids=(), log=print):
    """재판정 이력(REQ-0013) — AI 라벨 없이 판정기 결과만. 법률 fail·판정이 바뀐 행·지정 id 를 낸다.

    원본 판정(rejudgeOf)과 새 판정의 hits·review_hits·cap_hits·판정 근거(evidence 안전 키)를 싣는다.
    """
    scen = {s["id"]: s for s in ((db.get_scenarios() or {}).get("scenarios") or []) if s.get("id")}
    rows, per_run = [], {}
    for rid in runs:
        run = db.get_test_run(rid)
        if not run:
            log(f"[extract] 이력 없음: {rid}")
            continue
        res = [r for r in run.get("results") or [] if isinstance(r, dict)]
        flips = Counter()
        for r in res:
            sid, v3, old = r.get("scenarioId"), r.get("evalV3") or {}, r.get("rejudgeOf") or {}
            a, b = old.get("legal_verdict"), v3.get("legal_verdict")
            if old:
                flips[f"{a}→{b}"] += 1
            if not (b == "fail" or (old and a != b) or sid in ids):
                continue
            sc = scen.get(sid) or {}
            qtype = next((t[6:] for t in sc.get("tags") or [] if isinstance(t, str) and t.startswith("qtype:")),
                         "") or sc.get("subcategory") or ""
            esc = v3.get("judge_escalation") or {}
            rows.append(dict(
                _dim(qtype, sc), run_id=rid, scenario_id=sid, source_run=old.get("runId"),
                prior_legal=a, prior_hits=old.get("legal_hits"), legal=b,
                hits=[x for x in v3.get("legal_hits") or [] if x not in EXCLUDE_RULES],
                review_hits=v3.get("legal_review_hits") or [], cap_hits=v3.get("legal_cap_hits") or [],
                hit_detail=hit_rows(v3), claim_count=v3.get("claim_count"), claim_levels=v3.get("claim_levels"),
                escalation={k: esc.get(k) for k in ("first_model", "first_verdict", "first_hits", "model", "verdict")
                            if k in esc} or None,
                validity_grade=v3.get("validity_grade"), validity_grade_source=v3.get("validity_grade_source"),
                eval_version=v3.get("eval_version"), ontology_version=v3.get("ontology_version"),
                error=(str(v3.get("error"))[:120] if v3.get("error") else None)))
        per_run[rid] = {"results": len(res),
                        "legal": dict(Counter(str((r.get("evalV3") or {}).get("legal_verdict")) for r in res)),
                        "prior_to_new": dict(flips)}
    return {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "request": ["REQ-0013"],
            "runs": runs, "per_run": per_run, "excluded_rules": sorted(EXCLUDE_RULES),
            "notes": ["답변 원문·판정기 quote·evidence text/phrase/rationale·케이스 수치 제외.",
                      "행 = 새 판정 법률 fail + 원본과 판정이 바뀐 행 + 지정 id."],
            "counts": {"rows": len(rows)}, "rows": sorted(rows, key=lambda d: (d["run_id"], d["scenario_id"]))}


def _write(doc, out):
    if out.startswith("gs://"):
        import scenario_inventory as si
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
            path = f.name
        print(f"[extract] 업로드 {out} status={si.upload(path, out)}")
    else:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"[extract] 저장 {out}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default=os.environ.get("DIFF_RUNS", ""))
    ap.add_argument("--out", default=os.environ.get("EXTRACT_OUT", ""))
    ap.add_argument("--judge-runs", default=os.environ.get("JUDGE_RUNS", ""),
                    help="재판정 이력 — 판정기 단독 행(REQ-0013). 주면 --runs 대신 이것을 뽑는다")
    ap.add_argument("--judge-ids", default=os.environ.get("JUDGE_IDS", ""))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    jr = [x for x in a.judge_runs.split(",") if x]
    if jr:
        import db
        doc = judge_rows(jr, db=db, ids={x for x in a.judge_ids.split(",") if x})
        print("[extract] JUDGE " + json.dumps(dict(doc["counts"], per_run=doc["per_run"]), ensure_ascii=False))
        for r in doc["rows"]:
            print(f"[extract] {r['run_id']} {r['scenario_id']} {r['prior_legal']}{r['prior_hits']}→{r['legal']}"
                  f"{r['hits']} review={r['review_hits']} cap={r['cap_hits']}")
        if not a.dry_run and a.out:
            _write(doc, a.out)
        return 0
    runs = [x for x in a.runs.split(",") if x]
    if not runs:
        print("[extract] --runs 또는 DIFF_RUNS 가 필요합니다")
        return 2
    import db
    doc = extract(runs, db=db)
    print("[extract] COUNTS " + json.dumps(dict(doc["counts"], per_run=doc["per_run"]), ensure_ascii=False))
    for s in doc["item_summary"]:
        print("[extract] " + s["line"])
    if a.dry_run or not a.out:
        print("[extract] 저장 안 함 (dry-run 또는 출력 경로 없음)")
        return 0
    _write(doc, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
