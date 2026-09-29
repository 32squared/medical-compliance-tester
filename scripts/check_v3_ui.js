// history.html 의 v3 렌더 함수만 떼어내 논리(판정 분포 집계·배지)를 검증한다. DOM 없이 돈다.
//
//   node scripts/check_v3_ui.js      (repo 루트에서. CI lint 게이트)
//
// 브라우저를 띄우지 않고도 잡히는 것: v3 판정 분포 집계, 판정 배지·칩·체크리스트 줄,
// 판정 실패 안내, v3 없는 배치에서 섹션을 아예 안 그리는지, v2·정규식 UI 가 남지 않았는지. 문법만 보는 js-syntax 검사와
// 달리 값이 맞게 들어가는지를 본다. 실패 시 exit 1.
const fs = require('fs');
const path = require('path');
const ROOT = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(ROOT, 'history.html'), 'utf8');
const start = html.indexOf('  // ── v3 배치 요약 (최종 판정)');
const end = html.indexOf('  function renderBatchReport(run) {');
const popStart = html.indexOf('  // ── v3 온톨로지 판정 표시');
const popEnd = html.indexOf('  window.closeScenarioPopup =');
if (start < 0 || end < 0 || popStart < 0 || popEnd < 0) throw new Error('함수 구간을 못 찾음');

const shim = `
  const window = { };
  function escapeHtml(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
`;
const src = shim + html.slice(popStart, popEnd) + html.slice(start, end) +
  '\nreturn { buildV3ReportSection, buildEvalV3Html, v3VerdictOf, v3VerdictBadge, window };';
const mod = new Function(src)();

const mk = (id, v3) => ({
  scenarioId: id, response: '답변', status: 'pass', finalScore: 90,
  evalV3: v3,
});
const sv = (gate, grade, extra) => Object.assign({
  legal_verdict: gate, validity_grade: grade, validity_axis: 'SV',
  legal_hits: gate === 'fail' ? ['LG-05'] : [], validity_unmet: grade === 'C' ? ['SV-02'] : [],
  eval_version: 'v3.0-dev', ontology_version: 'v3.5', judge_model: 'gpt-5.4',
}, extra || {});

const results = [
  mk('S1', sv('pass', 'A')),
  mk('S2', sv('fail', 'D')),                 // 게이트 위반 → FAIL
  mk('S3', sv('pass', 'C')),
  mk('S4', sv('pass', 'B')),
  mk('S5', { error: 'RuntimeError: 판정 실패' }),
  mk('S7', sv('pass', null)),                // 등급 없음 → PASS
];

const sec = mod.buildV3ReportSection(results);
const cells = mod.window._v3Cells;
let bad = 0;
function check(label, ok) {
  console.log((ok ? '  ok   ' : '  FAIL ') + label);
  if (!ok) bad++;
}

console.log('[check_v3_ui] history.html v3 렌더');
console.log('판정 칸:', JSON.stringify(Object.fromEntries(
  Object.entries(cells).map(([k, v]) => [k, v.map(x => x.scenarioId)]))));
check('판정 6건(오류 포함)', sec.includes('>6</div><div class="bsc-label">판정'));
check('게이트 통과 4건', sec.includes('>4</div><div class="bsc-label">게이트 통과'));
check('게이트 위반 1건', sec.includes('>1</div><div class="bsc-label">게이트 위반'));
check('판정 실패 1건', sec.includes('>1</div><div class="bsc-label">판정 실패'));
check('판정별 칸 FAIL=S2', JSON.stringify((cells.FAIL || []).map(x => x.scenarioId)) === '["S2"]');
check('판정별 칸 PASS=S7', JSON.stringify((cells.PASS || []).map(x => x.scenarioId)) === '["S7"]');
check('판정 분포 막대(건수 있는 판정마다 클릭 가능)', ['FAIL', 'A', 'B', 'C', 'PASS'].every(k => sec.includes('toggleV3Cell(\'' + k + '\')')));
check('v2 교차표 없음', !sec.includes('v2 통과') && !sec.includes('v2 실패'));
check('병존 문구 없음', !sec.includes('병존') && !sec.includes('반영되지 않'));
check('버전 꼬리표', sec.includes('v3.0-dev · 온톨로지 v3.5 · gpt-5.4'));
check('v3 없는 배치는 섹션을 그리지 않음', mod.buildV3ReportSection([{ scenarioId: 'X' }]) === '');
check('v3VerdictOf 규칙', mod.v3VerdictOf(results[1]) === 'FAIL' && mod.v3VerdictOf(results[0]) === 'A' && mod.v3VerdictOf(results[5]) === 'PASS' && mod.v3VerdictOf(results[4]) === null);

const detail = mod.buildEvalV3Html(results[1]);
check('건별 게이트 위반 배지', detail.includes('게이트 위반'));
check('건별 최종 판정 배지 FAIL', detail.includes('>FAIL<') && detail.includes('(최종)'));
check('건별 카드 형식(result-section)', mod.buildEvalV3Html(results[1], true).includes('class="result-section"'));
check('건별 병존 문구 없음', !detail.includes('병존') && !detail.includes('반영되지 않'));
check('건별 걸린 규칙 LG-05', detail.includes('LG-05'));
const withCl = mod.buildEvalV3Html(mk('S6', sv('pass', 'C', {
  grade_cap: ['LG-16'],
  checklist: { symptom_key: 'fever', branch: '응급', red_flags_total: 3, red_flags_covered: 0,
               required_questions_pending: 2, lg16: true },
})));
check('건별 체크리스트 줄', withCl.includes('위험 신호 0/3 확인') && withCl.includes('fever'));
check('건별 등급 상한 표시', withCl.includes('등급 상한 LG-16'));
check('건별 판정 실패 안내', mod.buildEvalV3Html(results[4]).includes('판정 실패'));
check('건별 v3 없으면 빈 값', mod.buildEvalV3Html({ scenarioId: 'X' }) === '');


// ── v2·정규식 UI 가 남지 않았는지 (v3 가 유일한 최종 판정) ──────────────
{
  console.log('[check_v3_ui] v2·정규식 UI 제거');
  const banned = ['정규식', '패턴 분석', '4분면', 'gptEval', 'regexScore', '.compliance.', 'v2 통과', 'v2 실패',
    '정규식만 재평가', '컴플라이언스 평가 포함', 'segFilterGrade', 'segFilterViolation'];
  for (const b of banned) check(`history.html 에 '${b}' 없음`, !html.includes(b));
  const sm0 = fs.readFileSync(path.join(ROOT, 'scenario_manager.html'), 'utf8');
  for (const b of ['/api/evaluate\'', '/api/evaluate"', 'evaluate-phr', '정규식', 'regexScore']) {
    check(`scenario_manager.html 에 '${b}' 없음`, !sm0.includes(b));
  }
  // 법률 기준 관리 화면(정규식·v2 전용)은 삭제됨 — 파일도, 서버 라우트도 없어야 한다
  check('guideline_manager.html 삭제됨', !fs.existsSync(path.join(ROOT, 'guideline_manager.html')));
  const ps = fs.readFileSync(path.join(ROOT, 'proxy_server.py'), 'utf8');
  check('서버에 /guidelines 화면·guidelines/test 라우트 없음',
    !ps.includes("'/guidelines':") && !ps.includes('guidelines/test'));
  check('이력 헤더에 단일 다시 평가 버튼', html.includes('다시 평가</button>') && !html.includes('reEvaluateBatch'));
  check('판정 필터(segFilterVerdict)', html.includes('segFilterVerdict'));
}

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
