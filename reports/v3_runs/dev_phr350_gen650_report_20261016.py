# -*- coding: utf-8 -*-
"""Dev 환경 PHR 350건 + 일반 650건 순차 테스트 결과 리포트 (판정기 v3.18, 판정 모델 gpt-6-luna / 2차 gpt-6-sol).

입력: dumps/<PHR run>.json, dumps/<일반 run>.json (test_runs.results_json 덤프; 답변 원문은 길이·스탬프 계산에만 쓴다)
      dumps/rules.json (규칙 제목), dumps/inv_phr350.json (문항 유형 T#·카테고리·서브카테고리)
      선택: --prev-phr <이전 Dev PHR 350 덤프> (같은 판정 모델이면 등급 이동 비교), --prev-gen <이전 일반 덤프> (겹치는 id 만)
사용: python dev_phr350_gen650_report_20261016.py --phr dumps/A.json --gen dumps/B.json --out <html> [--prev-phr ...] [--prev-gen ...]
"""
import argparse, html, json, re, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

ap = argparse.ArgumentParser()
ap.add_argument("--phr", required=True); ap.add_argument("--gen", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--prev-phr", default=None); ap.add_argument("--prev-gen", default=None)
ap.add_argument("--prev-phr-label", default="이전 Dev 실행"); ap.add_argument("--prev-gen-label", default="이전 Dev 실행")
ap.add_argument("--rules", default="dumps/rules.json"); ap.add_argument("--inv", default="dumps/inv_phr350.json")
ap.add_argument("--sample", default=None, help="일반 표본 json (desc·by_category)")
ap.add_argument("--rerun", default=None, help="같은 650건을 같은 시각에 한 번 더 돌린 덤프(재현성 비교)")
ap.add_argument("--perf-note", default="", help="응답 성능 해석 주의 문구")
ap.add_argument("--date", default=datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d"))
a = ap.parse_args()

E = lambda s: html.escape(str(s if s is not None else ""))
KST = timezone(timedelta(hours=9))


def load(p):
    if not p:
        return None, {}
    d = json.load(open(p, encoding="utf-8"))
    rs = d.get("results_json") or d.get("results") or []
    return d, {r["scenarioId"]: r for r in rs}


runP, P = load(a.phr)
runG, G = load(a.gen)
prevP = load(a.prev_phr)[1]
prevG = load(a.prev_gen)[1]
rerunG = load(a.rerun)[1]
rules = (json.load(open(a.rules, encoding="utf-8")) or {}).get("rules", {})
inv = {r["id"]: r for r in json.load(open(a.inv, encoding="utf-8"))["rows"]}
sample = json.load(open(a.sample, encoding="utf-8")) if a.sample else {}

g = lambda r, k: (r.get("evalV3") or {}).get(k)
title_of = lambda rid: (rules.get(rid) or {}).get("title") or ""
# 법률 게이트 FAIL 을 둘로 나눈다: 확정 규칙 적중(hits 있음) / 법무 회신 대기 규칙만 적중(review-only)
conf = lambda r: "fail" if g(r, "legal_verdict") == "fail" and (g(r, "legal_hits") or []) else ("review" if g(r, "legal_verdict") == "fail" else "pass")
avg = lambda xs: round(sum(xs) / len(xs)) if xs else 0
pct = lambda k, d: f"{k} ({k * 100 / d:.0f}%)" if d else str(k)
med = lambda xs: round(statistics.median(xs)) if xs else 0
p95 = lambda xs: round(sorted(xs)[max(0, int(len(xs) * 0.95) - 1)]) if xs else 0


def stamp_of(R):
    c = Counter()
    for r in R.values():
        m = re.match(r"^\s*\(([^)\n]{1,40})\)", r.get("response") or "")
        c[m.group(1) if m else "(스탬프 없음)"] += 1
    return c


is_resp_fail = lambda r: r.get("httpStatus") != 200 or not (r.get("response") or "").strip() or bool(r.get("partialResponse"))


def meta(R):
    return dict(
        onto=Counter(g(r, "ontology_version") for r in R.values()).most_common(1)[0][0] if R else "",
        judge=Counter(g(r, "judge_model") for r in R.values()),
        legal_ver=Counter(g(r, "legal_version") for r in R.values()).most_common(1)[0][0] if R else "",
        stamp=stamp_of(R),
        fallback=[i for i, r in R.items() if (g(r, "claim_fallback") or 0) > 0],
        http_err=[i for i, r in R.items() if r.get("httpStatus") != 200 or r.get("status") not in ("pass", "fail")],
        resp_fail=[i for i, r in R.items() if is_resp_fail(r)],
        retried=[i for i, r in R.items() if (r.get("attempts") or 1) > 1],
        lens=[len(r.get("response") or "") for r in R.values()],
        ttft=[r.get("firstTokenMs") for r in R.values() if r.get("firstTokenMs")],
        tot=[r.get("responseTime") for r in R.values() if r.get("responseTime")],
    )


def run_span(run):
    rs = run.get("results_json") or run.get("results") or []
    ts = [r.get("completedAt") or r.get("timestamp") for r in rs if r.get("completedAt") or r.get("timestamp")]
    return run.get("run_at"), len(ts)


def dist_row(label, c, keys):
    return f"<tr><th>{E(label)}</th>" + "".join(f"<td>{c.get(k, 0)}</td>" for k in keys) + "</tr>"


def unmet_table(c, denom):
    out = ["<table><thead><tr><th>항목</th><th>이름</th><th>미충족 건수</th><th>비율</th></tr></thead><tbody>"]
    for k, v in c.most_common():
        out.append(f"<tr><td><b>{E(k)}</b></td><td>{E(title_of(k))}</td><td>{v}</td><td>{v * 100 / denom:.0f}%</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


def legal_table(R, ids, extra_col):
    out = [f"<table><thead><tr><th>문항</th><th>{E(extra_col[0])}</th><th>구분</th><th>적중 규칙</th><th>규칙 이름</th><th>판정 모델</th><th>claim 수준</th></tr></thead><tbody>"]
    for i in ids:
        r = R[i]
        hits = g(r, 'legal_hits') or []
        rv = g(r, 'legal_review_hits') or []
        kind = "확정 위반" if hits else "회신 대기 규칙만"
        shown = hits if hits else rv
        out.append(f"<tr><td>{E(i)}</td><td>{E(extra_col[1](i))}</td><td class={'bad' if hits else 'small'}>{E(kind)}</td><td>{E(', '.join(shown))}</td>"
                   f"<td>{E(' / '.join(title_of(h) for h in shown))}</td><td>{E(g(r, 'judge_model'))}</td><td class=small>{E(g(r, 'legal_max_level'))}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


# ═══════════════════ PHR 350 ═══════════════════
Pids = sorted(P); nP = len(Pids); mP = meta(P)
qtype = lambda i: (inv.get(i) or {}).get("qtype") or (P.get(i) or {}).get("subcategory") or "?"
legalP = Counter(g(P[i], "legal_verdict") for i in Pids)
pv = Counter(str(g(P[i], "validity_grade")) for i in Pids)
uv = Counter(str(g(P[i], "uv_grade")) for i in Pids)
scoredP = [i for i in Pids if g(P[i], "validity_status") == "ok"]
skippedP = [i for i in Pids if g(P[i], "validity_status") != "ok"]
uv_scoredP = [i for i in Pids if g(P[i], "uv_status") == "ok"]
all_a = [i for i in Pids if g(P[i], "validity_grade") == "A" and g(P[i], "uv_grade") == "A" and g(P[i], "legal_verdict") == "pass"]
pass_bar = [i for i in Pids if g(P[i], "validity_grade") in ("A", "B") and g(P[i], "uv_grade") in ("A", "B") and g(P[i], "legal_verdict") == "pass"]
pv_unmet = Counter(x for i in Pids for x in (g(P[i], "validity_unmet") or []))
uv_unmet = Counter(x for i in Pids for x in (g(P[i], "uv_unmet") or []))
legal_failP = [i for i in Pids if g(P[i], "legal_verdict") == "fail"]
confP = [i for i in legal_failP if conf(P[i]) == "fail"]; revP = [i for i in legal_failP if conf(P[i]) == "review"]
lg_hitsP = Counter(h for i in Pids for h in (g(P[i], "legal_hits") or []))


def by_group_phr(keyf):
    by = defaultdict(Counter)
    for i in Pids:
        k = keyf(i); c = by[k]
        c["n"] += 1
        c["legal_fail"] += g(P[i], "legal_verdict") == "fail"
        c["pvA"] += g(P[i], "validity_grade") == "A"; c["pvCD"] += g(P[i], "validity_grade") in ("C", "D")
        c["uvA"] += g(P[i], "uv_grade") == "A"; c["uvCD"] += g(P[i], "uv_grade") in ("C", "D")
        c["allA"] += i in all_a
        for x in (g(P[i], "validity_unmet") or []) + (g(P[i], "uv_unmet") or []):
            c["u:" + x] += 1
    return by


def group_table_phr(by, label):
    rows = sorted(by.items(), key=lambda kv: (-kv[1]["n"], str(kv[0])))
    out = [f"<table><thead><tr><th>{E(label)}</th><th>건</th><th>법률 FAIL</th><th>PV A</th><th>PV C·D</th><th>UV A</th><th>UV C·D</th><th>모두 A</th><th>주요 미충족(건)</th></tr></thead><tbody>"]
    for k, c in rows:
        um = sorted(((x[2:], v) for x, v in c.items() if x.startswith("u:")), key=lambda kv: -kv[1])[:4]
        out.append(f"<tr><td><b>{E(k)}</b></td><td>{c['n']}</td><td>{c['legal_fail']}</td><td>{c['pvA']}</td><td>{c['pvCD']}</td><td>{c['uvA']}</td><td>{c['uvCD']}</td><td>{c['allA']}</td><td class=small>{E(', '.join(f'{x} {v}' for x, v in um))}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


pv01 = []
for i in Pids:
    if "PV-01" in (g(P[i], "validity_unmet") or []):
        fc = g(P[i], "fact_check") or {}
        det = next((it.get("detail") for it in (g(P[i], "validity_items") or []) if it.get("id") == "PV-01"), "")
        pv01.append((i, qtype(i), g(P[i], "uv_intent"), fc.get("cited"), fc.get("matched"), fc.get("fabricated"), det))

prevP_html = ""
if prevP:
    common = sorted(set(P) & set(prevP))
    if common:
        def dist(RR):
            return (Counter(g(RR[i], "legal_verdict") for i in common), Counter(str(g(RR[i], "validity_grade")) for i in common),
                    Counter(str(g(RR[i], "uv_grade")) for i in common),
                    sum(1 for i in common if g(RR[i], "validity_grade") == "A" and g(RR[i], "uv_grade") == "A" and g(RR[i], "legal_verdict") == "pass"),
                    Counter(x for i in common for x in (g(RR[i], "validity_unmet") or [])),
                    Counter(x for i in common for x in (g(RR[i], "uv_unmet") or [])),
                    sum(1 for i in common if g(RR[i], "validity_grade") in ("A", "B") and g(RR[i], "uv_grade") in ("A", "B") and g(RR[i], "legal_verdict") == "pass"))
        p, c = dist(prevP), dist(P)
        keys = ["A", "B", "C", "D"]
        tr = Counter(f"{g(prevP[i], 'validity_grade')}→{g(P[i], 'validity_grade')}" for i in common if g(prevP[i], "validity_grade") != g(P[i], "validity_grade"))
        tru = Counter(f"{g(prevP[i], 'uv_grade')}→{g(P[i], 'uv_grade')}" for i in common if g(prevP[i], "uv_grade") != g(P[i], "uv_grade"))
        items = Counter()
        for i in common:
            for ax in ("validity_unmet", "uv_unmet"):
                A, B = set(g(prevP[i], ax) or []), set(g(P[i], ax) or [])
                for x in B - A: items[f"{x} 새로 미충족"] += 1
                for x in A - B: items[f"{x} 해소"] += 1
        lf_prev, lf_now = set(i for i in common if g(prevP[i], "legal_verdict") == "fail"), set(i for i in common if g(P[i], "legal_verdict") == "fail")
        prev_stamp = stamp_of(prevP).most_common(1)[0][0]
        prev_judge = ", ".join(f"{k} {v}" for k, v in Counter(g(prevP[i], "judge_model") for i in common).most_common())
        prevP_html = f"""
<h2 id=pprev>2-6. {E(a.prev_phr_label)}과의 비교 — 겹치는 {len(common)}건</h2>
<p class=small>이전: 프롬프트 스탬프 {E(prev_stamp)} · 판정 모델 {E(prev_judge)}. 같은 문항·같은 판정기(온톨로지 {E(mP['onto'])})이므로 차이는 답변 변화와 판정 모델의 흔들림을 합친 것이다.</p>
<table><thead><tr><th></th><th>법률 FAIL</th><th>PV A</th><th>PV B</th><th>PV C</th><th>PV D</th><th>UV A</th><th>UV B</th><th>UV C</th><th>UV D</th><th>모두 A</th><th>합격선(A/B)</th></tr></thead><tbody>
<tr><th>{E(a.prev_phr_label)}</th><td>{p[0].get('fail', 0)}</td>{''.join(f'<td>{p[1].get(k, 0)}</td>' for k in keys)}{''.join(f'<td>{p[2].get(k, 0)}</td>' for k in keys)}<td>{p[3]}</td><td>{p[6]}</td></tr>
<tr><th>이번 실행</th><td>{c[0].get('fail', 0)}</td>{''.join(f'<td>{c[1].get(k, 0)}</td>' for k in keys)}{''.join(f'<td>{c[2].get(k, 0)}</td>' for k in keys)}<td>{c[3]}</td><td>{c[6]}</td></tr>
</tbody></table>
<div class=cols><div><h3>PV 등급 이동</h3><table><tbody>{''.join(f'<tr><td>{E(k)}</td><td>{v}</td></tr>' for k, v in tr.most_common())}</tbody></table></div>
<div><h3>UV 등급 이동</h3><table><tbody>{''.join(f'<tr><td>{E(k)}</td><td>{v}</td></tr>' for k, v in tru.most_common())}</tbody></table></div>
<div><h3>항목 변화</h3><table><tbody>{''.join(f'<tr><td>{E(k)}</td><td>{v}</td></tr>' for k, v in items.most_common(14))}</tbody></table></div></div>
<p class=small>법률 FAIL: 이전에만 {len(lf_prev - lf_now)}건({E(', '.join(sorted(lf_prev - lf_now)))}) · 이번에만 {len(lf_now - lf_prev)}건({E(', '.join(sorted(lf_now - lf_prev)))}) · 둘 다 {len(lf_prev & lf_now)}건({E(', '.join(sorted(lf_prev & lf_now)))}).
미충족 합계: PV-03 {p[4].get('PV-03', 0)}→{c[4].get('PV-03', 0)} · PV-04 {p[4].get('PV-04', 0)}→{c[4].get('PV-04', 0)} · PV-05 {p[4].get('PV-05', 0)}→{c[4].get('PV-05', 0)} · PV-01 {p[4].get('PV-01', 0)}→{c[4].get('PV-01', 0)} · UV-01 {p[5].get('UV-01', 0)}→{c[5].get('UV-01', 0)} · UV-02 {p[5].get('UV-02', 0)}→{c[5].get('UV-02', 0)} · UV-04 {p[5].get('UV-04', 0)}→{c[5].get('UV-04', 0)} · UV-06 {p[5].get('UV-06', 0)}→{c[5].get('UV-06', 0)}</p>
"""

# ═══════════════════ 일반 650 ═══════════════════
Gids = sorted(G); nG = len(Gids); mG = meta(G)
cat = lambda i: (inv.get(i) or {}).get("category") or (G.get(i) or {}).get("category") or "?"
sub = lambda i: (inv.get(i) or {}).get("subcategory") or (G.get(i) or {}).get("subcategory") or ""
branch = lambda i: ((inv.get(i) or {}).get("cls") or {}).get("branch") or ((g(G[i], "checklist") or {}).get("branch")) or "미분류(기대 동작에 분기 없음)"
legalG = Counter(g(G[i], "legal_verdict") for i in Gids)
sv = Counter(str(g(G[i], "validity_grade")) for i in Gids)
modeG = Counter(g(G[i], "mode") for i in Gids)
sv_unmet = Counter(x for i in Gids for x in (g(G[i], "validity_unmet") or []))
legal_failG = [i for i in Gids if g(G[i], "legal_verdict") == "fail"]
confG = [i for i in legal_failG if conf(G[i]) == "fail"]; revG = [i for i in legal_failG if conf(G[i]) == "review"]
lg_hitsG = Counter(h for i in Gids for h in (g(G[i], "legal_hits") or []))
sv_scored = [i for i in Gids if g(G[i], "validity_status") == "ok"]
good_g = [i for i in Gids if g(G[i], "legal_verdict") == "pass" and g(G[i], "validity_grade") in ("A", "B")]
SMALL = {"피부", "머리·뇌·신경계", "전신·피로·발열", "소화기", "순환기", "호흡기", "감각기관", "근골격계", "비뇨생식기", "정신건강"}
catg = lambda i: "분과 10종" if cat(i) in SMALL else cat(i)


def by_group_gen(keyf):
    by = defaultdict(Counter)
    for i in Gids:
        k = keyf(i); c = by[k]
        c["n"] += 1
        c["legal_fail"] += g(G[i], "legal_verdict") == "fail"
        for gr in "ABCD":
            c["sv" + gr] += g(G[i], "validity_grade") == gr
        c["err"] += is_resp_fail(G[i])
        for x in (g(G[i], "validity_unmet") or []):
            c["u:" + x] += 1
        for h in (g(G[i], "legal_hits") or []):
            c["l:" + h] += 1
        tt = G[i].get("firstTokenMs")
        if tt: c["ttft_sum"] += tt; c["ttft_n"] += 1
    return by


def group_table_gen(by, label):
    rows = sorted(by.items(), key=lambda kv: (-kv[1]["n"], str(kv[0])))
    out = [f"<table><thead><tr><th>{E(label)}</th><th>건</th><th>법률 FAIL</th><th>적중 규칙</th><th>SV A</th><th>SV B</th><th>SV C</th><th>SV D</th><th>응답 오류</th><th>첫 토큰 평균(s)</th><th>주요 미충족(건)</th></tr></thead><tbody>"]
    for k, c in rows:
        um = sorted(((x[2:], v) for x, v in c.items() if x.startswith("u:")), key=lambda kv: -kv[1])[:4]
        lh = sorted(((x[2:], v) for x, v in c.items() if x.startswith("l:")), key=lambda kv: -kv[1])[:4]
        tt = f"{c['ttft_sum'] / c['ttft_n'] / 1000:.1f}" if c["ttft_n"] else "-"
        out.append(f"<tr><td><b>{E(k)}</b></td><td>{c['n']}</td><td>{c['legal_fail']}</td><td class=small>{E(', '.join(f'{x} {v}' for x, v in lh))}</td><td>{c['svA']}</td><td>{c['svB']}</td><td>{c['svC']}</td><td>{c['svD']}</td><td>{c['err']}</td><td>{tt}</td><td class=small>{E(', '.join(f'{x} {v}' for x, v in um))}</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


prevG_html = ""
if prevG:
    common = sorted(set(G) & set(prevG))
    if common:
        pj = ", ".join(f"{k} {v}" for k, v in Counter(g(prevG[i], "judge_model") for i in common).most_common())
        cj = ", ".join(f"{k} {v}" for k, v in Counter(g(G[i], "judge_model") for i in common).most_common())
        pl, cl = Counter(g(prevG[i], "legal_verdict") for i in common), Counter(g(G[i], "legal_verdict") for i in common)
        ps, cs = Counter(str(g(prevG[i], "validity_grade")) for i in common), Counter(str(g(G[i], "validity_grade")) for i in common)
        pu, cu = Counter(x for i in common for x in (g(prevG[i], "validity_unmet") or [])), Counter(x for i in common for x in (g(G[i], "validity_unmet") or []))
        trs = Counter(f"{g(prevG[i], 'validity_grade')}→{g(G[i], 'validity_grade')}" for i in common if g(prevG[i], "validity_grade") != g(G[i], "validity_grade"))
        lf_prev, lf_now = set(i for i in common if g(prevG[i], "legal_verdict") == "fail"), set(i for i in common if g(G[i], "legal_verdict") == "fail")
        prev_stamp = stamp_of({i: prevG[i] for i in common}).most_common(1)[0][0]
        keys = ["A", "B", "C", "D"]
        prevG_html = f"""
<h2 id=gprev>3-5. {E(a.prev_gen_label)}과의 비교 — 겹치는 {len(common)}건</h2>
<p class=note>이전 실행의 판정 모델은 {E(pj)}, 이번은 {E(cj)} 이다. 판정 모델이 다르므로 아래 차이에는 모델 차이가 섞여 있다(2026-10-14 판정 모델 3자 비교에서 gpt-6-luna 는 gpt-5.4-mini 보다 법률 FAIL 을 적게, SV C·D 를 비슷하게 매겼다). 이전 프롬프트 스탬프: {E(prev_stamp)}.</p>
<table><thead><tr><th></th><th>법률 FAIL</th><th>SV A</th><th>SV B</th><th>SV C</th><th>SV D</th><th>SV-02</th><th>SV-03</th><th>SV-04</th><th>SV-01</th><th>SV-05</th></tr></thead><tbody>
<tr><th>{E(a.prev_gen_label)}</th><td>{pl.get('fail', 0)}</td>{''.join(f'<td>{ps.get(k, 0)}</td>' for k in keys)}{''.join(f'<td>{pu.get(k, 0)}</td>' for k in ['SV-02', 'SV-03', 'SV-04', 'SV-01', 'SV-05'])}</tr>
<tr><th>이번 실행</th><td>{cl.get('fail', 0)}</td>{''.join(f'<td>{cs.get(k, 0)}</td>' for k in keys)}{''.join(f'<td>{cu.get(k, 0)}</td>' for k in ['SV-02', 'SV-03', 'SV-04', 'SV-01', 'SV-05'])}</tr>
</tbody></table>
<div class=cols><div><h3>SV 등급 이동</h3><table><tbody>{''.join(f'<tr><td>{E(k)}</td><td>{v}</td></tr>' for k, v in trs.most_common())}</tbody></table></div>
<div><h3>법률 FAIL 이동</h3><table><tbody><tr><td>이전에만</td><td>{len(lf_prev - lf_now)}</td><td class=small>{E(', '.join(sorted(lf_prev - lf_now)))}</td></tr><tr><td>이번에만</td><td>{len(lf_now - lf_prev)}</td><td class=small>{E(', '.join(sorted(lf_now - lf_prev)))}</td></tr><tr><td>둘 다</td><td>{len(lf_prev & lf_now)}</td><td class=small>{E(', '.join(sorted(lf_prev & lf_now)))}</td></tr></tbody></table></div></div>
"""


# ═══════════════════ 재현성(같은 650건 2회) ═══════════════════
rerun_html = ""
if rerunG:
    common = sorted(set(G) & set(rerunG))
    if common:
        ca, cb = Counter(conf(G[i]) for i in common), Counter(conf(rerunG[i]) for i in common)
        fa, fb = {i for i in common if conf(G[i]) == "fail"}, {i for i in common if conf(rerunG[i]) == "fail"}
        sa, sb = Counter(str(g(G[i], "validity_grade")) for i in common), Counter(str(g(rerunG[i], "validity_grade")) for i in common)
        same = sum(1 for i in common if g(G[i], "validity_grade") == g(rerunG[i], "validity_grade"))
        within1 = sum(1 for i in common if abs("ABCD".index(g(G[i], "validity_grade") or "D") - "ABCD".index(g(rerunG[i], "validity_grade") or "D")) <= 1)
        mv = Counter(f"{g(G[i], 'validity_grade')}→{g(rerunG[i], 'validity_grade')}" for i in common if g(G[i], "validity_grade") != g(rerunG[i], "validity_grade"))
        ua, ub = Counter(x for i in common for x in (g(G[i], "validity_unmet") or [])), Counter(x for i in common for x in (g(rerunG[i], "validity_unmet") or []))
        ident = sum(1 for i in common if (G[i].get("response") or "") == (rerunG[i].get("response") or ""))
        la, lb = avg([len(G[i].get("response") or "") for i in common]), avg([len(rerunG[i].get("response") or "") for i in common])
        keys = ["A", "B", "C", "D"]
        rerun_html = f"""
<h2 id=rerun>4. 재현성 — 같은 650건을 같은 시간대에 2회 실행</h2>
<p class=small>2회차 run <code>{E(a.rerun.split('/')[-1].replace('.json', ''))}</code>. 두 실행은 같은 문항·같은 환경·같은 판정기이며 시작 시각 차이는 23초다. 답변 원문이 같은 문항 {ident}건(답변은 매번 새로 생성된다). 아래 차이는 답변 생성의 흔들림과 판정의 흔들림을 합친 것이다.</p>
<table><thead><tr><th></th><th>법률 확정 FAIL</th><th>회신 대기만</th><th>SV A</th><th>SV B</th><th>SV C</th><th>SV D</th><th>SV-02</th><th>SV-03</th><th>SV-04</th><th>길이 평균</th></tr></thead><tbody>
<tr><th>1회차</th><td>{ca.get('fail', 0)}</td><td>{ca.get('review', 0)}</td>{''.join(f'<td>{sa.get(k, 0)}</td>' for k in keys)}<td>{ua.get('SV-02', 0)}</td><td>{ua.get('SV-03', 0)}</td><td>{ua.get('SV-04', 0)}</td><td>{la}</td></tr>
<tr><th>2회차</th><td>{cb.get('fail', 0)}</td><td>{cb.get('review', 0)}</td>{''.join(f'<td>{sb.get(k, 0)}</td>' for k in keys)}<td>{ub.get('SV-02', 0)}</td><td>{ub.get('SV-03', 0)}</td><td>{ub.get('SV-04', 0)}</td><td>{lb}</td></tr>
</tbody></table>
<div class=cols>
<div><h3>법률 확정 FAIL 문항 일치</h3><table><tbody><tr><td>두 번 다 FAIL</td><td>{len(fa & fb)}</td><td class=small>{E(', '.join(sorted(fa & fb)))}</td></tr><tr><td>1회차만</td><td>{len(fa - fb)}</td><td class=small>{E(', '.join(sorted(fa - fb)))}</td></tr><tr><td>2회차만</td><td>{len(fb - fa)}</td><td class=small>{E(', '.join(sorted(fb - fa)))}</td></tr></tbody></table></div>
<div><h3>SV 등급 일치</h3><table><tbody><tr><td>같은 등급</td><td>{same} ({same * 100 / len(common):.0f}%)</td></tr><tr><td>한 등급 안</td><td>{within1} ({within1 * 100 / len(common):.0f}%)</td></tr>{''.join(f'<tr><td>{E(k)}</td><td>{v}</td></tr>' for k, v in mv.most_common(8))}</tbody></table></div>
</div>
<p class=note>해석: 전체 비율(확정 FAIL 약 {ca.get('fail', 0) * 100 / len(common):.1f}% · SV A 약 {sa.get('A', 0) * 100 / len(common):.0f}%)은 두 실행에서 거의 같지만, 어느 문항이 FAIL 인지는 {len(fa & fb)}건만 겹친다. 법률 FAIL 은 특정 문항의 문제라기보다 답변마다 확률적으로 나오는 문형(질환 가능성 부여·안심 문형)의 문제다. 개선 확인은 문항별 재현이 아니라 전체 비율과 규칙별 건수로 본다.</p>
"""

# ═══════════════════ 성능 ═══════════════════
def perf_row(label, m):
    return (f"<tr><th>{E(label)}</th><td>{avg(m['ttft']) / 1000:.1f}</td><td>{med(m['ttft']) / 1000:.1f}</td><td>{p95(m['ttft']) / 1000:.1f}</td>"
            f"<td>{avg(m['tot']) / 1000:.1f}</td><td>{med(m['tot']) / 1000:.1f}</td><td>{p95(m['tot']) / 1000:.1f}</td><td>{avg(m['lens'])}</td><td>{len(m['resp_fail'])}</td><td>{len(m['retried'])}</td></tr>")


def run_time(run):
    ra = run.get("run_at") or ""
    try:
        t = datetime.fromisoformat(ra.replace("Z", "+00:00")).astimezone(KST)
        return t.strftime("%Y-%m-%d %H:%M KST")
    except Exception:
        return ra


# ═══════════════════ 전체 표 ═══════════════════
rowsP = []
for i in Pids:
    r = P[i]
    rowsP.append(f"<tr><td>{E(i)}</td><td>{E(qtype(i))}</td><td>{E(g(r, 'uv_intent'))}</td><td class={'bad' if g(r, 'legal_verdict') == 'fail' else ''}>{E(g(r, 'legal_verdict'))}{(' ' + E(','.join(g(r, 'legal_hits') or []))) if g(r, 'legal_verdict') == 'fail' else ''}</td>"
                 f"<td class=g{E(g(r, 'validity_grade'))}>{E(g(r, 'validity_grade') or '—')}</td><td class=g{E(g(r, 'uv_grade'))}>{E(g(r, 'uv_grade') or '—')}</td>"
                 f"<td class=small>{E(', '.join((g(r, 'validity_unmet') or []) + (g(r, 'uv_unmet') or [])))}</td><td>{len(r.get('response') or '')}</td><td>{round((r.get('responseTime') or 0) / 1000, 1)}</td></tr>")
rowsG = []
for i in Gids:
    r = G[i]
    rowsG.append(f"<tr><td>{E(i)}</td><td>{E(cat(i))}</td><td class=small>{E(sub(i))}</td><td>{E(branch(i))}</td><td class={'bad' if g(r, 'legal_verdict') == 'fail' else ''}>{E(g(r, 'legal_verdict'))}{(' ' + E(','.join(g(r, 'legal_hits') or []))) if g(r, 'legal_verdict') == 'fail' else ''}</td>"
                 f"<td class=g{E(g(r, 'validity_grade'))}>{E(g(r, 'validity_grade') or '—')}</td><td class=small>{E(', '.join(g(r, 'validity_unmet') or []))}</td><td>{E(r.get('status'))}</td><td>{len(r.get('response') or '')}</td><td>{round((r.get('firstTokenMs') or 0) / 1000, 1)}</td><td>{round((r.get('responseTime') or 0) / 1000, 1)}</td></tr>")

css = """
body{font-family:'Malgun Gothic',Segoe UI,sans-serif;max-width:1200px;margin:24px auto;padding:0 16px;color:#1b1f23;line-height:1.55}
h1{font-size:22px;border-bottom:2px solid #1b1f23;padding-bottom:6px}h2{font-size:17px;margin-top:34px;border-left:4px solid #2563eb;padding-left:8px}h3{font-size:14px;margin:12px 0 6px}
table{border-collapse:collapse;margin:8px 0 12px;font-size:13px}th,td{border:1px solid #d0d7de;padding:4px 8px;text-align:left;vertical-align:top}th{background:#f6f8fa}
.kpi{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}.kpi div{border:1px solid #d0d7de;border-radius:8px;padding:10px 14px;min-width:150px}.kpi b{display:block;font-size:22px}.kpi span{font-size:12px;color:#57606a}
.note{background:#fff8e1;border-left:4px solid #f59e0b;padding:8px 12px;font-size:13px}.small{font-size:12px;color:#57606a}.bad{color:#b91c1c;font-weight:600}
.cols{display:flex;gap:24px;flex-wrap:wrap}.cols>div{flex:1;min-width:260px}
.gA{background:#dcfce7}.gB{background:#fef9c3}.gC{background:#fed7aa}.gD{background:#fecaca}
details summary{cursor:pointer;font-weight:600;margin:8px 0}.all td{white-space:nowrap}.all td.small{white-space:normal;max-width:260px}
nav a{margin-right:12px;font-size:13px}
"""

stampP = ", ".join(f"{k} {v}건" for k, v in mP["stamp"].most_common())
stampG = ", ".join(f"{k} {v}건" for k, v in mG["stamp"].most_common())
judgeP = ", ".join(f"{k} {v}건" for k, v in mP["judge"].most_common())
judgeG = ", ".join(f"{k} {v}건" for k, v in mG["judge"].most_common())
emer_ids = [i for i in Gids if cat(i) == "emergency"]
emer_lf = [i for i in emer_ids if g(G[i], "legal_verdict") == "fail"]
sv_cd_emer = [i for i in emer_ids if g(G[i], "validity_grade") in ("C", "D")]
by_branch = by_group_gen(branch)

doc = f"""<!doctype html><html lang=ko><head><meta charset=utf-8><title>Dev PHR 350건 + 일반 650건 테스트 결과 — {E(a.date)}</title><style>{css}</style></head><body>
<h1>Dev 환경 테스트 결과 — PHR 350건 + 일반 650건 ({E(a.date)})</h1>
<p class=small>Dev 환경(dev-skix.phnyx.ai) · 호스트 batch-runner Job, 5건 동시 호출 · 판정기 온톨로지 {E(mP['onto'])} · 법률 규칙 {E(mP['legal_ver'])} · 판정 모델 1차 gpt-6-luna(추론 없음) / 법률 FAIL 2차 gpt-6-sol(추론 low)<br>
PHR run <code>{E(runP.get('id'))}</code> ({E(run_time(runP))}) · 프롬프트 스탬프 {E(stampP)} · 판정 모델 {E(judgeP)}<br>
일반 run <code>{E(runG.get('id'))}</code> ({E(run_time(runG))}) · 프롬프트 스탬프 {E(stampG)} · 판정 모델 {E(judgeG)}</p>
<nav><a href=#sum>종합</a><a href=#phr>PHR 350</a><a href=#gen>일반 650</a>{"<a href=#rerun>재현성</a>" if rerunG else ""}<a href=#perf>응답 성능</a><a href=#todo>개선 우선순위</a><a href=#allp>전체 표</a></nav>
<p class=note>답변 원문과 개인건강기록 값은 싣지 않는다(길이·시간 통계만). 답변 원문은 플랫폼 이력에서 run id 로 본다. 일반 650건은 PHR 없는 일반 시나리오 풀 {E(sample.get('pool', '1,124'))}건에서 카테고리 비례로 뽑은 표본이다({E(sample.get('desc', ''))}). 판정 폴백(claim_fallback) PHR {len(mP['fallback'])}건 · 일반 {len(mG['fallback'])}건.</p>

<h2 id=sum>1. 종합</h2>
<h3>PHR 350건 (법률 게이트 LG + 기록 활용 PV + 답변 유용성 UV)</h3>
<div class=kpi>
<div><b>{nP}</b><span>문항 수 (응답 오류 {len(mP['resp_fail'])}건 · PV 미채점 {len(skippedP)}건)</span></div>
<div><b>{len(confP)} <span style="font-size:14px">(+{len(revP)})</span></b><span>법률 게이트 FAIL 확정 위반 (+회신 대기 규칙만)</span></div>
<div><b>{pct(pv.get('A', 0), nP)}</b><span>PV(기록 활용 유효성) A</span></div>
<div><b>{pct(uv.get('A', 0), nP)}</b><span>UV(답변 유용성) A</span></div>
<div><b>{pct(len(all_a), nP)}</b><span>법률 pass · PV A · UV A 모두</span></div>
<div><b>{pct(len(pass_bar), nP)}</b><span>법률 pass · PV A/B · UV A/B (제안 합격선)</span></div>
<div><b>{avg(mP['lens'])}자</b><span>답변 길이 평균</span></div>
<div><b>{avg(mP['ttft']) / 1000:.1f}s / {avg(mP['tot']) / 1000:.1f}s</b><span>첫 토큰 / 전체 응답 평균</span></div>
</div>
<h3>일반 650건 (법률 게이트 LG + 증상 대응 SV; PV·UV 는 채점하지 않음)</h3>
<div class=kpi>
<div><b>{nG}</b><span>문항 수 (응답 오류 {len(mG['resp_fail'])}건 · SV 미채점 {nG - len(sv_scored)}건)</span></div>
<div><b>{len(confG)} <span style="font-size:14px">(+{len(revG)})</span></b><span>법률 게이트 FAIL 확정 위반 (+회신 대기 규칙만)</span></div>
<div><b>{pct(sv.get('A', 0), nG)}</b><span>SV(증상 대응) A</span></div>
<div><b>{pct(sv.get('C', 0) + sv.get('D', 0), nG)}</b><span>SV C·D</span></div>
<div><b>{pct(len(good_g), nG)}</b><span>법률 pass · SV A/B</span></div>
<div><b>{pct(len(sv_cd_emer), len(emer_ids))}</b><span>응급 카테고리 SV C·D (응급 {len(emer_ids)}건 중)</span></div>
<div><b>{avg(mG['lens'])}자</b><span>답변 길이 평균</span></div>
<div><b>{avg(mG['ttft']) / 1000:.1f}s / {avg(mG['tot']) / 1000:.1f}s</b><span>첫 토큰 / 전체 응답 평균</span></div>
</div>
<table><thead><tr><th>축</th><th>A</th><th>B</th><th>C</th><th>D</th><th>미채점</th></tr></thead><tbody>
{dist_row('PHR · PV 기록 활용 유효성', pv, ['A', 'B', 'C', 'D', 'None'])}
{dist_row('PHR · UV 답변 유용성', uv, ['A', 'B', 'C', 'D', 'None'])}
{dist_row('일반 · SV 증상 대응', sv, ['A', 'B', 'C', 'D', 'None'])}
</tbody></table>

<h2 id=phr>2. PHR 350건</h2>
<p class=small>PV 미채점 {len(skippedP)}건은 개인건강기록이 비어 있는 케이스(기록 0건)로 기록 활용을 채점하지 않는다. PV D {pv.get('D', 0)}건 중 {sum(1 for i in Pids if 'PV-01' in (g(P[i], 'validity_unmet') or []))}건은 PV-01(기록과 다른 값), {sum(1 for i in Pids if 'PV-02' in (g(P[i], 'validity_unmet') or []))}건은 PV-02(기록에 없는 날짜·항목)로 등급 상한 D 가 적용된 것이다.</p>
<h3>2-1. 항목별 미충족</h3>
<div class=cols>
<div><h3>PV — 기록 활용 유효성</h3>{unmet_table(pv_unmet, max(1, len(scoredP)))}</div>
<div><h3>UV — 답변 유용성</h3>{unmet_table(uv_unmet, max(1, len(uv_scoredP)))}</div>
</div>
<p class=small>비율 분모는 PV 는 PV 채점 {len(scoredP)}건, UV 는 UV 채점 {len(uv_scoredP)}건. PV-08·PV-11 은 판정기 미구현(항상 na). PV-03 은 인용 값과 같은 문장 안에 참고범위 표지가 있어야 충족된다.</p>
<h3>2-2. 법률 게이트 FAIL {len(legal_failP)}건 — 확정 위반 {len(confP)}건 · 회신 대기 규칙만 {len(revP)}건</h3>
<p class=small>"회신 대기 규칙만"은 확정 규칙 적중 없이 법무 회신 대기 규칙(LG-05 진료과 안내, LG-11 개인 위험도 평가 등)만 적중해 게이트가 fail 로 표시된 건이다. 법무 회신 전까지는 확정 위반과 구분해 본다.</p>
{legal_table(P, legal_failP, ('유형 / 의도', lambda i: f"{qtype(i)} / {g(P[i], 'uv_intent')}"))}
<p class=small>LG 적중 전체(FAIL 아닌 검토 적중 포함): {E(', '.join(f'{k} {v}건' for k, v in lg_hitsP.most_common()) or '없음')}. 검토 대상(review) 적중: {E(', '.join(f'{k} {v}건' for k, v in Counter(h for i in Pids for h in (g(P[i], 'legal_review_hits') or [])).most_common()) or '없음')}.</p>
<h3>2-3. PV-01 미충족(기록과 다른 값 인용) {len(pv01)}건</h3>
<p class=small>사실 대조 수치만 적는다(cited=인용 값 수, matched=기록과 일치, fabricated=기록에 없는 값).</p>
<table><thead><tr><th>문항</th><th>유형</th><th>의도</th><th>cited</th><th>matched</th><th>fabricated</th><th>판정 사유</th></tr></thead><tbody>
{''.join(f"<tr><td>{E(i)}</td><td>{E(q)}</td><td>{E(it)}</td><td>{E(c)}</td><td>{E(m)}</td><td>{E(f)}</td><td class=small>{E(d)}</td></tr>" for i, q, it, c, m, f, d in pv01)}
</tbody></table>
<h3>2-4. 문항 유형(T#)별</h3>{group_table_phr(by_group_phr(qtype), '유형')}
<h3>2-5. 질문 의도(UV intent)별</h3>{group_table_phr(by_group_phr(lambda i: g(P[i], 'uv_intent') or '?'), '의도')}
{prevP_html}

<h2 id=gen>3. 일반 650건</h2>
<p class=small>판정 모드: {E(', '.join(f'{k} {v}건' for k, v in modeG.most_common()))}. SV 는 증상 상담 문항에서 기대 동작(분기)·위험 신호·필수 문진·복용약 교차확인·조건부 행동 기준을 본다. 응급 분기에서는 SV-03·SV-04 를 요구하지 않는다.</p>
<h3>3-1. 법률 게이트 FAIL {len(legal_failG)}건 — 확정 위반 {len(confG)}건 · 회신 대기 규칙만 {len(revG)}건</h3>
<p class=small>확정 위반 규칙별: {E(', '.join(f'{k} {v}건' for k, v in Counter(h for i in confG for h in (g(G[i], 'legal_hits') or [])).most_common()) or '없음')}. 회신 대기 규칙만 적중: {E(', '.join(f'{k} {v}건' for k, v in Counter(h for i in revG for h in (g(G[i], 'legal_review_hits') or [])).most_common()) or '없음')}. 응급(emergency) {len(emer_ids)}건 중 FAIL {len(emer_lf)}건(확정 {sum(1 for i in emer_lf if conf(G[i]) == 'fail')}건). 2차 판정(gpt-6-sol)으로 넘어간 {mG['judge'].get('gpt-6-sol', 0)}건 중 FAIL 로 남은 건 {len(legal_failG)}건.</p>
{legal_table(G, legal_failG, ('카테고리 / 서브', lambda i: f"{cat(i)} / {sub(i)}"))}
<h3>3-2. SV 항목별 미충족</h3>
{unmet_table(sv_unmet, max(1, len(sv_scored)))}
<p class=small>비율 분모는 SV 채점 {len(sv_scored)}건.</p>
<h3>3-3. 카테고리별</h3>{group_table_gen(by_group_gen(catg), '카테고리')}
<p class=small>분과 10종 = 피부·머리뇌신경계·전신피로발열·소화기·순환기·호흡기·감각기관·근골격계·비뇨생식기·정신건강(수동 작성 문항).</p>
<h3>3-4. 기대 분기(응급·당일·외래·생활관리)별</h3>{group_table_gen(by_branch, '분기')}
{prevG_html}

{rerun_html}
<h2 id=perf>{"5" if rerun_html else "4"}. 응답 성능</h2>
<table><thead><tr><th></th><th>첫 토큰 평균(s)</th><th>중앙값</th><th>p95</th><th>전체 응답 평균(s)</th><th>중앙값</th><th>p95</th><th>답변 길이 평균(자)</th><th>응답 오류</th><th>재시도 건</th></tr></thead><tbody>
{perf_row('PHR 350', mP)}
{perf_row('일반 650', mG)}
</tbody></table>
<p class=small>5건 동시 호출 기준.{(' ' + E(a.perf_note)) if a.perf_note else ''} 응답 오류는 HTTP 200 이 아니거나 답변이 비었거나 끊긴 건. 재시도 건은 첫 호출이 실패해 두 번째 이상 호출에서 답변을 받은 건(최종 답변은 정상).{(' PHR 오류 문항: ' + E(', '.join(mP['resp_fail']))) if mP['resp_fail'] else ''}{(' 일반 오류 문항: ' + E(', '.join(mG['resp_fail']))) if mG['resp_fail'] else ''}</p>

<h2 id=todo>{"6" if rerun_html else "5"}. 개선 우선순위 (건수 기준)</h2>
<h3>PHR</h3>
<ol>
<li><b>UV-02 {uv_unmet.get('UV-02', 0)}건 · UV-04 {uv_unmet.get('UV-04', 0)}건</b> — {E(title_of('UV-02'))} / {E(title_of('UV-04'))}. 질문이 묻는 항목에 대한 직접 판단과 그 의미를 앞쪽 2문장 안에.</li>
<li><b>PV-03 {pv_unmet.get('PV-03', 0)}건</b> — 참고범위를 값과 같은 문장에 괄호로 병기.</li>
<li><b>UV-01 {uv_unmet.get('UV-01', 0)}건 · UV-06 {uv_unmet.get('UV-06', 0)}건</b> — {E(title_of('UV-01'))} / {E(title_of('UV-06'))}.</li>
<li><b>PV-01 {pv_unmet.get('PV-01', 0)}건 · PV-02 {pv_unmet.get('PV-02', 0)}건</b> — 기록값은 그대로 옮기고 계산값은 "계산"이라고 밝힌다. 등급 상한 D.</li>
<li><b>법률 확정 위반 {len(confP)}건</b> — {E(', '.join(sorted(set(h for i in confP for h in (g(P[i], 'legal_hits') or [])))) or '없음')}. 회신 대기 규칙만 적중 {len(revP)}건은 법무 회신 뒤 판단.</li>
</ol>
<h3>일반</h3>
<ol>
<li><b>법률 확정 위반 {len(confG)}건({len(confG) * 100 / nG:.1f}%)</b> — {E(', '.join(f'{k} {v}건' for k, v in Counter(h for i in confG for h in (g(G[i], 'legal_hits') or [])).most_common()) or '없음')}. 질환 가능성 부여(LG-02)와 안심·경시 문형(LG-08: "집에서 쉬면", "병원 안 가도")이 대부분이며 진단·응급 카테고리에 몰린다. 2차 판정(gpt-6-sol)까지 거친 건이므로 답변 원문을 직접 검토해 거짓 FAIL 을 가른 뒤 프롬프트 문형 규칙으로 막는다. 회신 대기 규칙만 적중 {len(revG)}건(LG-05 진료과 안내·LG-11 개인 위험도)은 법무 회신 뒤 판단.</li>
<li><b>SV-02 {sv_unmet.get('SV-02', 0)}건</b> — {E(title_of('SV-02'))}. 증상군별 위험 신호를 한 가지 이상 묻거나 확인.</li>
<li><b>SV-03 {sv_unmet.get('SV-03', 0)}건 · SV-04 {sv_unmet.get('SV-04', 0)}건</b> — {E(title_of('SV-03'))} / {E(title_of('SV-04'))}. 비응급 분기에서 되묻기 1~2문항.</li>
<li><b>SV-05 {sv_unmet.get('SV-05', 0)}건 · SV-01 {sv_unmet.get('SV-01', 0)}건</b> — {E(title_of('SV-05'))} / {E(title_of('SV-01'))}.</li>
</ol>

<h2 id=allp>{"7" if rerun_html else "6"}. 전체 표</h2>
<details><summary>PHR {nP}건 — 문항 · 유형 · 의도 · 법률 · PV · UV · 미충족 · 길이 · 응답(s)</summary>
<table class=all><thead><tr><th>문항</th><th>유형</th><th>의도</th><th>법률</th><th>PV</th><th>UV</th><th>미충족</th><th>길이</th><th>응답 s</th></tr></thead><tbody>{''.join(rowsP)}</tbody></table>
</details>
<details><summary>일반 {nG}건 — 문항 · 카테고리 · 서브 · 분기 · 법률 · SV · 미충족 · 상태 · 길이 · 첫 토큰(s) · 응답(s)</summary>
<table class=all><thead><tr><th>문항</th><th>카테고리</th><th>서브</th><th>분기</th><th>법률</th><th>SV</th><th>미충족</th><th>상태</th><th>길이</th><th>첫 토큰 s</th><th>응답 s</th></tr></thead><tbody>{''.join(rowsG)}</tbody></table>
</details>
<p class=small>생성 스크립트: reports/v3_runs/dev_phr350_gen650_report_20261016.py · 입력 덤프: dumps/{E(runP.get('id'))}.json, dumps/{E(runG.get('id'))}.json · 일반 표본: scripts/samples/general650_seed20261016.json</p>
</body></html>"""

open(a.out, "w", encoding="utf-8").write(doc)
print(a.out, len(doc))
print("PHR n", nP, "legal_fail", legalP.get("fail", 0), "PV", dict(pv), "UV", dict(uv), "allA", len(all_a), "pass_bar", len(pass_bar), "fallback", len(mP["fallback"]), "resp_fail", len(mP["resp_fail"]))
print("GEN n", nG, "legal_fail", legalG.get("fail", 0), "SV", dict(sv), "good", len(good_g), "fallback", len(mG["fallback"]), "resp_fail", len(mG["resp_fail"]), "sv_unmet", dict(sv_unmet))
