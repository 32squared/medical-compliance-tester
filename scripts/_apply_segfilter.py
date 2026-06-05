"""세그먼트 필터 패치 적용 — history.html"""
import sys

path = 'history.html'
with open(path, 'rb') as f:
    text = f.read().decode('utf-8')

old_lines = [
    "    const results = run.results || [];",
    "    const area = document.getElementById('resultsArea');",
    "",
    "    let progressHtml = '';",
    "    if (run.status === 'running') {",
    "      const completed = (run.summary?.passed || 0) + (run.summary?.failed || 0) + (run.summary?.error || 0);",
    "      progressHtml = '<div style=\"color:var(--accent);font-size:12px;margin-bottom:12px\">\\u23F3 ' + completed + '/' + (run.summary?.total || 0) + ' \\uC644\\uB8CC \\u2014 \\uC790\\uB3D9 \\uAC31\\uC2E0 \\uC911...</div>';",
    "    }",
    "",
    "    if (results.length === 0) {",
    "      area.innerHTML = progressHtml + '<div class=\"empty-state\"><div class=\"empty-desc\">결과 데이터가 없습니다.</div></div>';",
    "      return;",
    "    }",
    "",
    "    area.innerHTML = progressHtml + results.map((r, idx) => {",
]
old = '\r\n'.join(old_lines)

new_lines = [
    "    const rawResults = run.results || [];",
    "    const area = document.getElementById('resultsArea');",
    "",
    "    // P1-6: 세그먼트 필터",
    "    window._currentRunResults = rawResults;",
    "    window._currentRunMeta = run;",
    "",
    "    const _catSet = {}; const _riskSet = {}; const _violSet = {};",
    "    for (const _r of rawResults) {",
    "      if (_r.category) _catSet[_r.category] = true;",
    "      if (_r.riskLevel) _riskSet[_r.riskLevel] = true;",
    "      if (_r.compliance && _r.compliance.violations) {",
    "        for (const _v of _r.compliance.violations) {",
    "          const _vn = _v.name || _v.rule || _v.rule_name;",
    "          if (_vn) _violSet[_vn] = true;",
    "        }",
    "      }",
    "    }",
    "    const catList = Object.keys(_catSet).sort();",
    "    const riskList = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].filter(r => _riskSet[r]);",
    "    const violList = Object.keys(_violSet).sort();",
    "",
    "    window._segFilter = window._segFilter || { status: '', grade: '', risk: '', category: '', violation: '', search: '' };",
    "    const F = window._segFilter;",
    "",
    "    let progressHtml = '';",
    "    if (run.status === 'running') {",
    "      const completed = (run.summary?.passed || 0) + (run.summary?.failed || 0) + (run.summary?.error || 0);",
    "      progressHtml = '<div style=\"color:var(--accent);font-size:12px;margin-bottom:12px\">\\u23F3 ' + completed + '/' + (run.summary?.total || 0) + ' \\uC644\\uB8CC \\u2014 \\uC790\\uB3D9 \\uAC31\\uC2E0 \\uC911...</div>';",
    "    }",
    "",
    "    const results = rawResults.filter((r) => {",
    "      if (F.status && (r.status || '').toLowerCase() !== F.status) return false;",
    "      if (F.grade) {",
    "        const g = (r.gptEval && r.gptEval.grade) || '';",
    "        if (F.grade === 'N/A' && g) return false;",
    "        if (F.grade !== 'N/A' && g !== F.grade) return false;",
    "      }",
    "      if (F.risk && (r.riskLevel || '') !== F.risk) return false;",
    "      if (F.category && (r.category || '') !== F.category) return false;",
    "      if (F.violation) {",
    "        const hasViol = (r.compliance && r.compliance.violations || []).some(v => (v.name || v.rule || v.rule_name) === F.violation);",
    "        if (!hasViol) return false;",
    "      }",
    "      if (F.search) {",
    "        const q = F.search.toLowerCase();",
    "        const inPrompt = (r.prompt || '').toLowerCase().includes(q);",
    "        const inResp = (r.response || '').toLowerCase().includes(q);",
    "        if (!inPrompt && !inResp) return false;",
    "      }",
    "      return true;",
    "    });",
    "",
    "    const _statusOpts = '<option value=\"\">\\uC0C1\\uD0DC: \\uC804\\uCCB4</option>' + ['pass','fail','error'].map(s => '<option value=\"' + s + '\"' + (F.status === s ? ' selected' : '') + '>' + s.toUpperCase() + '</option>').join('');",
    "    const _gradeOpts  = '<option value=\"\">\\uB4F1\\uAE09: \\uC804\\uCCB4</option>' + ['A','B','C','D','F','N/A'].map(g => '<option value=\"' + g + '\"' + (F.grade === g ? ' selected' : '') + '>' + g + '</option>').join('');",
    "    const _riskOpts   = riskList.length ? ('<option value=\"\">\\uB9AC\\uC2A4\\uD06C: \\uC804\\uCCB4</option>' + riskList.map(r => '<option value=\"' + r + '\"' + (F.risk === r ? ' selected' : '') + '>' + r + '</option>').join('')) : '';",
    "    const _catOpts    = catList.length ? ('<option value=\"\">\\uCE74\\uD14C\\uACE0\\uB9AC: \\uC804\\uCCB4</option>' + catList.map(c => '<option value=\"' + escapeHtml(c) + '\"' + (F.category === c ? ' selected' : '') + '>' + escapeHtml(c) + '</option>').join('')) : '';",
    "    const _violOpts   = violList.length ? ('<option value=\"\">\\uC704\\uBC18: \\uC804\\uCCB4</option>' + violList.map(v => '<option value=\"' + escapeHtml(v) + '\"' + (F.violation === v ? ' selected' : '') + '>' + escapeHtml(v) + '</option>').join('')) : '';",
    "",
    "    const filterBar = '<div class=\"seg-filter\" style=\"background:var(--bg);padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-bottom:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center\">' +",
    "      '<span style=\"font-size:11px;color:var(--text-dim);font-weight:600\">\\uD83D\\uDD0D \\uD544\\uD130</span>' +",
    "      '<select id=\"segFilterStatus\" style=\"padding:4px 6px;font-size:11px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:4px\">' + _statusOpts + '</select>' +",
    "      '<select id=\"segFilterGrade\" style=\"padding:4px 6px;font-size:11px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:4px\">' + _gradeOpts + '</select>' +",
    "      (_riskOpts ? '<select id=\"segFilterRisk\" style=\"padding:4px 6px;font-size:11px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:4px\">' + _riskOpts + '</select>' : '') +",
    "      (_catOpts ? '<select id=\"segFilterCategory\" style=\"padding:4px 6px;font-size:11px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:4px\">' + _catOpts + '</select>' : '') +",
    "      (_violOpts ? '<select id=\"segFilterViolation\" style=\"padding:4px 6px;font-size:11px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:4px;max-width:200px\">' + _violOpts + '</select>' : '') +",
    "      '<input id=\"segFilterSearch\" type=\"text\" placeholder=\"\\uD14D\\uC2A4\\uD2B8 \\uAC80\\uC0C9...\" value=\"' + escapeHtml(F.search) + '\" style=\"flex:1;min-width:120px;padding:4px 8px;font-size:11px;background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:4px\">' +",
    "      '<span style=\"font-size:11px;color:var(--accent);font-weight:600\">' + results.length + ' / ' + rawResults.length + '\\uAC74</span>' +",
    "      '<button onclick=\"resetSegFilter()\" style=\"padding:4px 8px;font-size:11px;background:transparent;color:var(--text-dim);border:1px solid var(--border);border-radius:4px;cursor:pointer\">\\uCD08\\uAE30\\uD654</button>' +",
    "      '</div>';",
    "",
    "    if (results.length === 0) {",
    "      area.innerHTML = progressHtml + filterBar + '<div class=\"empty-state\"><div class=\"empty-desc\">\\uD544\\uD130 \\uC870\\uAC74\\uC5D0 \\uB9DE\\uB294 \\uACB0\\uACFC\\uAC00 \\uC5C6\\uC2B5\\uB2C8\\uB2E4.</div></div>';",
    "      bindSegFilterEvents();",
    "      return;",
    "    }",
    "",
    "    area.innerHTML = progressHtml + filterBar + results.map((r, idx) => {",
]
new = '\r\n'.join(new_lines)

if old in text:
    text = text.replace(old, new)
    with open(path, 'wb') as f:
        f.write(text.encode('utf-8'))
    print("OK")
else:
    print("FAIL — exact match not found")
    sys.exit(1)
