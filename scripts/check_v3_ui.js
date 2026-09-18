// history.html 의 v3 렌더 함수만 떼어내 논리(교차표 집계·배지)를 검증한다. DOM 없이 돈다.
//
//   node scripts/check_v3_ui.js      (repo 루트에서. CI lint 게이트)
//
// 브라우저를 띄우지 않고도 잡히는 것: 교차표 집계, v2 통과×v3 위반 강조, 배지·칩·체크리스트
// 줄, 판정 실패 안내, v3 없는 배치에서 섹션을 아예 안 그리는지. 문법만 보는 js-syntax 검사와
// 달리 값이 맞게 들어가는지를 본다. 실패 시 exit 1.
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'history.html'), 'utf8');
const start = html.indexOf('  // ── v3 배치 요약 + v2 교차표');
const end = html.indexOf('  function renderBatchReport(run) {');
const popStart = html.indexOf('  // ── v3 온톨로지 판정 표시');
const popEnd = html.indexOf('  window.closeScenarioPopup =');
if (start < 0 || end < 0 || popStart < 0 || popEnd < 0) throw new Error('함수 구간을 못 찾음');

const shim = `
  const window = { };
  function escapeHtml(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
`;
const src = shim + html.slice(popStart, popEnd) + html.slice(start, end) +
  '\nreturn { buildV3ReportSection, buildEvalV3Html, v3VerdictOf, window };';
const mod = new Function(src)();

const mk = (id, v2pass, v3) => ({
  scenarioId: id, response: '답변', status: 'pass',
  gptEval: { passed: v2pass, grade: v2pass ? 'A' : 'C' },
  evalV3: v3,
});
const sv = (gate, grade, extra) => Object.assign({
  legal_verdict: gate, validity_grade: grade, validity_axis: 'SV',
  legal_hits: gate === 'fail' ? ['LG-05'] : [], validity_unmet: grade === 'C' ? ['SV-02'] : [],
  eval_version: 'v3.0-dev', ontology_version: 'v3.5', judge_model: 'gpt-5.4',
}, extra || {});

const results = [
  mk('S1', true,  sv('pass', 'A')),
  mk('S2', true,  sv('fail', 'D')),          // v2 통과 × v3 위반 — 강조 칸
  mk('S3', false, sv('pass', 'C')),
  mk('S4', true,  sv('pass', 'B')),
  mk('S5', true,  { error: 'RuntimeError: 판정 실패' }),
];

const sec = mod.buildV3ReportSection(results);
const cells = mod.window._v3Cells;
let bad = 0;
function check(label, ok) {
  console.log((ok ? '  ok   ' : '  FAIL ') + label);
  if (!ok) bad++;
}

console.log('[check_v3_ui] history.html v3 렌더');
console.log('교차표 칸:', JSON.stringify(Object.fromEntries(
  Object.entries(cells).map(([k, v]) => [k, v.map(x => x.scenarioId)]))));
check('게이트 통과 3건', sec.includes('>3</div><div class="bsc-label">게이트 통과'));
check('게이트 위반 1건', sec.includes('>1</div><div class="bsc-label">게이트 위반'));
check('판정 실패 1건', sec.includes('>1</div><div class="bsc-label">판정 실패'));
check('v2 통과 × v3 위반 칸 강조', sec.includes('#dc262618'));
check('버전 꼬리표', sec.includes('v3.0-dev · 온톨로지 v3.5 · gpt-5.4'));
check('v3 없는 배치는 섹션을 그리지 않음', mod.buildV3ReportSection([{ scenarioId: 'X' }]) === '');

const detail = mod.buildEvalV3Html(results[1]);
check('건별 게이트 위반 배지', detail.includes('게이트 위반'));
check('건별 걸린 규칙 LG-05', detail.includes('LG-05'));
const withCl = mod.buildEvalV3Html(mk('S6', true, sv('pass', 'C', {
  grade_cap: ['LG-16'],
  checklist: { symptom_key: 'fever', branch: '응급', red_flags_total: 3, red_flags_covered: 0,
               required_questions_pending: 2, lg16: true },
})));
check('건별 체크리스트 줄', withCl.includes('위험 신호 0/3 확인') && withCl.includes('fever'));
check('건별 등급 상한 표시', withCl.includes('등급 상한 LG-16'));
check('건별 판정 실패 안내', mod.buildEvalV3Html(results[4]).includes('판정 실패'));
check('건별 v3 없으면 빈 값', mod.buildEvalV3Html({ scenarioId: 'X' }) === '');


// ── 시나리오 관리 — 평가 기준 연계 필드 ────────────────────────────────
// 판정기 입력(증상군·분기·PHR 케이스)을 사람이 지정하는 자리다. 조용히 사라지면
// 다시 태그로만 연계해야 하므로 구조만 확인해 둔다.
{
  const sm = fs.readFileSync(path.join(ROOT, 'scenario_manager.html'), 'utf8');
  console.log('[check_v3_ui] scenario_manager.html 평가 기준 연계');
  for (const id of ['fSymptomKey', 'fBranch', 'fPhrCaseId']) {
    check(`입력 ${id}`, sm.includes(`id="${id}"`));
  }
  for (const key of ['symptomKey:', 'branch:', 'phrCaseId:']) {
    check(`저장 payload ${key}`, sm.includes(key));
  }
  check('증상군 목록을 체크리스트에서 받음', sm.includes('/api/checklists'));
  check('태그 폴백 유지', sm.includes("v3TagValue(tags, 'symptom:')"));
  for (const b of ['응급', '당일', '외래', '생활관리']) {
    check(`분기 ${b}`, sm.includes(`value="${b}"`));
  }
}

console.log(bad ? `[check_v3_ui] FAIL — ${bad}건` : '[check_v3_ui] OK');
process.exit(bad ? 1 : 0);
