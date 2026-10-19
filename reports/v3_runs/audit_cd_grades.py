"""C 등급 이하(유효성 PV·SV, 사용자 가치 UV) 판정 타당성 검토 — 데이터셋 생성과 리포트 렌더.

build  : 10.16 덤프들을 build_eval_evidence_viewer 와 같은 방식으로 압축해 C·D 등급 결과만 뽑고,
         미충족 항목마다 근거(지목 문장·빠진 질문 목록·기록 불일치)를 붙여 검토 배치(JSON)로 나눈다.
report : 검토자(에이전트)가 적은 verdicts_*.json 을 합쳐 항목별 타당/거짓/경계 분포, 거짓을 뺀 재계산 등급,
         원인 유형을 집계하고 단독 HTML 리포트를 만든다.

사용:
  python audit_cd_grades.py build --run "PHR 350=...json" --run "일반 650=...json" --out-dir <dir> [--snapshot ...] [--batch 40]
  python audit_cd_grades.py report --data-dir <dir> --out <html> [--patterns patterns.json] [--title ...]
"""
import argparse
import glob
import html
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
KST = timezone(timedelta(hours=9))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

E = lambda s: html.escape("" if s is None else str(s), quote=True)
GRADES = ("A", "B", "C", "D")
CAP_D = {"PV-01", "PV-02"}          # validity_phr.grade_from_items: grade_cap=D 항목
VERDICTS = ("타당", "거짓", "경계", "확인불가")


# ── build ────────────────────────────────────────────────────────────────
def load_viewer_rows(run_specs, snapshot, tmp_out):
    """뷰어 생성기를 그대로 불러 모든 결과의 압축 형태(rows)·규칙 제목(TITLES)·필수 여부(REQUIRED)를 얻는다."""
    import importlib
    argv = ["build_eval_evidence_viewer.py"]
    for s in run_specs:
        argv += ["--run", s]
    argv += ["--out", tmp_out, "--title", "audit-tmp"]
    if snapshot:
        argv += ["--snapshot", snapshot]
    saved = sys.argv
    sys.argv = argv
    sys.path.insert(0, HERE)
    try:
        mod = importlib.import_module("build_eval_evidence_viewer")
    finally:
        sys.argv = saved
    return mod.rows, mod.TITLES, mod.REQUIRED, mod.SNAP_VER, mod.runs


def is_cd(r):
    return (r.get("vgrade") in ("C", "D")) or (r.get("uvgrade") in ("C", "D"))


def case_record(r, titles):
    b = r["basis"]
    items = []
    for u in b["validity"]["unmet"] + b["uv"]["unmet"]:
        items.append({
            "id": u["id"], "title": titles.get(u["id"], ""), "axis": u["axis"], "required": u["required"],
            "detail": u["detail"], "kind": u["kind"], "sentence_idx": u["sentence_idx"] or [],
            "quotes": u["quotes"] or [], "missing": u["missing"] or [], "mismatch": u["mismatch"] or [],
        })
    return {
        "run": r["run"], "id": r["id"], "cat": r["cat"], "sub": r["sub"], "case": r["case"],
        "prompt": r["prompt"], "expected": r["expected"],
        "legal": r["legal"], "legal_hits": r["hits"], "cap_hits": r["cap_hits"],
        "axis": r["axis"], "vgrade": r["vgrade"], "v_required_total": b["validity"]["required_total"],
        "v_required_unmet": b["validity"]["required_unmet"], "grade_cap": r["grade_cap"],
        "uvgrade": r["uvgrade"], "uv_required_total": b["uv"]["required_total"], "uv_required_unmet": b["uv"]["required_unmet"],
        "intent": r["intent"], "slots": b["uv"]["slots"], "symptom": b["symptom"], "said": b["said"],
        "branch": (r.get("checklist") or {}).get("branch"),
        "all_items_v": [{"id": i["id"], "result": i["result"]} for i in r["vitems"]],
        "all_items_uv": [{"id": i["id"], "result": i["result"]} for i in r["uvitems"]],
        "sentences": [f"{i + 1}: {s[1] if isinstance(s, (list, tuple)) else s}" for i, s in enumerate(r["sents"])],
        "answer_chars": len(r["answer"] or ""),
        "summary": r["summary"], "items": items,
    }


def cmd_build(a):
    os.makedirs(a.out_dir, exist_ok=True)
    tmp_out = os.path.join(a.out_dir, "_viewer_tmp.html")
    rows, titles, required, snap_ver, runs = load_viewer_rows(a.run, a.snapshot, tmp_out)
    try:
        os.remove(tmp_out)
    except OSError:
        pass
    sel = [case_record(r, titles) for r in rows if is_cd(r)]
    sel.sort(key=lambda c: (c["run"], c["id"]))
    meta = {"generated": datetime.now(KST).isoformat(timespec="seconds"), "snapshot": snap_ver, "runs": runs,
            "total_results": len(rows), "selected": len(sel), "required": required, "titles": titles,
            "grade_dist": {
                lab: {"validity": dict(Counter(r["vgrade"] for r in rows if r["run"] == lab)),
                      "uv": dict(Counter(r["uvgrade"] for r in rows if r["run"] == lab))}
                for lab in sorted({r["run"] for r in rows})}}
    with open(os.path.join(a.out_dir, "cases.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "cases": sel}, f, ensure_ascii=False, indent=1)
    # 배치: run 별로 나눈다
    n = 0
    for lab in ([] if a.no_batches else sorted({c["run"] for c in sel})):
        cs = [c for c in sel if c["run"] == lab]
        k = max(1, -(-len(cs) // a.batch))
        size = -(-len(cs) // k)
        for i in range(k):
            n += 1
            part = cs[i * size:(i + 1) * size]
            with open(os.path.join(a.out_dir, f"batch_{n:02d}.json"), "w", encoding="utf-8") as f:
                json.dump(part, f, ensure_ascii=False, indent=1)
            print(f"[build] batch_{n:02d}: {lab} {len(part)}건, 미충족 {sum(len(c['items']) for c in part)}개")
    print(f"[build] 전체 {len(rows)}건 중 C 이하 {len(sel)}건, 미충족 항목 {sum(len(c['items']) for c in sel)}개 → {a.out_dir}")


# ── report ───────────────────────────────────────────────────────────────
class Grader:
    """판정기의 등급 함수(validity_phr.grade_from_items · validity_uv.grade_from_items · validity_symptom.apply_cap)를
    그대로 불러 쓴다. 10.16 덤프 1000건에서 저장 등급을 전부 재현함을 확인했다(불일치 0)."""

    def __init__(self, snapshot_path):
        sys.path.insert(0, os.path.join(HERE, "..", ".."))
        sys.path.insert(0, os.path.join(HERE, "..", "..", "packages", "medical_eval", "src"))
        from medical_eval import validity_phr, validity_uv, validity_symptom, phr_fact_check
        from medical_eval.ontology import load_snapshot, latest_snapshot_path
        p = snapshot_path or latest_snapshot_path(os.path.join(HERE, "..", "..", "packages", "medical_eval", "ontology", "snapshot"))
        s = load_snapshot(p)
        self.rules = [r for r in s.table("rule") if r.get("id")]
        self.th = phr_fact_check.thresholds(s)
        self.vp, self.vu, self.vs = validity_phr, validity_uv, validity_symptom
        self.version = s.version

    def regrade(self, axis, items, branch, legal_cap_hits):
        """items = [{id, result}] (재검토 반영 뒤). SV 는 LG-16 상한(SV-02 unmet · 응급 아님)과 법률 상한을 다시 적용."""
        if not items:
            return None
        if axis == "UV":
            g, _ = self.vu.grade_from_items(items, self.rules, self.th)
            return g
        g, b = self.vp.grade_from_items(items, self.rules, self.th)
        if axis == "SV":
            by = {i["id"]: i for i in items}
            lg16 = by.get("SV-02", {}).get("result") == "unmet" and branch != "응급"
            cap_ids = (["LG-16"] if lg16 else []) + [str(h) for h in (legal_cap_hits or [])]
            g, b = self.vs.apply_cap(g, b, cap_ids)
        return g


def cmd_report(a):
    data = json.load(open(os.path.join(a.data_dir, "cases.json"), encoding="utf-8"))
    meta, cases = data["meta"], data["cases"]
    required = meta["required"]
    verdicts = {}
    for p in sorted(glob.glob(os.path.join(a.data_dir, "verdicts_*.json"))):
        for v in json.load(open(p, encoding="utf-8")):
            verdicts[(v["run"], v["id"])] = v
    patterns = json.load(open(a.patterns, encoding="utf-8")) if a.patterns and os.path.exists(a.patterns) else []
    grader = Grader(a.snapshot)
    est_path = os.path.join(a.data_dir, "estimate_sv_any.json")
    est = json.load(open(est_path, encoding="utf-8")) if os.path.exists(est_path) else None

    missing_review = []
    by_rule = defaultdict(Counter)
    grade_moves, lenient_moves, remaining_d = Counter(), Counter(), []
    out_cases = []
    concl_path = os.path.join(a.data_dir, "conclusions.html")
    conclusions = open(concl_path, encoding="utf-8").read() if os.path.exists(concl_path) else ""
    for c in cases:
        v = verdicts.get((c["run"], c["id"]))
        vmap = {}
        if v:
            for it in v.get("items", []):
                vmap[it["id"]] = it
        else:
            missing_review.append(c["id"])
        items = []
        for it in c["items"]:
            jv = vmap.get(it["id"]) or {}
            verdict = jv.get("verdict") or "미검토"
            if verdict not in VERDICTS:
                verdict = "미검토" if verdict == "미검토" else "확인불가"
            if verdict == "미검토" and v:                       # 검토 파일은 있는데 이 항목만 빠짐 — 항목 단위로 기록
                missing_review.append(f"{c['id']}/{it['id']}")
            by_rule[it["id"]][verdict] += 1
            # 바로잡은 결과: 검토자가 corrected 를 적었으면 그대로, 아니면 '응급 분기라 na 여야 함' 유형은 na, 그 밖의 거짓·경계는 met
            corrected = jv.get("corrected") if jv.get("corrected") in ("met", "na") else (
                "na" if (jv.get("pattern") or "") == "응급분기_na누락" else "met")
            items.append(dict(it, verdict=verdict, reason=jv.get("reason") or "", ref_sentences=jv.get("sentences") or [],
                              pattern=jv.get("pattern") or "", corrected=corrected))
        # 재계산: 거짓(strict) 또는 거짓+경계(lenient)인 항목을 바로잡은 결과(met 또는 na)로 바꾼 뒤 판정기 등급 함수를 다시 적용.
        # na 는 required 분모에서 빠지므로 met 과 다르게 등급에 영향한다(2/4 미충족은 D, 2/5 는 C).
        def _re(all_items, axis, mode):
            drop = {"거짓"} if mode == "strict" else {"거짓", "경계"}
            fix = {i["id"]: i["corrected"] for i in items if (i["axis"] == "UV") == (axis == "UV") and i["verdict"] in drop}
            adj = [{"id": i["id"], "result": fix[i["id"]] if (i["result"] == "unmet" and i["id"] in fix) else i["result"]}
                   for i in all_items]
            return grader.regrade(axis, adj, c.get("branch"), c["cap_hits"])
        re_v = {m: _re(c.get("all_items_v") or [], c["axis"] or "PV", m) for m in ("strict", "lenient")} if c["vgrade"] else {}
        re_u = {m: _re(c.get("all_items_uv") or [], "UV", m) for m in ("strict", "lenient")} if c["uvgrade"] else {}
        if c["vgrade"] in ("C", "D"):
            grade_moves[(c["run"], c["axis"] or "PV", c["vgrade"], re_v.get("strict"))] += 1
            lenient_moves[(c["run"], c["axis"] or "PV", c["vgrade"], re_v.get("lenient"))] += 1
            if re_v.get("strict") == "D":
                remaining_d.append(f"{c['id']}({c['axis'] or 'PV'})")
        if c["uvgrade"] in ("C", "D"):
            grade_moves[(c["run"], "UV", c["uvgrade"], re_u.get("strict"))] += 1
            lenient_moves[(c["run"], "UV", c["uvgrade"], re_u.get("lenient"))] += 1
            if re_u.get("strict") == "D":
                remaining_d.append(f"{c['id']}(UV)")
        out_cases.append(dict(c, items=items, regrade_v=re_v, regrade_uv=re_u, reviewer_note=(v or {}).get("note", ""),
                              verdict_set=sorted({i["verdict"] for i in items})))

    total_items = sum(sum(cnt.values()) for cnt in by_rule.values())
    tot = Counter()
    for cnt in by_rule.values():
        tot.update(cnt)

    def pct(n, d):
        return f"{(100.0 * n / d):.0f}%" if d else "-"

    # 표 1: 항목별 분포
    rule_rows = []
    for rid, cnt in sorted(by_rule.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(cnt.values())
        rule_rows.append(f"<tr><td class=mono>{E(rid)}</td><td>{E(meta['titles'].get(rid, ''))}</td><td>{'필수' if required.get(rid) else '선택'}</td>"
                         f"<td class=num>{n}</td>" + "".join(f"<td class=num>{cnt.get(k, 0)}</td>" for k in VERDICTS)
                         + f"<td class=num><b>{pct(cnt.get('거짓', 0), n)}</b></td></tr>")
    # 표 2: 등급 이동(strict)
    move_rows = []
    for (run, axis, g0, g1), n in sorted(grade_moves.items()):
        move_rows.append(f"<tr><td>{E(run)}</td><td>{E(axis)}</td><td class=num>{E(g0)}</td><td class=num>{E(g1 or '-')}</td><td class=num>{n}</td>"
                         f"<td>{'유지' if g0 == g1 else '상향 ' + E(g0) + '→' + E(g1 or '-')}</td></tr>")
    stays = sum(n for (run, axis, g0, g1), n in grade_moves.items() if g0 == g1)
    moves_total = sum(grade_moves.values())
    to_ab = sum(n for (run, axis, g0, g1), n in grade_moves.items() if g1 in ("A", "B"))

    # 원인 유형
    pat_rows = []
    pat_count = Counter(i["pattern"] for c in out_cases for i in c["items"] if i["pattern"])
    pat_desc = {p["key"]: p for p in patterns}
    for key, n in pat_count.most_common():
        p = pat_desc.get(key, {})
        pat_rows.append(f"<tr><td class=mono>{E(key)}</td><td>{E(p.get('title', key))}</td><td class=num>{n}</td><td>{E(p.get('cause', ''))}</td><td>{E(p.get('fix', ''))}</td></tr>")

    # 사례 카드
    def item_html(i):
        ev = []
        if i["mismatch"]:
            ev.append("<div class=mm>" + " · ".join(E(m) for m in i["mismatch"]) + "</div>")
        for q in i["quotes"]:
            ev.append(f"<div class=q>「{E(q)}」</div>")
        if i["sentence_idx"]:
            ev.append(f"<div class=dim>지목 문장 {E(', '.join(map(str, i['sentence_idx'])))}</div>")
        if i["missing"]:
            ev.append("<div class=dim>답변이 확인하지 않은 항목</div>" + "".join(f"<span class=chip>{E(m)}</span>" for m in i["missing"]))
        if not ev:
            ev.append("<span class=dim>사유만 있음</span>")
        ref = f" <span class=dim>(문장 {E(', '.join(map(str, i['ref_sentences'])))})</span>" if i["ref_sentences"] else ""
        if i["verdict"] in ("거짓", "경계") and i.get("corrected") == "na":
            ref += " <span class=dim>→ na</span>"
        return (f"<tr class='v-{E(i['verdict'])}'><td class=mono>{E(i['id'])}<div class=dim>{E(i['title'])}</div></td>"
                f"<td>{E(i['detail'] or '')}</td><td>{''.join(ev)}</td>"
                f"<td><span class='vb v-{E(i['verdict'])}'>{E(i['verdict'])}</span>{ref}<div class=reason>{E(i['reason'])}</div>"
                f"{('<div class=dim>유형 ' + E(i['pattern']) + '</div>') if i['pattern'] else ''}</td></tr>")

    cards = []
    for c in out_cases:
        gl = []
        if c["vgrade"]:
            rv = c["regrade_v"]
            gl.append(f"<span class='g g-{E(c['vgrade'])}'>{E(c['axis'] or 'PV')} {E(c['vgrade'])}</span>"
                      + (f" → 거짓 제외 <b>{E(rv.get('strict'))}</b>" + (f" · 경계까지 제외 {E(rv.get('lenient'))}" if rv.get('lenient') != rv.get('strict') else "") if rv else ""))
        if c["uvgrade"]:
            ru = c["regrade_uv"]
            gl.append(f"<span class='g g-{E(c['uvgrade'])}'>UV {E(c['uvgrade'])}</span>"
                      + (f" → 거짓 제외 <b>{E(ru.get('strict'))}</b>" + (f" · 경계까지 제외 {E(ru.get('lenient'))}" if ru.get('lenient') != ru.get('strict') else "") if ru else ""))
        changed = (c["vgrade"] in ("C", "D") and c["regrade_v"].get("strict") not in (None, c["vgrade"])) or \
                  (c["uvgrade"] in ("C", "D") and c["regrade_uv"].get("strict") not in (None, c["uvgrade"]))
        meta_line = " · ".join(x for x in [E(c["run"]), E(c["cat"]), E(c["sub"]), E(c["symptom"] or ""), ("의도 " + E(c["intent"])) if c["intent"] else "",
                                            ("법률 " + E(c["legal"])) if c["legal"] else ""] if x)
        data_attr = (f'data-run="{E(c["run"])}" data-vg="{E(c["vgrade"] or "")}" data-uvg="{E(c["uvgrade"] or "")}" '
                     f'data-verdicts="{E(" ".join(c["verdict_set"]))}" data-rules="{E(" ".join(i["id"] for i in c["items"]))}" '
                     f'data-changed="{"1" if changed else "0"}" data-text="{E((c["id"] + " " + c["prompt"] + " " + " ".join(i["reason"] for i in c["items"])).lower())}"')
        sents = "".join(f"<div class=s>{E(s)}</div>" for s in c["sentences"])
        cards.append(f"""<details class=card {data_attr}><summary><span class=id>{E(c['id'])}</span> <span class=dim>{meta_line}</span><div class=prompt>{E(c['prompt'])}</div><div class=grades>{' &nbsp; '.join(gl)}</div>
<div class=vs>{''.join(f"<span class='vb v-{E(v)}'>{E(v)} {sum(1 for i in c['items'] if i['verdict'] == v)}</span>" for v in VERDICTS + ('미검토',) if any(i['verdict'] == v for i in c['items']))}</div></summary>
<div class=body>{('<div class=exp><b>기대 동작</b> ' + E(c['expected']) + '</div>') if c['expected'] else ''}
<table class=items><thead><tr><th>기준</th><th>판정기 사유</th><th>판정기 근거</th><th>검토 결과</th></tr></thead><tbody>{''.join(item_html(i) for i in c['items'])}</tbody></table>
{('<div class=note><b>검토자 메모</b> ' + E(c['reviewer_note']) + '</div>') if c['reviewer_note'] else ''}
<details class=ans><summary>답변 원문 (문장 번호, {len(c['sentences'])}문장)</summary>{sents}</details></div></details>""")

    runs_line = " · ".join(f"{E(r.get('label'))}: {E((r.get('run_at') or '')[:16])} {E(r.get('count') or '')}건" for r in meta["runs"]) if meta.get("runs") else ""
    gd = meta["grade_dist"]
    dist_rows = "".join(f"<tr><td>{E(lab)}</td><td class=num>{d['validity'].get('C', 0)}</td><td class=num>{d['validity'].get('D', 0)}</td><td class=num>{d['uv'].get('C', 0)}</td><td class=num>{d['uv'].get('D', 0)}</td></tr>" for lab, d in gd.items())
    false_cases = sum(1 for c in out_cases if "거짓" in c["verdict_set"])
    gen_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    est_html = ""
    if est:
        gb, ga = est["grade_before"], est["grade_after"]
        est_rows = "".join(f"<tr><td class=num>{g}</td><td class=num>{gb.get(g, 0)}</td><td class=num>{ga.get(g, 0)}</td></tr>" for g in GRADES)
        flip_rows = "".join(f"<tr><td class=mono>{E(k)}</td><td class=num>{est['unmet_before'].get(k, 0)}</td><td class=num>{est['unmet_to_met'].get(k, 0)}</td>"
                            f"<td class=num>{pct(est['unmet_to_met'].get(k, 0), est['unmet_before'].get(k, 0))}</td></tr>" for k in ("SV-02", "SV-03", "SV-04"))
        est_html = f"""<h2>5. 코드 규칙 하나의 영향 추정 — SV-02·03·04 키워드 매칭</h2>
<div class=dim>판정기(validity_symptom._mentions)는 체크리스트 항목의 키워드가 <b>모두</b> 답변에 있어야 '확인'으로 센다. 예: 복용약물 = 약·복용·먹고 셋 다, 기저질환 = 기저·당뇨·혈압·질환 넷 다, 전문가 상담 필요 = 악화·지속·심한 셋 다.
이를 '라벨 또는 강한 키워드 1개' 로 바꿔 일반 650 전체({est['results']}건)를 다시 계산한 결과(상한선 추정 — 실제 수정안은 LLM 2차 확인 등으로 이 사이에 놓인다).</div>
<div style="display:flex;gap:24px;flex-wrap:wrap"><table style="max-width:420px"><thead><tr><th>항목</th><th class=num>현행 미충족</th><th class=num>충족으로 바뀜</th><th class=num>비율</th></tr></thead><tbody>{flip_rows}</tbody></table>
<table style="max-width:320px"><thead><tr><th class=num>SV 등급</th><th class=num>현행</th><th class=num>바꾼 뒤</th></tr></thead><tbody>{est_rows}</tbody></table></div>"""

    page = f"""<!doctype html><html lang=ko><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>{E(a.title)}</title>
<style>
:root{{--bg:#fff;--fg:#1b1b1b;--dim:#6b7280;--border:#e5e7eb;--card:#fafafa;--ok:#15803d;--bad:#b91c1c;--mid:#b45309;--na:#475569}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#111315;--fg:#e7e7e7;--dim:#9aa3af;--border:#2b2f36;--card:#17191c}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.55 -apple-system,"Segoe UI","Malgun Gothic",sans-serif}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 8px}} .dim{{color:var(--dim);font-size:12.5px}} .mono{{font-family:Consolas,monospace;white-space:nowrap}}
table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{border:1px solid var(--border);padding:5px 8px;text-align:left;vertical-align:top}} th{{background:var(--card)}} td.num,th.num{{text-align:right;white-space:nowrap}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}} .kpi div{{border:1px solid var(--border);border-radius:8px;padding:8px 14px;background:var(--card)}} .kpi b{{font-size:20px;display:block}}
.bar{{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap;align-items:center;z-index:2}}
.bar select,.bar input{{font:13px inherit;padding:4px 6px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--fg)}}
.card{{border:1px solid var(--border);border-radius:8px;margin:10px 0;background:var(--card)}} .card>summary{{padding:10px 12px;cursor:pointer;list-style:none}} .card>summary::-webkit-details-marker{{display:none}}
.card .id{{font-weight:700}} .prompt{{margin:4px 0}} .grades{{margin:4px 0}} .g{{display:inline-block;padding:0 8px;border-radius:10px;font-weight:700;border:1px solid var(--border)}}
.g-C{{color:var(--mid)}} .g-D{{color:var(--bad)}} .g-A,.g-B{{color:var(--ok)}}
.vb{{display:inline-block;padding:0 7px;border-radius:10px;font-size:12px;font-weight:700;border:1px solid var(--border);margin-right:4px}}
.v-타당{{color:var(--ok)}} .v-거짓{{color:var(--bad)}} .v-경계{{color:var(--mid)}} .v-확인불가,.v-미검토{{color:var(--na)}}
tr.v-거짓 td{{background:rgba(185,28,28,.06)}} tr.v-경계 td{{background:rgba(180,83,9,.06)}}
.body{{padding:0 12px 12px}} .items td:first-child{{white-space:nowrap}} .q{{color:var(--fg)}} .mm{{font-family:Consolas,monospace;font-size:12.5px}} .reason{{margin-top:3px}}
.chip{{display:inline-block;border:1px solid var(--border);border-radius:4px;padding:0 6px;margin:2px 3px 0 0;font-size:12px}}
.ans{{margin-top:8px}} .ans summary{{cursor:pointer;color:var(--dim)}} .s{{font-size:12.5px;padding:1px 0;border-bottom:1px dashed var(--border)}} .exp,.note{{margin:8px 0;font-size:13px}}
.hide{{display:none}}
</style></head><body>
<h1>{E(a.title)}</h1>
<div class=dim>{runs_line} · 온톨로지 {E(meta.get('snapshot') or '?')} · 생성 {gen_at}</div>
<p>{E(a.note)}</p>
<div class=kpi><div><b>{meta['total_results']}</b>전체 결과</div><div><b>{meta['selected']}</b>C 이하(유효성 또는 UV)</div><div><b>{total_items}</b>미충족 항목</div>
<div><b>{tot.get('타당', 0)}</b>타당</div><div><b>{tot.get('거짓', 0)}</b>거짓 ({pct(tot.get('거짓', 0), total_items)})</div><div><b>{tot.get('경계', 0)}</b>경계</div><div><b>{tot.get('확인불가', 0)}</b>확인불가</div>{('<div><b>' + str(tot.get('미검토', 0)) + '</b>미검토</div>') if tot.get('미검토') else ''}
<div><b>{false_cases}</b>거짓 항목이 있는 결과</div><div><b>{to_ab}/{moves_total}</b>거짓 제외 시 A·B 로 오르는 등급</div></div>
{conclusions}

<h2>1. C 이하 분포 (실행별)</h2>
<table><thead><tr><th>실행</th><th class=num>유효성 C</th><th class=num>유효성 D</th><th class=num>UV C</th><th class=num>UV D</th></tr></thead><tbody>{dist_rows}</tbody></table>

<h2>2. 기준별 검토 결과</h2>
<div class=dim>거짓 = 답변이 기준을 실제로 충족하는데 미충족으로 판정됨. 경계 = 규칙 문언대로면 미충족이나 사람이 보면 충족에 가깝거나 기준이 문항과 맞지 않음.</div>
<table><thead><tr><th>기준</th><th>제목</th><th>필수</th><th class=num>미충족</th>{''.join(f'<th class=num>{k}</th>' for k in VERDICTS)}<th class=num>거짓 비율</th></tr></thead><tbody>{''.join(rule_rows)}</tbody></table>

<h2>3. 거짓 항목을 뺐을 때 등급 이동</h2>
<div class=dim>거짓으로 검토된 항목을 바로잡은 결과(충족, 또는 응급 분기라 판정 대상이 아닌 항목은 na)로 바꾼 뒤 판정기의 등급 함수(필수 미충족 0/1/2/3+ → A/B/C/D, PV·SV 는 절반 이상 D, PV-01·02 는 D, SV-02 미충족이면 LG-16 상한 C)를 그대로 다시 적용. 유지 {stays}/{moves_total}.</div>
<table><thead><tr><th>실행</th><th>축</th><th class=num>원래</th><th class=num>재계산</th><th class=num>건수</th><th>변화</th></tr></thead><tbody>{''.join(move_rows)}</tbody></table>

<h2>4. 거짓·경계의 원인 유형</h2>
<table><thead><tr><th>유형</th><th>설명</th><th class=num>건수</th><th>원인</th><th>대책</th></tr></thead><tbody>{''.join(pat_rows) or '<tr><td colspan=5 class=dim>유형 미기재</td></tr>'}</tbody></table>
{('<div class=dim>검토 누락 ' + str(len(missing_review)) + '건: ' + E(', '.join(missing_review[:20])) + '</div>') if missing_review else ''}
{est_html}

<h2>{'6' if est else '5'}. 결과별 상세 ({len(out_cases)}건)</h2>
<div class=bar>
<select id=fRun><option value="">실행 전체</option>{''.join(f'<option>{E(l)}</option>' for l in gd)}</select>
<select id=fAxis><option value="">등급 축</option><option value=vg>유효성(PV·SV) C/D</option><option value=uvg>UV C/D</option></select>
<select id=fVerdict><option value="">검토 결과</option>{''.join(f'<option>{v}</option>' for v in VERDICTS + ('미검토',))}</select>
<select id=fChanged><option value="">등급 변화</option><option value=1>거짓 제외 시 등급 상향</option><option value=0>등급 유지</option></select>
<input id=fRule placeholder="기준 id (예: SV-02)" size=12><input id=fText placeholder="문항 id·질문·검토 사유 검색" size=28>
<span id=nShown class=dim></span><button id=bOpen>모두 펼치기</button><button id=bClose>접기</button></div>
<div id=list>{''.join(cards)}</div>
<script>
(function(){{
const $=s=>document.querySelector(s);const cards=[...document.querySelectorAll('.card')];
function apply(){{const run=$('#fRun').value,axis=$('#fAxis').value,vd=$('#fVerdict').value,ch=$('#fChanged').value,rule=$('#fRule').value.trim().toUpperCase(),tx=$('#fText').value.trim().toLowerCase();let n=0;
for(const c of cards){{let ok=true;if(run&&c.dataset.run!==run)ok=false;if(axis==='vg'&&!/^[CD]$/.test(c.dataset.vg))ok=false;if(axis==='uvg'&&!/^[CD]$/.test(c.dataset.uvg))ok=false;
if(vd&&!c.dataset.verdicts.split(' ').includes(vd))ok=false;if(ch!==''&&c.dataset.changed!==ch)ok=false;if(rule&&!c.dataset.rules.split(' ').includes(rule))ok=false;if(tx&&!c.dataset.text.includes(tx))ok=false;
c.classList.toggle('hide',!ok);if(ok)n++;}}$('#nShown').textContent=n+'건 표시';}}
for(const id of ['fRun','fAxis','fVerdict','fChanged'])$('#'+id).addEventListener('change',apply);for(const id of ['fRule','fText'])$('#'+id).addEventListener('input',apply);
$('#bOpen').addEventListener('click',()=>cards.forEach(c=>{{if(!c.classList.contains('hide'))c.open=true}}));$('#bClose').addEventListener('click',()=>cards.forEach(c=>c.open=false));apply();
}})();
</script></body></html>"""
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(page)
    summary = {"total_items": total_items, "verdicts": dict(tot), "false_cases": false_cases, "grade_moves": {f"{k[0]}|{k[1]}|{k[2]}->{k[3]}": n for k, n in grade_moves.items()},
               "lenient_moves": {f"{k[0]}|{k[1]}|{k[2]}->{k[3]}": n for k, n in lenient_moves.items()}, "remaining_d": remaining_d,
               "by_rule": {k: dict(v) for k, v in by_rule.items()}, "patterns": dict(pat_count), "missing_review": missing_review}
    with open(os.path.join(a.data_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print(f"[report] {len(out_cases)}건 · 미충족 {total_items} · {dict(tot)} → {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB)")
    print(f"[report] 등급 이동(strict): {json.dumps(summary['grade_moves'], ensure_ascii=False)}")
    if missing_review:
        print(f"[report] 검토 누락 {len(missing_review)}건")


def _rule_ids(hits):
    """legal_cap_hits 는 compact 덤프에서는 규칙 id 문자열, 판정기 원형에서는 {rule_id,...} dict — 둘 다 받는다."""
    out = []
    for h in hits or []:
        out.append(str(h if isinstance(h, str) else (h.get("rule_id") if isinstance(h, dict) else h)))
    return out


# ── estimate: SV-02·03·04 키워드 규칙 하나를 바꿨을 때 ─────────────────────────
def cmd_estimate(a):
    """판정기 validity_symptom._mentions(loose=False) 는 체크리스트 항목의 키워드가 **모두** 답변에 있어야 '확인'으로 센다
    ('복용약물' = 약·복용·먹고 셋 다). 이를 '라벨 또는 강한 키워드 하나' 로 바꿨을 때 일반 650 의 SV 항목·등급이
    어떻게 달라지는지 센다(상한선 추정 — 실제 수정안은 LLM 2차 확인 등으로 그 사이에 놓인다)."""
    grader = Grader(a.snapshot)
    vs = grader.vs
    import mhc_viz
    groups = {g["symptom_key"]: g for g in json.load(open(a.checklists, encoding="utf-8"))}
    rows = []
    d = json.load(open(a.dump, encoding="utf-8"))

    def walk(o):
        if isinstance(o, dict):
            if "scenarioId" in o and "evalV3" in o:
                rows.append(o)
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)

    def alt_mentions(text, e):
        label = vs._norm(e.get("label"))
        if label and label.replace(" ", "") in text.replace(" ", ""):
            return True
        strong = [k for k in (e.get("keywords") or []) if k and k not in vs._WEAK_KEYWORDS]
        return any(k in text for k in strong)

    flip, before, after = Counter(), Counter(), Counter()
    for r in rows:
        v = r["evalV3"]
        items = v.get("validity_items") or []
        cl = v.get("checklist") or {}
        key = cl.get("symptom_key")
        before[v.get("validity_grade")] += 1
        if not key or key not in groups or not items:
            after[v.get("validity_grade")] += 1
            continue
        g = groups[key]
        ans = vs._norm(mhc_viz.strip_blocks(r.get("response") or ""))
        user = vs._norm(r.get("prompt") or "") + " "
        new = [dict(i) for i in items]
        for i in new:
            if i["result"] != "unmet":
                continue
            if i["id"] == "SV-02":
                cov = [f for f in g.get("red_flags") or [] if alt_mentions(ans, f)]
            elif i["id"] == "SV-03":
                pend = [q for q in g.get("required_questions") or [] if not vs._mentions(user, q, loose=True)]
                cov = [q for q in pend if alt_mentions(ans, q)]
            elif i["id"] == "SV-04":
                cov = [q for q in g.get("context_questions") or [] if alt_mentions(ans, q)]
            else:
                continue
            if cov:
                i["result"] = "met"
                flip[i["id"]] += 1
        after[grader.regrade("SV", new, cl.get("branch"), _rule_ids(v.get("legal_cap_hits")))] += 1
    unmet_before = Counter(i["id"] for r in rows for i in (r["evalV3"].get("validity_items") or [])
                           if i["result"] == "unmet" and i["id"] in ("SV-02", "SV-03", "SV-04"))
    out = {"rule": "라벨 또는 강한 키워드 1개(현행: 키워드 전부)", "results": len(rows), "unmet_before": dict(unmet_before),
           "unmet_to_met": dict(flip), "grade_before": {str(k): n for k, n in before.items()}, "grade_after": {str(k): n for k, n in after.items()},
           "branches": {str(k): n for k, n in Counter((r["evalV3"].get("checklist") or {}).get("branch") for r in rows).items()}}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"[estimate] {json.dumps(out, ensure_ascii=False)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate")
    e.add_argument("--dump", required=True, help="일반 650 덤프 json")
    e.add_argument("--checklists", default=os.path.join(HERE, "..", "..", "packages", "medical_shared", "compliance_rules", "consultation_checklists.json"))
    e.add_argument("--snapshot", default=None)
    e.add_argument("--out", required=True)
    b = sub.add_parser("build")
    b.add_argument("--run", action="append", required=True)
    b.add_argument("--out-dir", required=True)
    b.add_argument("--snapshot", default=None)
    b.add_argument("--batch", type=int, default=40)
    b.add_argument("--no-batches", action="store_true", help="cases.json 만 다시 쓰고 배치 파일은 건드리지 않는다")
    r = sub.add_parser("report")
    r.add_argument("--data-dir", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--snapshot", default=None, help="온톨로지 스냅샷(등급 재계산에 판정기 함수를 쓴다)")
    r.add_argument("--patterns", default=None)
    r.add_argument("--title", default="C 이하 등급 판정 타당성 검토")
    r.add_argument("--note", default="")
    a = ap.parse_args()
    {"build": cmd_build, "report": cmd_report, "estimate": cmd_estimate}[a.cmd](a)


if __name__ == "__main__":
    main()
