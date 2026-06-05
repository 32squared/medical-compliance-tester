"""1100건 배치의 컴플라이언스 위반 중심 단일 HTML 보고서 생성.

사용:
  python scripts/make_run_1100_compliance_report.py \
    data/run-1e71ae-compliance.json reports/scenario_1100_compliance.html
"""
import html as html_mod
import json
import os
import sys

CSS = """
:root {
  --primary: #0ea5e9;
  --accent: #6366f1;
  --green: #22c55e;
  --yellow: #eab308;
  --orange: #f97316;
  --red: #ef4444;
  --crimson: #dc2626;
  --purple: #a855f7;
  --bg: #ffffff;
  --surface: #f8fafc;
  --surface2: #f1f5f9;
  --border: #e2e8f0;
  --text: #0f172a;
  --text-dim: #64748b;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans KR', sans-serif; background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.7; }
.page { max-width: 1024px; margin: 0 auto; padding: 32px 28px 60px; }
.report-header { border-bottom: 4px solid var(--crimson); padding-bottom: 18px; margin-bottom: 28px; }
.report-title { font-size: 30px; font-weight: 800; color: var(--text); margin-bottom: 6px; }
.report-subtitle { font-size: 14px; color: var(--text-dim); }
.report-meta { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 12px; font-size: 12px; color: var(--text-dim); }
.report-meta span { padding: 3px 9px; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; }
.report-meta b { color: var(--text); }
h2 { font-size: 20px; font-weight: 700; margin: 32px 0 14px; padding-bottom: 8px; border-bottom: 2px solid var(--border); }
h3 { font-size: 15px; font-weight: 700; margin: 18px 0 8px; color: var(--accent); }
p { margin-bottom: 10px; }
ul, ol { margin: 8px 0 12px 24px; }
li { margin-bottom: 4px; }
code { background: var(--surface2); padding: 1px 6px; border-radius: 3px; font-size: 12px; color: var(--accent); font-family: 'Menlo', 'Consolas', monospace; }
.tldr { background: linear-gradient(135deg, #fef2f2 0%, #fce7f3 100%); border: 1px solid var(--red); border-left: 6px solid var(--crimson); border-radius: 8px; padding: 16px 22px; margin: 18px 0 28px; }
.tldr-title { font-size: 13px; font-weight: 700; color: var(--crimson); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.tldr-content { font-size: 14.5px; color: var(--text); line-height: 1.75; }
.tldr-content b { color: var(--crimson); }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 12px; margin: 14px 0 20px; }
.kpi-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; text-align: center; }
.kpi-value { font-size: 28px; font-weight: 800; line-height: 1.1; }
.kpi-label { font-size: 11px; color: var(--text-dim); margin-top: 6px; text-transform: uppercase; letter-spacing: 0.3px; }
.kpi-card.green .kpi-value { color: var(--green); }
.kpi-card.yellow .kpi-value { color: var(--yellow); }
.kpi-card.red .kpi-value { color: var(--red); }
.kpi-card.crimson .kpi-value { color: var(--crimson); }
.kpi-card.orange .kpi-value { color: var(--orange); }
.kpi-card.blue .kpi-value { color: var(--primary); }
.kpi-card.purple .kpi-value { color: var(--purple); }
table { width: 100%; border-collapse: collapse; margin: 10px 0 18px; font-size: 13px; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: var(--surface); font-weight: 700; font-size: 11.5px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.3px; }
tr:hover td { background: var(--surface); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.center { text-align: center; }
.bar-row { display: flex; align-items: center; gap: 10px; margin: 5px 0; font-size: 12.5px; }
.bar-label { min-width: 200px; text-align: right; color: var(--text-dim); }
.bar-track { flex: 1; height: 22px; background: var(--surface2); border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; display: flex; align-items: center; padding-left: 8px; color: white; font-weight: 700; font-size: 11px; }
.bar-value { min-width: 70px; font-weight: 700; font-size: 12.5px; }
.callout { padding: 12px 16px; border-radius: 6px; margin: 12px 0; border-left: 4px solid; }
.callout-warn { background: #fef3c7; border-color: var(--yellow); color: #78350f; }
.callout-red { background: #fee2e2; border-color: var(--red); color: #7f1d1d; }
.callout-info { background: #dbeafe; border-color: var(--primary); color: #1e3a8a; }
.callout-green { background: #d1fae5; border-color: var(--green); color: #064e3b; }
.sev-badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-weight: 700; font-size: 11px; color: white; }
.sev-CRITICAL { background: var(--crimson); }
.sev-HIGH { background: var(--orange); }
.sev-MEDIUM { background: var(--yellow); color: #78350f; }
.sev-LOW { background: var(--green); }
.sev-NONE, .sev-UNKNOWN { background: var(--text-dim); }
.law-tag { display: inline-block; padding: 2px 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 3px; font-size: 11px; color: var(--text-dim); margin-right: 4px; }
.case-card { background: var(--surface); border-left: 4px solid var(--crimson); border-radius: 4px; padding: 12px 16px; margin: 10px 0; }
.case-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.case-id { font-weight: 700; font-size: 14px; }
.case-meta { font-size: 11px; color: var(--text-dim); }
.case-desc { font-size: 12.5px; line-height: 1.65; color: var(--text); margin-top: 6px; padding: 8px 10px; background: var(--bg); border-radius: 3px; border: 1px solid var(--border); }
@media print {
  body { font-size: 11.5pt; }
  .page { padding: 0; max-width: none; }
  h2 { page-break-after: avoid; }
  .kpi-card, .callout, table, .case-card { page-break-inside: avoid; }
  .tldr { background: #fef2f2 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .bar-fill, .kpi-value, .sev-badge { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
.print-hint { position: fixed; top: 12px; right: 12px; padding: 6px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; font-size: 11px; color: var(--text-dim); cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.print-hint:hover { background: var(--surface2); }
@media print { .print-hint { display: none; } }
"""

LAW_COLOR = {
    '의료법 제27조 (무면허 의료행위)': '#dc2626',
    '의료법 27조 + 응급의료법': '#ea580c',
    '응급의료에 관한 법률': '#f97316',
    '의료법 제56조 (과대광고)': '#7c3aed',
    '의료법 27조 + 56조': '#9333ea',
    '내부 평가/준수 기준': '#0ea5e9',
    '미분류': '#94a3b8',
}


def sev_color(sev):
    return {'CRITICAL': '#dc2626', 'HIGH': '#f97316', 'MEDIUM': '#eab308', 'LOW': '#22c55e'}.get(sev, '#94a3b8')


def render(data):
    m = data['meta']
    o = data['overview']

    parts = []
    p = parts.append

    p(f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>시나리오 1,100건 컴플라이언스 위반 분석</title><style>{CSS}</style></head><body>
<div class="print-hint" onclick="window.print()">🖨 인쇄 / PDF 저장</div>
<div class="page">''')

    run_at = m.get('run_at') or ''
    p(f'''<header class="report-header">
  <div class="report-title">⚖️ 컴플라이언스 위반 분석 보고서</div>
  <div class="report-subtitle">SKIX 의료 응답 1,100건 — 의료법·응급의료법 위반 패턴 식별 및 우선순위 도출</div>
  <div class="report-meta">
    <span><b>run_id</b>: {m["id"]}</span>
    <span><b>시점</b>: {run_at[:19].replace("T"," ")}</span>
    <span><b>환경</b>: {m.get("env","").upper()}</span>
    <span><b>대상</b>: 일반 시나리오 1,100건</span>
    <span><b>분석 축</b>: 법 조항 · 심각도 · 카테고리 · 빈도×가중치</span>
  </div>
</header>''')

    # ───────────────────────────────────────
    # TL;DR
    # ───────────────────────────────────────
    crit_n = data['by_severity'].get('CRITICAL', 0)
    high_n = data['by_severity'].get('HIGH', 0)
    law27_n = data['by_law'].get('의료법 제27조 (무면허 의료행위)', 0)
    law27_combo_n = data['by_law'].get('의료법 27조 + 응급의료법', 0)
    emergency_n = data['by_law'].get('응급의료에 관한 법률', 0)
    total_27_related = law27_n + law27_combo_n + data['by_law'].get('의료법 27조 + 56조', 0)
    total_emergency = law27_combo_n + emergency_n
    total_v = data['total_violation_items']
    crit_cases = data['critical_case_count']
    multi_n = data['multi_violation_count']
    top_priority = data['priority_violations'][0] if data['priority_violations'] else None

    p(f'''<div class="tldr">
  <div class="tldr-title">⚠️ TL;DR — 컴플라이언스 핵심 위험</div>
  <div class="tldr-content">
    총 1,100건 중 <b>{o["violated_scenarios"]}건(50.7%)</b>에서 위반 발견, 위반 항목 누계 <b>{total_v:,}건</b>.
    <b>CRITICAL 등급 위반 {crit_n}건</b>(시나리오 {crit_cases}건에서 발생) — 즉시 조치 필요.
    의료법 제27조(무면허 의료행위) 관련 위반이 <b>{total_27_related}건({total_27_related/total_v*100:.1f}%)</b>로 압도적, 응급의료법 관련도 <b>{total_emergency}건</b>.
    가중치 기준 최우선 개선 대상은 <b>"{top_priority["type"]}"</b>({top_priority["count"]}회, {top_priority["primary_law"]}).
    4건 이상 다중 위반 시나리오 <b>{multi_n}건</b>은 응답 전면 개정 대상.
  </div>
</div>''')

    # ───────────────────────────────────────
    # 1. 위반 발생률 KPI
    # ───────────────────────────────────────
    p('<h2>1. 위반 발생률 (Compliance Risk Overview)</h2>')
    p(f'''<div class="kpi-grid">
  <div class="kpi-card crimson"><div class="kpi-value">{o["violated_rate"]:.1f}%</div><div class="kpi-label">위반 보유 시나리오</div></div>
  <div class="kpi-card green"><div class="kpi-value">{o["clean_rate"]:.1f}%</div><div class="kpi-label">위반 없음 (Clean)</div></div>
  <div class="kpi-card crimson"><div class="kpi-value">{crit_n:,}</div><div class="kpi-label">CRITICAL 위반</div></div>
  <div class="kpi-card orange"><div class="kpi-value">{high_n:,}</div><div class="kpi-label">HIGH 위반</div></div>
  <div class="kpi-card red"><div class="kpi-value">{crit_cases}</div><div class="kpi-label">CRITICAL 보유 시나리오</div></div>
  <div class="kpi-card orange"><div class="kpi-value">{multi_n}</div><div class="kpi-label">4건+ 다중 위반</div></div>
  <div class="kpi-card blue"><div class="kpi-value">{total_v:,}</div><div class="kpi-label">총 위반 항목</div></div>
  <div class="kpi-card purple"><div class="kpi-value">{total_v/o["violated_scenarios"]:.1f}</div><div class="kpi-label">평균 위반/시나리오 (위반보유 기준)</div></div>
</div>''')

    # 시나리오당 위반 분포
    p('<h3>1.1 시나리오당 위반 개수 분포</h3>')
    vd = data['viol_distribution']
    max_v = max(vd.values()) if vd else 1
    for n_viol in sorted(vd.keys(), key=int):
        n = vd[n_viol]
        if n == 0: continue
        w = n / max_v * 100
        c = '#22c55e' if int(n_viol) == 0 else ('#eab308' if int(n_viol) <= 1 else ('#f97316' if int(n_viol) <= 3 else '#dc2626'))
        label = f'{n_viol}개 위반' if int(n_viol) > 0 else '위반 없음'
        p(f'''<div class="bar-row">
  <div class="bar-label">{label}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{w:.1f}%;background:{c}">{n}</div></div>
  <div class="bar-value">{n/o["total_scenarios"]*100:.1f}%</div>
</div>''')

    # ───────────────────────────────────────
    # 2. 법 조항별 위반
    # ───────────────────────────────────────
    p('<h2>2. 법 조항별 위반 분포</h2>')
    p('<table><thead><tr><th>법 조항</th><th class="num">위반</th><th class="num">비중</th><th>분포 시각화</th></tr></thead><tbody>')
    max_law = max(data['by_law'].values()) if data['by_law'] else 1
    for law, n in data['by_law'].items():
        if n == 0: continue
        pct = n / total_v * 100
        w = n / max_law * 100
        c = LAW_COLOR.get(law, '#94a3b8')
        p(f'''<tr>
  <td><b>{html_mod.escape(law)}</b></td>
  <td class="num"><b>{n:,}</b></td>
  <td class="num">{pct:.1f}%</td>
  <td><div class="bar-track" style="margin:0"><div class="bar-fill" style="width:{w:.1f}%;background:{c}">{n}</div></div></td>
</tr>''')
    p('</tbody></table>')

    p(f'''<div class="callout callout-red">
  <b>핵심</b>: 의료법 제27조(무면허 의료행위) 관련 위반이 단독 또는 복합으로 <b>{total_27_related}회({total_27_related/total_v*100:.1f}%)</b>. 즉, 위반의 대부분은 진단·처방·치료·검사를 의료진처럼 지시하는 표현 때문. 응급의료법 관련도 {total_emergency}회로 응급 안내 미흡/단정 분류가 두 번째 큰 위험.
</div>''')

    # ───────────────────────────────────────
    # 3. 심각도(Severity) 분포
    # ───────────────────────────────────────
    p('<h2>3. 심각도 분포</h2>')
    p('<table><thead><tr><th>심각도</th><th class="num">위반</th><th class="num">비중</th><th>시각화</th></tr></thead><tbody>')
    sev_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN']
    max_sev = max(data['by_severity'].values()) if data['by_severity'] else 1
    for sev in sev_order:
        n = data['by_severity'].get(sev, 0)
        if n == 0: continue
        pct = n / total_v * 100
        w = n / max_sev * 100
        c = sev_color(sev)
        p(f'''<tr>
  <td><span class="sev-badge sev-{sev}">{sev}</span></td>
  <td class="num"><b>{n:,}</b></td>
  <td class="num">{pct:.1f}%</td>
  <td><div class="bar-track" style="margin:0"><div class="bar-fill" style="width:{w:.1f}%;background:{c}">{n}</div></div></td>
</tr>''')
    p('</tbody></table>')

    # 법 조항 × severity 매트릭스
    p('<h3>3.1 법 조항 × 심각도 매트릭스</h3>')
    p('<table><thead><tr><th>법 조항</th>')
    for sev in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        p(f'<th class="num"><span class="sev-badge sev-{sev}">{sev}</span></th>')
    p('<th class="num">합계</th></tr></thead><tbody>')
    for law, _ in list(data['by_law'].items())[:6]:
        ls = data['law_severity_matrix'].get(law, {})
        row_total = sum(ls.values())
        p(f'<tr><td><b>{html_mod.escape(law)}</b></td>')
        for sev in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            n = ls.get(sev, 0)
            if n > 0:
                pct = n / row_total * 100 if row_total else 0
                p(f'<td class="num" style="background:{sev_color(sev)}22"><b>{n}</b><br><span style="font-size:10px;color:var(--text-dim)">{pct:.0f}%</span></td>')
            else:
                p('<td class="num" style="color:var(--text-dim)">—</td>')
        p(f'<td class="num"><b>{row_total}</b></td></tr>')
    p('</tbody></table>')

    p(f'''<div class="callout callout-warn">
  <b>해석</b>: 의료법 제27조 단독 위반에서 CRITICAL이 <b>241회</b>로 압도적 — 검사·처방·치료 지시 표현이 자주 강하게 나타나는 의미. 응급의료법 복합 위반은 CRITICAL이 44회로 응급 상황 분류·지시가 실제 환자 안전에 직접 영향.
</div>''')

    # ───────────────────────────────────────
    # 4. 우선순위 가중 위반 유형
    # ───────────────────────────────────────
    p('<h2>4. 위반 유형 우선순위 (빈도 × 심각도 가중치)</h2>')
    p('<p style="color:var(--text-dim);font-size:12.5px">가중치 = CRITICAL×3 + HIGH×2 + MEDIUM×1 + LOW×0.5. 동일 빈도라도 CRITICAL 비율이 높으면 우선순위 상승.</p>')
    p('<table><thead><tr><th>#</th><th>위반 유형</th><th>주 법 조항</th><th class="num">빈도</th><th class="center">심각도 분포</th><th class="num">가중치</th></tr></thead><tbody>')
    for i, pv in enumerate(data['priority_violations'][:12], 1):
        sev_dist = pv['severity']
        sev_pills = ''
        for sev in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            n = sev_dist.get(sev, 0)
            if n > 0:
                sev_pills += f'<span class="sev-badge sev-{sev}" style="margin:1px">{n}</span>'
        c = LAW_COLOR.get(pv['primary_law'], '#94a3b8')
        p(f'''<tr>
  <td class="center"><b>{i}</b></td>
  <td><b>{html_mod.escape(pv["type"])}</b></td>
  <td><span class="law-tag" style="border-color:{c};color:{c}">{html_mod.escape(pv["primary_law"])}</span></td>
  <td class="num"><b>{pv["count"]}</b></td>
  <td class="center">{sev_pills}</td>
  <td class="num"><b>{pv["weighted_score"]:.0f}</b></td>
</tr>''')
    p('</tbody></table>')

    # ───────────────────────────────────────
    # 5. CRITICAL 위반 사례 (실제 description)
    # ───────────────────────────────────────
    p('<h2>5. CRITICAL 위반 실제 사례 (Top 8)</h2>')
    p('<p style="color:var(--text-dim);font-size:12.5px">점수가 가장 낮은 CRITICAL 위반 시나리오. <code>description</code>은 GPT 평가가 지적한 실제 문구.</p>')
    for case in data['critical_cases'][:8]:
        sub = (case.get('subcategory') or '')[:50]
        p(f'''<div class="case-card">
  <div class="case-header">
    <div>
      <span class="case-id">{case["scenarioId"]}</span>
      <span class="case-meta"> · {case["category"]} · {html_mod.escape(sub)}</span>
    </div>
    <div>
      <span class="sev-badge sev-{case["riskLevel"] if case["riskLevel"] in ["CRITICAL","HIGH","MEDIUM","LOW"] else "UNKNOWN"}">{case["riskLevel"]}</span>
      <span class="sev-badge" style="background:#94a3b8">점수 {case["finalScore"]:.0f}</span>
      <span class="sev-badge" style="background:{sev_color("CRITICAL") if case["grade"] in ["D","F"] else "#0ea5e9"}">등급 {case["grade"]}</span>
      <span class="sev-badge sev-CRITICAL">CRITICAL {case["critical_count"]}건</span>
    </div>
  </div>''')
        for v in case['critical_violations']:
            p(f'''<div style="margin-top:6px">
    <span class="law-tag" style="border-color:var(--crimson);color:var(--crimson)">{html_mod.escape(v["law"])}</span>
    <span class="law-tag">{html_mod.escape(v["type"])}</span>
    <div class="case-desc">{html_mod.escape(v["description"])}</div>
  </div>''')
        p('</div>')

    # ───────────────────────────────────────
    # 6. 다중 위반 시나리오 (4건 이상)
    # ───────────────────────────────────────
    p('<h2>6. 다중 위반 시나리오 (4건 이상 위반)</h2>')
    p(f'<p style="color:var(--text-dim);font-size:12.5px">총 {data["multi_violation_count"]}건. 응답 전면 개정 대상. Top 12 표시.</p>')
    p('<table><thead><tr><th>scenarioId</th><th>카테고리</th><th>위험도</th><th class="num">점수</th><th class="center">등급</th><th class="num">위반</th><th>심각도 분포</th><th>주요 위반 유형</th></tr></thead><tbody>')
    for mv in data['multi_violation_scenarios'][:12]:
        sev_pills = ''
        for sev in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            n = mv['severity_breakdown'].get(sev, 0)
            if n > 0:
                sev_pills += f'<span class="sev-badge sev-{sev}" style="margin:1px">{n}</span>'
        types_str = ', '.join(mv['top_types'][:3])
        risk = mv['riskLevel'] if mv['riskLevel'] in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] else 'UNKNOWN'
        p(f'''<tr>
  <td><code>{mv["scenarioId"]}</code></td>
  <td>{mv["category"]}</td>
  <td><span class="sev-badge sev-{risk}">{mv["riskLevel"]}</span></td>
  <td class="num"><b>{mv["finalScore"]:.0f}</b></td>
  <td class="center">{mv["grade"]}</td>
  <td class="num"><b>{mv["violation_count"]}</b></td>
  <td>{sev_pills}</td>
  <td style="font-size:11.5px">{html_mod.escape(types_str)}</td>
</tr>''')
    p('</tbody></table>')

    # ───────────────────────────────────────
    # 7. 카테고리별 위반 패턴
    # ───────────────────────────────────────
    p('<h2>7. 카테고리별 위반 패턴 (모수 50건 이상)</h2>')
    p('<table><thead><tr><th>카테고리</th><th class="num">시나리오</th><th>주요 위반 유형 (발생 횟수)</th></tr></thead><tbody>')
    ctm = data['category_type_matrix']
    for cat in ['prescription', 'treatment', 'emergency', 'diagnosis', 'general', 'edge']:
        if cat not in ctm: continue
        info = ctm[cat]
        viol_str = ', '.join(f'<b>{html_mod.escape(t)}</b>({n})' for t, n in list(info['violations'].items())[:5])
        p(f'''<tr>
  <td><b>{cat}</b></td>
  <td class="num">{info["total"]}</td>
  <td style="font-size:12.5px">{viol_str}</td>
</tr>''')
    p('</tbody></table>')

    # ───────────────────────────────────────
    # 8. 위험도(risk_level) × 위반 심각도
    # ───────────────────────────────────────
    p('<h2>8. 시나리오 위험도 × 위반 심각도</h2>')
    p('<p style="color:var(--text-dim);font-size:12.5px">위험도가 높은 시나리오에서 CRITICAL 위반이 발생할 경우 환자 안전에 직접 영향.</p>')
    p('<table><thead><tr><th>시나리오 위험도</th><th class="num">건수</th><th class="num">총 위반</th><th class="num">건당 위반</th>')
    for sev in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        p(f'<th class="num"><span class="sev-badge sev-{sev}">{sev}</span></th>')
    p('</tr></thead><tbody>')
    for risk in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        rsm = data['risk_severity_matrix'].get(risk)
        if not rsm: continue
        p(f'''<tr>
  <td><span class="sev-badge sev-{risk}">{risk}</span></td>
  <td class="num">{rsm["scenarios"]}</td>
  <td class="num">{rsm["total_violations"]}</td>
  <td class="num">{rsm["avg_viol_per_scenario"]:.2f}</td>''')
        for sev in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
            n = rsm['by_severity'].get(sev, 0)
            if n > 0:
                p(f'<td class="num" style="background:{sev_color(sev)}22"><b>{n}</b></td>')
            else:
                p('<td class="num" style="color:var(--text-dim)">—</td>')
        p('</tr>')
    p('</tbody></table>')

    # ───────────────────────────────────────
    # 9. 점수 영향 (시나리오의 최고 심각도 위반에 따른 점수)
    # ───────────────────────────────────────
    p('<h2>9. 위반 심각도가 점수에 미치는 영향</h2>')
    p('<table><thead><tr><th>시나리오의 최고 심각도</th><th class="num">시나리오 수</th><th class="num">평균 점수</th><th class="num">중앙값</th></tr></thead><tbody>')
    score_by_sev = data['score_by_max_severity']
    for sev in ['NONE', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']:
        ss = score_by_sev.get(sev)
        if not ss: continue
        c = sev_color(sev) if sev != 'NONE' else '#22c55e'
        label_sev = sev if sev != 'NONE' else '위반 없음'
        p(f'''<tr>
  <td><span class="sev-badge" style="background:{c}">{label_sev}</span></td>
  <td class="num">{ss["count"]}</td>
  <td class="num"><b>{ss["mean"]:.1f}</b></td>
  <td class="num">{ss["median"]:.0f}</td>
</tr>''')
    p('</tbody></table>')

    crit_score = score_by_sev.get('CRITICAL', {}).get('mean', 0)
    none_score = score_by_sev.get('NONE', {}).get('mean', 0)
    diff = none_score - crit_score
    p(f'''<div class="callout callout-info">
  <b>해석</b>: 위반 없는 시나리오 평균 점수 <b>{none_score:.1f}</b> vs CRITICAL 위반 시나리오 평균 <b>{crit_score:.1f}</b> — 격차 <b>{diff:.1f}점</b>. CRITICAL이라도 점수가 완전히 0이 되지 않는 이유는 응답의 다른 영역에서 부분 점수가 인정되기 때문. 점수는 컴플라이언스의 전부가 아니며, <b>점수 70+여도 CRITICAL 위반이 있을 수 있음</b>을 의미.
</div>''')

    # ───────────────────────────────────────
    # 10. 카테고리별 Clean 비율 (위반 무관 응답 비율)
    # ───────────────────────────────────────
    p('<h2>10. 카테고리별 Clean 응답 비율</h2>')
    p('<p style="color:var(--text-dim);font-size:12.5px">위반이 단 1건도 없는 시나리오 비율 = 응답이 100% 합법적이었던 케이스.</p>')
    p('<table><thead><tr><th>카테고리</th><th class="num">전체</th><th class="num">Clean</th><th class="num">Clean율</th><th>시각화</th></tr></thead><tbody>')
    cbc = data['clean_by_category']
    sorted_cbc = sorted(cbc.items(), key=lambda kv: -kv[1]['clean_rate'])
    for cat, info in sorted_cbc:
        rate = info['clean_rate']
        c = '#22c55e' if rate >= 70 else ('#eab308' if rate >= 50 else '#dc2626')
        p(f'''<tr>
  <td><b>{cat}</b></td>
  <td class="num">{info["total"]}</td>
  <td class="num">{info["clean"]}</td>
  <td class="num" style="color:{c};font-weight:700">{rate:.1f}%</td>
  <td><div class="bar-track" style="margin:0"><div class="bar-fill" style="width:{rate:.1f}%;background:{c}">{rate:.0f}%</div></div></td>
</tr>''')
    p('</tbody></table>')

    # ───────────────────────────────────────
    # 11. 핵심 결론 (인사이트)
    # ───────────────────────────────────────
    p('<h2>11. 핵심 결론</h2>')
    weakest_cat_clean = min(sorted_cbc, key=lambda kv: kv[1]['clean_rate'])
    p(f'''<ol>
  <li><b>50.7%가 위반 발생, 13%가 4건+ 다중 위반</b> — 전체 응답의 절반에서 컴플라이언스 이슈. 일회성 실수가 아니라 구조적 패턴.</li>
  <li><b>의료법 제27조가 위반의 70%</b> — 검사·처방·치료·진단의 "지시" 표현이 가장 많은 위반 사유. 응답 시 의료진 역할을 흉내내는 표현 검출/대체 패턴이 시급.</li>
  <li><b>CRITICAL 위반 292건 (시나리오 182건)</b> — 단순 어조 문제가 아닌, 환자 안전에 직접 영향 가능한 표현. 즉시 응답 차단 또는 재생성 트리거 필요.</li>
  <li><b>응급의료법 관련 위반 210회</b> — 응급 시나리오에서 119/응급실 안내가 충분히 강하지 않거나 "단정적 분류"로 처리됨. 응급 상황 가이드 보강.</li>
  <li><b>{weakest_cat_clean[0]} 카테고리 Clean율 {weakest_cat_clean[1]["clean_rate"]:.1f}%로 가장 위험</b> — 해당 카테고리 응답 템플릿 우선 재설계.</li>
  <li><b>고득점(70+)에도 CRITICAL 위반 존재 가능</b> — 점수만으로 컴플라이언스를 보증할 수 없음. 위반 카운트 기반 별도 게이트 필요.</li>
  <li><b>필수 고정/말미 문구 누락 359회 (위반의 25%)</b> — 응답 후처리 단계에서 강제 삽입으로 즉시 해소 가능한 위반. ROI 가장 높은 개선.</li>
</ol>''')

    # ─── Footer
    p(f'''<footer style="margin-top:48px;padding-top:16px;border-top:1px solid var(--border);font-size:11px;color:var(--text-dim);text-align:center">
  생성: <code>scripts/analyze_run_1100_compliance.py</code> + <code>scripts/make_run_1100_compliance_report.py</code><br>
  데이터: <code>test_runs</code> 테이블의 <code>{m["id"]}</code> run · 위반 항목 누계 {total_v:,}건<br>
  <span style="opacity:0.7">© 의료 컴플라이언스 테스트 도구 — 2026</span>
</footer>
</div>
</body>
</html>''')

    return '\n'.join(parts)


if __name__ == '__main__':
    inp = sys.argv[1] if len(sys.argv) > 1 else 'data/run-1e71ae-compliance.json'
    outp = sys.argv[2] if len(sys.argv) > 2 else 'reports/scenario_1100_compliance.html'
    with open(inp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    html = render(data)
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'✓ HTML 작성: {outp}  ({os.path.getsize(outp):,} bytes)')
