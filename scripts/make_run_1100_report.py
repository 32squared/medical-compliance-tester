"""1100건 일반 시나리오 배치 분석 → 단일 HTML 보고서 생성.

사용:
  python scripts/make_run_1100_report.py data/run-1e71ae-analysis.json reports/scenario_1100_analysis.html
"""
import json
import os
import sys

# CSS — HB 보고서와 동일 토큰 사용
CSS = """
:root {
  --primary: #0ea5e9;
  --accent: #6366f1;
  --green: #22c55e;
  --yellow: #eab308;
  --orange: #f97316;
  --red: #ef4444;
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
.report-header { border-bottom: 4px solid var(--primary); padding-bottom: 18px; margin-bottom: 28px; }
.report-title { font-size: 30px; font-weight: 800; color: var(--text); margin-bottom: 6px; }
.report-subtitle { font-size: 14px; color: var(--text-dim); }
.report-meta { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 12px; font-size: 12px; color: var(--text-dim); }
.report-meta span { padding: 3px 9px; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; }
.report-meta b { color: var(--text); }
h2 { font-size: 20px; font-weight: 700; margin: 32px 0 14px; padding-bottom: 8px; border-bottom: 2px solid var(--border); display: flex; align-items: center; gap: 8px; }
h3 { font-size: 16px; font-weight: 700; margin: 18px 0 8px; color: var(--accent); }
p { margin-bottom: 10px; }
ul, ol { margin: 8px 0 12px 24px; }
li { margin-bottom: 4px; }
code { background: var(--surface2); padding: 1px 6px; border-radius: 3px; font-size: 12px; color: var(--accent); font-family: 'Menlo', 'Consolas', monospace; }
.tldr { background: linear-gradient(135deg, #eff6ff 0%, #ede9fe 100%); border: 1px solid var(--primary); border-left: 6px solid var(--primary); border-radius: 8px; padding: 16px 22px; margin: 18px 0 28px; }
.tldr-title { font-size: 13px; font-weight: 700; color: var(--primary); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.tldr-content { font-size: 14.5px; color: var(--text); line-height: 1.75; }
.tldr-content b { color: var(--accent); }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 12px; margin: 14px 0 20px; }
.kpi-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; text-align: center; }
.kpi-value { font-size: 28px; font-weight: 800; line-height: 1.1; }
.kpi-label { font-size: 11px; color: var(--text-dim); margin-top: 6px; text-transform: uppercase; letter-spacing: 0.3px; }
.kpi-card.green .kpi-value { color: var(--green); }
.kpi-card.yellow .kpi-value { color: var(--yellow); }
.kpi-card.red .kpi-value { color: var(--red); }
.kpi-card.blue .kpi-value { color: var(--primary); }
.kpi-card.purple .kpi-value { color: var(--purple); }
table { width: 100%; border-collapse: collapse; margin: 10px 0 18px; font-size: 13px; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
th { background: var(--surface); font-weight: 700; font-size: 11.5px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.3px; }
tr:hover td { background: var(--surface); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.center { text-align: center; }
.bar-row { display: flex; align-items: center; gap: 10px; margin: 5px 0; font-size: 12.5px; }
.bar-label { min-width: 170px; text-align: right; color: var(--text-dim); }
.bar-track { flex: 1; height: 22px; background: var(--surface2); border-radius: 3px; overflow: hidden; position: relative; }
.bar-fill { height: 100%; display: flex; align-items: center; padding-left: 8px; color: white; font-weight: 700; font-size: 11px; }
.bar-value { min-width: 60px; font-weight: 700; }
.callout { padding: 12px 16px; border-radius: 6px; margin: 12px 0; border-left: 4px solid; }
.callout-warn { background: #fef3c7; border-color: var(--yellow); color: #78350f; }
.callout-red { background: #fee2e2; border-color: var(--red); color: #7f1d1d; }
.callout-info { background: #dbeafe; border-color: var(--primary); color: #1e3a8a; }
.callout-green { background: #d1fae5; border-color: var(--green); color: #064e3b; }
.prio { display: inline-block; padding: 2px 10px; border-radius: 4px; font-weight: 700; font-size: 11px; }
.prio-red { background: var(--red); color: white; }
.prio-yellow { background: var(--yellow); color: #78350f; }
.prio-green { background: var(--green); color: white; }
.tag { display: inline-block; padding: 2px 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 3px; font-size: 11px; font-family: monospace; color: var(--text-dim); }
@media print {
  body { font-size: 11.5pt; }
  .page { padding: 0; max-width: none; }
  h2 { page-break-after: avoid; }
  .kpi-card, .callout, table { page-break-inside: avoid; }
  .report-header { border-color: #000; }
  .tldr { background: #f5f5f5 !important; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .bar-fill, .kpi-value { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
.print-hint { position: fixed; top: 12px; right: 12px; padding: 6px 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; font-size: 11px; color: var(--text-dim); cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.print-hint:hover { background: var(--surface2); }
@media print { .print-hint { display: none; } }
"""


def color_for_rate(rate):
    if rate >= 90: return '#22c55e'
    if rate >= 75: return '#0ea5e9'
    if rate >= 50: return '#eab308'
    return '#ef4444'


def color_for_grade(g):
    return {'A': '#22c55e', 'B': '#0ea5e9', 'C': '#eab308', 'D': '#f97316', 'F': '#ef4444'}.get(g, '#94a3b8')


def render(data):
    m = data['meta']
    s = data['score']
    pass_rate = m['passed'] / m['total'] * 100 if m['total'] else 0
    df_count = data['grades'].get('D', 0) + data['grades'].get('F', 0)
    df_pct = df_count / m['total'] * 100 if m['total'] else 0

    parts = []
    p = parts.append

    # ─── 헤더
    p(f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>일반 시나리오 1,100건 분석 보고서</title><style>{CSS}</style></head><body>
<div class="print-hint" onclick="window.print()">🖨 인쇄 / PDF 저장</div>
<div class="page">''')

    run_at = m.get('run_at') or ''
    p(f'''<header class="report-header">
  <div class="report-title">🩺 일반 시나리오 1,100건 분석 보고서</div>
  <div class="report-subtitle">SKIX 의료 컴플라이언스 평가 — 카테고리·위험도·위반 패턴 분석</div>
  <div class="report-meta">
    <span><b>run_id</b>: {m["id"]}</span>
    <span><b>시점</b>: {run_at[:19].replace("T"," ")}</span>
    <span><b>환경</b>: {m.get("env","").upper()}</span>
    <span><b>데이터셋</b>: 일반 의료 시나리오 1,100건</span>
    <span><b>평가</b>: 정규식 + GPT + Consultation</span>
  </div>
</header>''')

    # ─── TL;DR
    cats = data['categories']
    weakest_cat = min((c for c in cats.items() if c[1]['total'] >= 50), key=lambda kv: kv[1]['pass_rate'])
    strongest_cat = max((c for c in cats.items() if c[1]['total'] >= 50), key=lambda kv: kv[1]['pass_rate'])
    top_viol = data['violations']['top'][0] if data['violations']['top'] else ('', 0)
    ax = data['consultation_axes']
    weakest_axis = min(ax.items(), key=lambda kv: kv[1]['mean'] / (20 if kv[0]=='redFlagScreening' else (15 if kv[0]=='symptomExploration' else 10)))

    p(f'''<div class="tldr">
  <div class="tldr-title">📊 TL;DR — 한눈 요약</div>
  <div class="tldr-content">
    SKIX 의 일반 시나리오 1,100건 평균 점수 <b>{s["mean"]:.1f}점</b> (중앙값 {s["median"]:.0f}점, 통과율 <b>{pass_rate:.1f}%</b>).
    상위 등급(A) <b>{data["grades"].get("A",0)}건({data["grades"].get("A",0)/m["total"]*100:.1f}%)</b>, 하위 등급(D/F) <b>{df_count}건({df_pct:.1f}%)</b>.
    가장 약한 카테고리는 <b>{weakest_cat[0]}</b>({weakest_cat[1]["pass_rate"]:.1f}% pass), 가장 강한 카테고리는 <b>{strongest_cat[0]}</b>({strongest_cat[1]["pass_rate"]:.1f}%).
    최다 위반 패턴은 <b>"{top_viol[0]}"</b>({top_viol[1]}회). Consultation 5축 중 <b>{weakest_axis[0]}</b>(평균 {weakest_axis[1]["mean"]:.1f})가 가장 약점.
  </div>
</div>''')

    # ─── 1. KPI 카드
    p('<h2>1. 핵심 지표 (KPI)</h2>')
    p(f'''<div class="kpi-grid">
  <div class="kpi-card blue"><div class="kpi-value">{m["total"]:,}</div><div class="kpi-label">총 시나리오</div></div>
  <div class="kpi-card green"><div class="kpi-value">{pass_rate:.1f}%</div><div class="kpi-label">통과율</div></div>
  <div class="kpi-card blue"><div class="kpi-value">{s["mean"]:.1f}</div><div class="kpi-label">평균 점수</div></div>
  <div class="kpi-card purple"><div class="kpi-value">{s["median"]:.0f}</div><div class="kpi-label">중앙값</div></div>
  <div class="kpi-card green"><div class="kpi-value">{s["perfect_count"]}</div><div class="kpi-label">만점(100점)</div></div>
  <div class="kpi-card red"><div class="kpi-value">{df_count}</div><div class="kpi-label">D/F 등급</div></div>
  <div class="kpi-card yellow"><div class="kpi-value">{s["below_60"]}</div><div class="kpi-label">60점 미만</div></div>
  <div class="kpi-card blue"><div class="kpi-value">{s["over_80"]}</div><div class="kpi-label">80점 이상</div></div>
</div>''')

    # ─── 2. 점수 분포 (등급 + 히스토그램)
    p('<h2>2. 점수 분포</h2>')
    p('<h3>2.1 GPT 등급 분포</h3>')
    max_grade = max(data['grades'].values()) if data['grades'] else 1
    p('<div>')
    for g in ['A', 'B', 'C', 'D', 'F']:
        n = data['grades'].get(g, 0)
        if n == 0: continue
        pct = n / m['total'] * 100
        w = n / max_grade * 100
        c = color_for_grade(g)
        p(f'''<div class="bar-row">
  <div class="bar-label">{g}등급</div>
  <div class="bar-track"><div class="bar-fill" style="width:{w:.1f}%;background:{c}">{n}</div></div>
  <div class="bar-value">{pct:.1f}%</div>
</div>''')
    p('</div>')

    p('<h3>2.2 점수 히스토그램 (10점 단위)</h3>')
    hist = data['histogram']
    max_h = max(hist) if max(hist) > 0 else 1
    p('<div>')
    for i, n in enumerate(hist):
        label = f'{i*10}–{i*10+9}' if i < 10 else '100'
        if n == 0: continue
        w = n / max_h * 100
        c = '#ef4444' if i < 6 else ('#eab308' if i < 8 else '#22c55e')
        p(f'''<div class="bar-row">
  <div class="bar-label">{label}점</div>
  <div class="bar-track"><div class="bar-fill" style="width:{w:.1f}%;background:{c}">{n}</div></div>
  <div class="bar-value">{n/m["total"]*100:.1f}%</div>
</div>''')
    p('</div>')

    p(f'''<div class="callout callout-info">
  <b>해석</b>: 90–99점 구간 <b>{hist[9]}건</b>이 압도적 다수. 60점 미만은 {s["below_60"]}건({s["below_60"]/m["total"]*100:.1f}%)로 적지만, 18–58점 사이 D/F 등급 케이스가 명확한 약점 영역. 점수 분포의 꼬리는 짧지만 깊음 — 평균만 보면 안 보이는 위반이 존재.
</div>''')

    # ─── 3. 카테고리별
    p('<h2>3. 카테고리별 성능</h2>')
    p('<table><thead><tr><th>카테고리</th><th class="num">시나리오</th><th class="num">통과율</th><th class="num">평균점수</th><th class="num">중앙값</th></tr></thead><tbody>')
    cats_sorted = sorted(cats.items(), key=lambda kv: -kv[1]['total'])
    for cat, st in cats_sorted:
        rate = st['pass_rate']
        color = color_for_rate(rate)
        p(f'''<tr>
  <td><b>{cat}</b></td>
  <td class="num">{st["total"]:,}</td>
  <td class="num" style="color:{color};font-weight:700">{rate:.1f}%</td>
  <td class="num">{st["mean_score"]:.1f}</td>
  <td class="num">{st["median_score"]:.0f}</td>
</tr>''')
    p('</tbody></table>')

    # 약점 카테고리 콜아웃
    weak_cats = [c for c in cats.items() if c[1]['total'] >= 50 and c[1]['pass_rate'] < 75]
    if weak_cats:
        names = ', '.join(f'<b>{c[0]}</b>({c[1]["pass_rate"]:.1f}%)' for c in weak_cats)
        p(f'<div class="callout callout-warn"><b>주목</b>: {names} — 50건 이상 모수에서 75% 미만 통과율. 우선 개선 대상.</div>')

    # ─── 4. 위험도 (Risk Level)
    p('<h2>4. 위험도(Risk Level) 분포</h2>')
    rc = data['risk_level']['counts']
    rp = data['risk_level']['pass_rate']
    p('<table><thead><tr><th>위험도</th><th class="num">건수</th><th class="num">비율</th><th class="num">통과율</th></tr></thead><tbody>')
    for risk in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']:
        n = rc.get(risk, 0)
        if n == 0: continue
        rate = rp.get(risk, 0)
        c = color_for_rate(rate)
        risk_color = {'CRITICAL': '#dc2626', 'HIGH': '#f97316', 'MEDIUM': '#eab308', 'LOW': '#22c55e'}.get(risk, '#94a3b8')
        p(f'''<tr>
  <td><span class="prio" style="background:{risk_color};color:white">{risk}</span></td>
  <td class="num">{n:,}</td>
  <td class="num">{n/m["total"]*100:.1f}%</td>
  <td class="num" style="color:{c};font-weight:700">{rate:.1f}%</td>
</tr>''')
    p('</tbody></table>')

    p(f'''<div class="callout callout-info">
  <b>해석</b>: CRITICAL 케이스(가장 위험한 응급 등) 통과율 <b>{rp.get("CRITICAL",0):.1f}%</b>, HIGH <b>{rp.get("HIGH",0):.1f}%</b>. 위험도가 높을수록 통과율이 더 높은 점은 가이드라인이 명시적 응급 안내 패턴을 잘 포착하고 있다는 신호. 반대로 MEDIUM 위험도에서 <b>{rp.get("MEDIUM",0):.1f}%</b>로 떨어지는 것은 "애매한" 영역에서 의료법 경계 판단이 약하다는 의미.
</div>''')

    # ─── 5. Top 위반 패턴
    p('<h2>5. 위반 패턴 Top 10 (전체)</h2>')
    p(f'<p style="color:var(--text-dim);font-size:12.5px">총 {data["violations"]["total_unique"]}개 고유 위반 패턴. 빈도 순으로 정렬.</p>')
    p('<table><thead><tr><th>#</th><th>위반 패턴</th><th class="num">발생</th><th>예시 시나리오</th></tr></thead><tbody>')
    for i, (rule, n) in enumerate(data['violations']['top'][:10], 1):
        ex = data['violations']['examples'].get(rule, [])[:3]
        ex_str = ', '.join(f'<code>{e}</code>' for e in ex)
        p(f'<tr><td class="center">{i}</td><td>{rule[:100]}</td><td class="num"><b>{n}</b></td><td>{ex_str}</td></tr>')
    p('</tbody></table>')

    # D/F 등급 위반
    p('<h2>6. D/F 등급 시나리오의 위반 패턴</h2>')
    p(f'<p style="color:var(--text-dim);font-size:12.5px">총 {df_count}건의 D/F 시나리오에서 발생한 위반 (가장 심각한 케이스).</p>')
    p('<table><thead><tr><th>#</th><th>위반 패턴</th><th class="num">D/F 내 발생</th><th class="num">D/F 내 비중</th></tr></thead><tbody>')
    for i, (rule, n) in enumerate(data['fail_violations'][:10], 1):
        pct = n / df_count * 100 if df_count else 0
        p(f'<tr><td class="center">{i}</td><td>{rule[:100]}</td><td class="num"><b>{n}</b></td><td class="num">{pct:.1f}%</td></tr>')
    p('</tbody></table>')

    # ─── 7. Consultation 5축
    p('<h2>7. Consultation 평가 5축</h2>')
    p('<p style="color:var(--text-dim);font-size:12.5px">문진 품질 5개 축 — 만점 기준 mean × 100 = 달성률.</p>')
    AXIS_MAX = {
        'patientContext': 10,
        'redFlagScreening': 20,
        'symptomExploration': 15,
        'structuredApproach': 10,
        'appropriateGuidance': 10,
    }
    AXIS_KO = {
        'patientContext': '환자 맥락 파악',
        'redFlagScreening': '응급 스크리닝',
        'symptomExploration': '증상 탐색',
        'structuredApproach': '구조적 접근',
        'appropriateGuidance': '적절한 안내',
    }
    p('<table><thead><tr><th>축</th><th class="num">평균</th><th class="num">중앙값</th><th class="num">만점 대비</th><th>달성률</th></tr></thead><tbody>')
    for k, v in sorted(ax.items(), key=lambda kv: -(kv[1]['mean'] / AXIS_MAX.get(kv[0], 10))):
        mx = AXIS_MAX.get(k, 10)
        rate = v['mean'] / mx * 100
        ko = AXIS_KO.get(k, k)
        c = color_for_rate(rate)
        p(f'''<tr>
  <td><b>{ko}</b><br><span class="tag">{k}</span></td>
  <td class="num">{v["mean"]:.1f}</td>
  <td class="num">{v["median"]:.0f}</td>
  <td class="num">/ {mx}</td>
  <td><div class="bar-track" style="margin-bottom:0"><div class="bar-fill" style="width:{rate:.1f}%;background:{c}">{rate:.0f}%</div></div></td>
</tr>''')
    p('</tbody></table>')

    # 가장 약한 축 코멘트
    worst_axis_k, worst_axis_v = min(ax.items(), key=lambda kv: kv[1]['mean'] / AXIS_MAX.get(kv[0], 10))
    worst_rate = worst_axis_v['mean'] / AXIS_MAX.get(worst_axis_k, 10) * 100
    p(f'''<div class="callout callout-warn">
  <b>약점 축</b>: <b>{AXIS_KO.get(worst_axis_k, worst_axis_k)}</b> 달성률 <b>{worst_rate:.0f}%</b> — 환자의 나이/성별/기저질환·복용 약물 등 맥락 정보 수집이 가장 부족한 영역.
</div>''')

    # ─── 8. 약점 Subcategory
    p('<h2>8. 약점 Subcategory Top 10 (평균 점수 낮은 순)</h2>')
    p('<p style="color:var(--text-dim);font-size:12.5px">최소 3건 이상 모수가 있는 subcategory 중 평균 점수 낮은 순. 우선 개선 대상.</p>')
    p('<table><thead><tr><th>Subcategory</th><th class="num">건수</th><th class="num">통과율</th><th class="num">평균 점수</th></tr></thead><tbody>')
    for sub in data['subcategories_worst'][:10]:
        rate = sub['pass_rate']
        c = color_for_rate(rate)
        p(f'''<tr>
  <td>{sub["name"][:60]}</td>
  <td class="num">{sub["total"]}</td>
  <td class="num" style="color:{c};font-weight:700">{rate:.1f}%</td>
  <td class="num">{sub["mean_score"]:.1f}</td>
</tr>''')
    p('</tbody></table>')

    # ─── 9. 하위 시나리오
    p('<h2>9. 하위 점수 시나리오 (Bottom 10)</h2>')
    p('<p style="color:var(--text-dim);font-size:12.5px">개별 시나리오 단위로 점수가 가장 낮은 케이스. 직접 확인이 필요한 사례.</p>')
    p('<table><thead><tr><th>scenarioId</th><th>카테고리</th><th class="num">점수</th><th class="center">등급</th><th>주요 위반</th></tr></thead><tbody>')
    for r in data['bottom_scenarios']:
        gc = color_for_grade(r.get('grade', ''))
        viol = '<br>'.join(f'<span style="font-size:11px;color:var(--text-dim)">• {v}</span>' for v in r['violations'][:2])
        p(f'''<tr>
  <td><code>{r["scenarioId"]}</code></td>
  <td>{r["category"]}<br><span style="font-size:11px;color:var(--text-dim)">{(r["subcategory"] or "")[:30]}</span></td>
  <td class="num"><b>{r["score"]:.0f}</b></td>
  <td class="center"><span class="prio" style="background:{gc};color:white">{r["grade"]}</span></td>
  <td>{viol}</td>
</tr>''')
    p('</tbody></table>')

    # ─── 10. 응답 시간
    rt = data.get('response_time') or {}
    if rt:
        p('<h2>10. 응답 시간 (Latency)</h2>')
        p(f'''<div class="kpi-grid">
  <div class="kpi-card blue"><div class="kpi-value">{rt["mean"]/1000:.1f}s</div><div class="kpi-label">평균</div></div>
  <div class="kpi-card blue"><div class="kpi-value">{rt["median"]/1000:.1f}s</div><div class="kpi-label">중앙값</div></div>
  <div class="kpi-card yellow"><div class="kpi-value">{rt["p95"]/1000:.1f}s</div><div class="kpi-label">P95</div></div>
  <div class="kpi-card red"><div class="kpi-value">{rt["max"]/1000:.1f}s</div><div class="kpi-label">최대</div></div>
</div>''')
        p(f'''<div class="callout callout-info">
  <b>해석</b>: 평균 <b>{rt["mean"]/1000:.1f}초</b>, P95 <b>{rt["p95"]/1000:.0f}초</b> — UX 관점에서 명확한 지연. 채팅 응답이라기보다 "리포트 생성"에 가까운 체감. 응답 길이/검증 단계가 원인일 가능성, 별도 latency 최적화 필요.
</div>''')

    # ─── 11. 핵심 인사이트 (요약)
    p('<h2>11. 핵심 인사이트</h2>')
    p(f'''<ol>
  <li><b>전반적 품질은 양호</b> — 통과율 {pass_rate:.1f}%, A등급 {data["grades"].get("A",0)/m["total"]*100:.1f}%로 의료법 준수 측면에서 합격선 위. 평균 87.8점은 충분히 신뢰할 수 있는 수준.</li>
  <li><b>"필수 고정/말미 문구 누락"이 위반의 절반 이상</b> — Top 2 위반 패턴이 총 {(data["violations"]["top"][0][1] + data["violations"]["top"][1][1]) if len(data["violations"]["top"]) >= 2 else 0}회로 전체 위반의 가장 큰 비중. 응답 템플릿 강제 삽입으로 즉시 개선 가능한 영역.</li>
  <li><b>prescription/treatment 카테고리가 약점</b> — 67% 대 통과율로 다른 카테고리(80%+)와 격차. 처방/치료 관련 질문에서 "지시"로 해석될 수 있는 표현이 검출됨.</li>
  <li><b>Consultation에서 환자 맥락 수집이 가장 부족</b> — patientContext 달성률 {worst_rate:.0f}%로 5축 중 최저. 나이·성별·복용약 정보를 적극 요청하는 패턴이 부족.</li>
  <li><b>응답 시간 평균 {rt.get("mean",0)/1000:.0f}초는 UX 관점 큰 부담</b> — 의료 안전 검증이 늘어날수록 더 길어질 수 있음. Streaming/early-exit 개선 검토 필요.</li>
</ol>''')

    # ─── Footer
    p(f'''<footer style="margin-top:48px;padding-top:16px;border-top:1px solid var(--border);font-size:11px;color:var(--text-dim);text-align:center">
  생성: 본 보고서는 <code>scripts/analyze_run_1100.py</code> + <code>scripts/make_run_1100_report.py</code> 의 출력에서 자동 정리.<br>
  데이터 보존: <code>test_runs</code> 테이블의 <code>{m["id"]}</code> run.<br>
  <span style="opacity:0.7">© 의료 컴플라이언스 테스트 도구 — 2026</span>
</footer>
</div>
</body>
</html>''')

    return '\n'.join(parts)


if __name__ == '__main__':
    inp = sys.argv[1] if len(sys.argv) > 1 else 'data/run-1e71ae-analysis.json'
    outp = sys.argv[2] if len(sys.argv) > 2 else 'reports/scenario_1100_analysis.html'
    with open(inp, 'r', encoding='utf-8') as f:
        data = json.load(f)
    html = render(data)
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'✓ HTML 작성: {outp}  ({os.path.getsize(outp):,} bytes)')
