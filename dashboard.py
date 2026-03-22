"""
HTML 대시보드 리포트 생성기
"""

import os
import json
import html as html_module
from datetime import datetime
from runner import TestSuiteResult, TestResult
from config import REPORT_CONFIG


class DashboardGenerator:
    """테스트 결과를 HTML 대시보드로 변환"""

    def generate(self, suite: TestSuiteResult, output_path: str = None) -> str:
        """HTML 대시보드 파일 생성"""
        if output_path is None:
            os.makedirs(REPORT_CONFIG["output_dir"], exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(REPORT_CONFIG["output_dir"], f"report_{ts}.html")

        html_content = self._build_html(suite)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        return output_path

    def _build_html(self, suite: TestSuiteResult) -> str:
        categories = suite.by_category()
        severities = suite.by_severity()

        # 카테고리별 차트 데이터
        cat_labels = json.dumps(list(categories.keys()), ensure_ascii=False)
        cat_passed = json.dumps([c["passed"] for c in categories.values()])
        cat_failed = json.dumps([c["failed"] for c in categories.values()])

        # 상세 결과 행
        detail_rows = self._build_detail_rows(suite.results)

        # 위반 유형별 집계
        violation_type_counts = {}
        for r in suite.results:
            for v in r.analysis.violations:
                key = v.rule_name
                violation_type_counts[key] = violation_type_counts.get(key, 0) + 1

        vtype_labels = json.dumps(list(violation_type_counts.keys()), ensure_ascii=False)
        vtype_values = json.dumps(list(violation_type_counts.values()))

        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>나만의 주치의 — 의료법 준수 테스트 리포트</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #0f172a; --surface: #1e293b; --surface2: #334155;
    --text: #e2e8f0; --text-dim: #94a3b8; --accent: #38bdf8;
    --green: #22c55e; --red: #ef4444; --yellow: #eab308; --orange: #f97316;
    --critical-bg: #3b1111; --high-bg: #3b2911; --medium-bg: #3b3511; --pass-bg: #113b1d;
    --border: #475569; --radius: 12px;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: 'Pretendard','Apple SD Gothic Neo',system-ui,sans-serif;
         background:var(--bg); color:var(--text); padding:24px; line-height:1.6; }}
  .container {{ max-width:1200px; margin:auto; }}

  /* Header */
  .header {{ text-align:center; margin-bottom:32px; }}
  .header h1 {{ font-size:28px; font-weight:700; margin-bottom:4px; }}
  .header .subtitle {{ color:var(--text-dim); font-size:14px; }}

  /* Summary Cards */
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin-bottom:32px; }}
  .card {{ background:var(--surface); border-radius:var(--radius); padding:20px; text-align:center; }}
  .card .value {{ font-size:32px; font-weight:700; }}
  .card .label {{ color:var(--text-dim); font-size:13px; margin-top:4px; }}
  .card.pass .value {{ color:var(--green); }}
  .card.fail .value {{ color:var(--red); }}
  .card.score .value {{ color:var(--accent); }}

  /* Pass rate ring */
  .ring-container {{ display:flex; justify-content:center; margin:24px 0; }}
  .ring-wrapper {{ position:relative; width:160px; height:160px; }}
  .ring-wrapper canvas {{ width:160px!important; height:160px!important; }}
  .ring-center {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
                   font-size:28px; font-weight:700; }}

  /* Charts */
  .charts {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; margin-bottom:32px; }}
  .chart-box {{ background:var(--surface); border-radius:var(--radius); padding:20px; }}
  .chart-box h3 {{ font-size:16px; margin-bottom:12px; color:var(--text-dim); }}

  /* Table */
  .table-section {{ margin-bottom:32px; }}
  .table-section h2 {{ font-size:20px; margin-bottom:16px; }}
  .filter-bar {{ display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }}
  .filter-btn {{ background:var(--surface2); border:1px solid var(--border); color:var(--text);
                  padding:6px 14px; border-radius:20px; cursor:pointer; font-size:13px; }}
  .filter-btn.active {{ background:var(--accent); color:#0f172a; border-color:var(--accent); }}
  table {{ width:100%; border-collapse:collapse; background:var(--surface); border-radius:var(--radius); overflow:hidden; }}
  thead th {{ background:var(--surface2); padding:12px 16px; text-align:left; font-size:13px;
              color:var(--text-dim); font-weight:600; white-space:nowrap; }}
  tbody td {{ padding:12px 16px; border-top:1px solid var(--border); font-size:13px; vertical-align:top; }}
  tbody tr:hover {{ background:rgba(56,189,248,.05); }}

  .badge {{ display:inline-block; padding:2px 10px; border-radius:10px; font-size:11px; font-weight:600; }}
  .badge-pass {{ background:var(--pass-bg); color:var(--green); }}
  .badge-fail {{ background:var(--critical-bg); color:var(--red); }}
  .badge-critical {{ background:var(--critical-bg); color:var(--red); }}
  .badge-high {{ background:var(--high-bg); color:var(--orange); }}
  .badge-medium {{ background:var(--medium-bg); color:var(--yellow); }}
  .badge-low {{ background:var(--pass-bg); color:var(--green); }}

  .expandable {{ cursor:pointer; }}
  .detail-row {{ display:none; }}
  .detail-row.open {{ display:table-row; }}
  .detail-cell {{ padding:16px 24px; background:rgba(15,23,42,.5); }}
  .detail-cell h4 {{ font-size:14px; margin-bottom:8px; color:var(--accent); }}
  .detail-cell .response-text {{ background:var(--bg); padding:12px; border-radius:8px;
                                  font-size:12px; line-height:1.5; max-height:200px; overflow-y:auto;
                                  white-space:pre-wrap; word-break:break-all; }}
  .violation-item {{ background:var(--bg); padding:10px; border-radius:8px; margin-bottom:8px;
                     border-left:3px solid var(--red); }}
  .violation-item .v-header {{ font-weight:600; font-size:13px; }}
  .violation-item .v-law {{ color:var(--text-dim); font-size:11px; }}
  .violation-item .v-match {{ background:var(--surface2); padding:4px 8px; border-radius:4px;
                              font-size:12px; margin-top:4px; display:inline-block; }}

  /* Footer */
  .footer {{ text-align:center; color:var(--text-dim); font-size:12px; padding:24px 0; }}

  @media(max-width:768px) {{
    .charts {{ grid-template-columns:1fr; }}
    .cards {{ grid-template-columns:repeat(2,1fr); }}
  }}
</style>
</head>
<body>
<div class="container">

  <!-- Header -->
  <div class="header">
    <h1>나만의 주치의 — 의료법 준수 테스트 리포트</h1>
    <div class="subtitle">생성: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | 소요: {suite.total_duration_ms:.0f}ms</div>
  </div>

  <!-- Summary Cards -->
  <div class="cards">
    <div class="card"><div class="value">{suite.total}</div><div class="label">전체 테스트</div></div>
    <div class="card pass"><div class="value">{suite.passed_count}</div><div class="label">통과</div></div>
    <div class="card fail"><div class="value">{suite.failed_count}</div><div class="label">실패</div></div>
    <div class="card score"><div class="value">{suite.avg_compliance_score:.0f}</div><div class="label">평균 준수 점수</div></div>
  </div>

  <!-- Pass Rate Ring -->
  <div class="ring-container">
    <div class="ring-wrapper">
      <canvas id="ringChart"></canvas>
      <div class="ring-center" style="color:{self._pass_color(suite.pass_rate)}">{suite.pass_rate:.0f}%</div>
    </div>
  </div>

  <!-- Charts -->
  <div class="charts">
    <div class="chart-box">
      <h3>카테고리별 통과/실패</h3>
      <canvas id="catChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>위반 유형별 빈도</h3>
      <canvas id="vtypeChart"></canvas>
    </div>
  </div>

  <!-- Detail Table -->
  <div class="table-section">
    <h2>상세 결과</h2>
    <div class="filter-bar">
      <button class="filter-btn active" onclick="filterTable('all')">전체</button>
      <button class="filter-btn" onclick="filterTable('fail')">실패만</button>
      <button class="filter-btn" onclick="filterTable('pass')">통과만</button>
      <button class="filter-btn" onclick="filterTable('critical')">CRITICAL</button>
    </div>
    <table id="resultTable">
      <thead>
        <tr>
          <th>ID</th><th>카테고리</th><th>세부</th><th>위험도</th>
          <th>준수점수</th><th>위반수</th><th>결과</th>
        </tr>
      </thead>
      <tbody>
        {detail_rows}
      </tbody>
    </table>
  </div>

  <div class="footer">
    나만의 주치의 — 의료법 준수 자동화 테스트 도구 v1.0<br>
    비의료기기 의료법 준수 검수 목적으로 사용됩니다.
  </div>
</div>

<script>
// Ring chart
new Chart(document.getElementById('ringChart'), {{
  type: 'doughnut',
  data: {{
    datasets: [{{
      data: [{suite.passed_count}, {suite.failed_count}],
      backgroundColor: ['#22c55e', '#ef4444'],
      borderWidth: 0, borderRadius: 4,
    }}]
  }},
  options: {{
    cutout: '78%', responsive: false,
    plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: false }} }}
  }}
}});

// Category chart
new Chart(document.getElementById('catChart'), {{
  type: 'bar',
  data: {{
    labels: {cat_labels},
    datasets: [
      {{ label: '통과', data: {cat_passed}, backgroundColor: '#22c55e88', borderColor: '#22c55e', borderWidth: 1 }},
      {{ label: '실패', data: {cat_failed}, backgroundColor: '#ef444488', borderColor: '#ef4444', borderWidth: 1 }}
    ]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
      y: {{ ticks: {{ color: '#94a3b8', stepSize: 1 }}, grid: {{ color: '#334155' }}, beginAtZero: true }}
    }}
  }}
}});

// Violation type chart
new Chart(document.getElementById('vtypeChart'), {{
  type: 'bar',
  data: {{
    labels: {vtype_labels},
    datasets: [{{
      label: '위반 횟수',
      data: {vtype_values},
      backgroundColor: ['#ef444488','#f9731688','#eab30888','#22c55e88'],
      borderColor: ['#ef4444','#f97316','#eab308','#22c55e'],
      borderWidth: 1
    }}]
  }},
  options: {{
    indexAxis: 'y', responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8', stepSize: 1 }}, grid: {{ color: '#334155' }}, beginAtZero: true }},
      y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
    }}
  }}
}});

// Toggle detail rows
document.querySelectorAll('.expandable').forEach(row => {{
  row.addEventListener('click', () => {{
    const detail = row.nextElementSibling;
    detail.classList.toggle('open');
  }});
}});

// Filter
function filterTable(type) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  document.querySelectorAll('#resultTable tbody tr').forEach(row => {{
    if (row.classList.contains('detail-row')) return;
    const status = row.dataset.status;
    const risk = row.dataset.risk;
    if (type === 'all') row.style.display = '';
    else if (type === 'fail') row.style.display = status === 'fail' ? '' : 'none';
    else if (type === 'pass') row.style.display = status === 'pass' ? '' : 'none';
    else if (type === 'critical') row.style.display = risk === 'CRITICAL' ? '' : 'none';
    // hide corresponding detail rows
    const next = row.nextElementSibling;
    if (next && next.classList.contains('detail-row')) {{
      next.style.display = 'none';
      next.classList.remove('open');
    }}
  }});
}}
</script>
</body>
</html>"""

    def _build_detail_rows(self, results: list) -> str:
        rows = []
        for r in results:
            status = "pass" if r.passed else "fail"
            badge = "badge-pass" if r.passed else "badge-fail"
            badge_text = "PASS" if r.passed else "FAIL"
            risk_badge = f"badge-{r.scenario.risk_level.lower()}"

            row = f"""<tr class="expandable" data-status="{status}" data-risk="{r.scenario.risk_level}">
  <td><code>{r.scenario.id}</code></td>
  <td>{html_module.escape(r.scenario.category)}</td>
  <td>{html_module.escape(r.scenario.subcategory)}</td>
  <td><span class="badge {risk_badge}">{r.scenario.risk_level}</span></td>
  <td>{r.analysis.compliance_score:.0f}</td>
  <td>{r.analysis.violation_count}</td>
  <td><span class="badge {badge}">{badge_text}</span></td>
</tr>"""

            # Detail row
            violations_html = ""
            if r.analysis.violations:
                for v in r.analysis.violations:
                    violations_html += f"""<div class="violation-item">
  <div class="v-header">[{v.severity}] {html_module.escape(v.rule_name)}</div>
  <div class="v-law">{html_module.escape(v.law)}</div>
  <div class="v-match">{html_module.escape(v.matched_text[:100])}</div>
</div>"""
            else:
                violations_html = '<div style="color:var(--green)">위반 사항 없음 ✅</div>'

            response_text = html_module.escape(r.raw_response[:500]) if REPORT_CONFIG.get("include_raw_response") else "(숨김)"

            detail = f"""<tr class="detail-row">
  <td colspan="7" class="detail-cell">
    <h4>프롬프트</h4>
    <div class="response-text">{html_module.escape(r.scenario.prompt)}</div>
    <h4 style="margin-top:12px">응답</h4>
    <div class="response-text">{response_text}</div>
    <h4 style="margin-top:12px">위반 탐지 결과</h4>
    {violations_html}
    <div style="margin-top:8px;color:var(--text-dim);font-size:11px">
      기대 동작: {html_module.escape(r.scenario.expected_behavior)} | 응답시간: {r.response_time_ms:.0f}ms
    </div>
  </td>
</tr>"""

            rows.append(row + detail)

        return "\n".join(rows)

    def _pass_color(self, rate: float) -> str:
        if rate >= 80:
            return "var(--green)"
        elif rate >= 50:
            return "var(--yellow)"
        return "var(--red)"
