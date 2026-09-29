# -*- coding: utf-8 -*-
"""v3 시험 세트 plan(build_v3_set.py 결과)을 운영 scenarios 에 반영한다.

(Cloud Run Job RUN_MODE=apply_scenario_set. 2026-09-29 사용자 결정: v3 축 기준 세트 1,000건 이상,
뽑히지 않은 옛 문항은 은퇴.)

- 세트 문항: 이전 세트 태그(set:·zone:·mode:·intent:·sym:·branch:·target:)를 지우고 plan 태그를 붙인다.
  증상 문항은 symptom_key·branch 컬럼도 채운다 — 판정기가 증상군을 받아 SV-02~04 를 채점하게 된다.
  enabled 는 켠다.
- 은퇴 문항: enabled 를 끄고 retired:<set>-unselected 태그를 붙인다. 지우지 않는다.
- plan 은 GCS(gs://…) 나 이미지 안 파일에서 읽는다. 문항 문장은 읽지도 쓰지도 않는다.

    python scripts/apply_scenario_set.py --plan gs://…/plan.json [--dry-run]
    env: SET_PLAN
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SET_PREFIXES = ("set:", "zone:", "mode:", "intent:", "sym:", "branch:", "target:")
MAX_TAGS = 20


def load_plan(src):
    if src.startswith("gs://"):
        import urllib.parse
        import urllib.request
        tok = json.loads(urllib.request.urlopen(urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"}), timeout=10).read())["access_token"]
        bucket, obj = src[5:].split("/", 1)
        req = urllib.request.Request(
            f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{urllib.parse.quote(obj, safe='')}?alt=media",
            headers={"Authorization": f"Bearer {tok}"})
        return json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
    with open(src, encoding="utf-8") as f:
        return json.load(f)


def merge_tags(old, new):
    keep = [t for t in (old or []) if isinstance(t, str) and not t.startswith(SET_PREFIXES)]
    out = list(new) + [t for t in keep if t not in new]
    return out[:MAX_TAGS]


def plan_updates(plan, rows):
    """(id, data) 목록 — 바뀌는 것만."""
    by = {r["id"]: r for r in rows}
    set_id = plan["set"]
    retired_tag = f"retired:{set_id}-unselected"
    ups, missing = [], []
    for sid, tags in plan["tags"].items():
        r = by.get(sid)
        if r is None:
            missing.append(sid)
            continue
        data = {}
        nt = merge_tags(r.get("tags"), tags)
        nt = [t for t in nt if t != retired_tag]
        if nt != (r.get("tags") or []):
            data["tags"] = nt
        if not r.get("enabled", True):
            data["enabled"] = True
        sym = next((t[4:] for t in tags if t.startswith("sym:")), "")
        br = next((t[7:] for t in tags if t.startswith("branch:")), "")
        if sym and (r.get("symptomKey") or "") != sym:
            data["symptomKey"] = sym
        if br and (r.get("branch") or "") != br:
            data["branch"] = br
        if data:
            ups.append((sid, data))
    for sid in plan.get("retire") or []:
        r = by.get(sid)
        if r is None:
            missing.append(sid)
            continue
        data = {}
        if r.get("enabled", True):
            data["enabled"] = False
        if retired_tag not in (r.get("tags") or []):
            data["tags"] = ([retired_tag] + list(r.get("tags") or []))[:MAX_TAGS]
        if data:
            ups.append((sid, data))
    return ups, missing


def run(src, *, db=None, dry_run=False, log=print):
    if db is None:
        import db as db  # noqa: F811
    plan = load_plan(src)
    data = db.get_scenarios()
    rows = data.get("scenarios") if isinstance(data, dict) else data
    ups, missing = plan_updates(plan, rows or [])
    n_set, n_ret = len(plan["tags"]), len(plan.get("retire") or [])
    log(f"[apply_set] plan={plan['set']} 세트 {n_set}건 · 은퇴 {n_ret}건 · 바꿀 행 {len(ups)} · 없는 id {len(missing)}")
    if missing:
        log(f"[apply_set] 없는 id 예: {missing[:10]}")
        return 3
    if n_set < int(plan.get("min_total") or 0):
        log(f"[apply_set] 세트 {n_set}건이 최소 {plan.get('min_total')} 에 못 미쳐 중단")
        return 4
    if dry_run:
        log("[apply_set] dry-run — 저장하지 않음")
        return 0
    for i, (sid, d) in enumerate(ups, 1):
        db.update_scenario(sid, d)
        if i % 200 == 0:
            log(f"[apply_set] {i}/{len(ups)}")
    after = {r["id"]: r for r in (db.get_scenarios() or {}).get("scenarios", [])}
    on = sum(1 for s in plan["tags"] if after.get(s, {}).get("enabled", True))
    off = sum(1 for s in plan.get("retire") or [] if not after.get(s, {}).get("enabled", True))
    log(f"[apply_set] 저장 확인: 세트 활성 {on}/{n_set} · 은퇴 비활성 {off}/{n_ret}")
    return 0 if on == n_set and off == n_ret else 5


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=os.environ.get("SET_PLAN", ""))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.plan:
        print("[apply_set] --plan 또는 SET_PLAN 이 필요합니다")
        return 2
    return run(a.plan, dry_run=a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
