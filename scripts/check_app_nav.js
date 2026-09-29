// app_nav.js 섹션 탭 로직 검증 (가짜 DOM 으로 로드 후 순수 함수만 호출)
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'app_nav.js'), 'utf8');
const win = { location: { pathname: '/', origin: 'http://x' } };
const doc = { readyState: 'loading', addEventListener() {}, getElementById() { return null; } };
new Function('window', 'document', 'fetch', src)(win, doc, () => Promise.resolve({ ok: true, json: () => ({}) }));
const N = win.AppNav;
let fail = 0;
function eq(name, got, want) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) fail++;
  console.log((ok ? 'OK   ' : 'FAIL ') + name + (ok ? '' : ' got=' + JSON.stringify(got) + ' want=' + JSON.stringify(want)));
}
const labels = s => s && s.tabs.map(t => t.label);
const activeOf = s => s && s.tabs.filter(t => t.active).map(t => t.label);

const admin = { isAdmin: true, permissions: ['*'] };
let s = N._sectionFor('/manager', N._visibleMenus(admin));
eq('admin /manager tabs', labels(s), ['시나리오', 'HealthBench', 'PHR 케이스']);
eq('admin /manager active', activeOf(s), ['시나리오']);

const tester = { tester: { role: 'tester' }, permissions: ['manage_scenarios', 'view_history'] };
s = N._sectionFor('/manager', N._visibleMenus(tester));
eq('tester /manager tabs', labels(s), ['시나리오', 'HealthBench']);
eq('tester /manager active', activeOf(s), ['시나리오']);

const advisor = { tester: { role: 'advisor' }, userRole: 'advisor', permissions: ['*'] };
eq('advisor / none', N._sectionFor('/', N._visibleMenus(advisor)), null);

s = N._sectionFor('/healthbench/about', N._visibleMenus(admin));
eq('/healthbench/about active', activeOf(s), ['HealthBench']);
s = N._sectionFor('/healthbench/scenario', N._visibleMenus(admin));
eq('/healthbench/scenario active', activeOf(s), ['HealthBench']);
s = N._sectionFor('/arena', N._visibleMenus(admin));
eq('admin /arena tabs', labels(s), ['단일 대화', 'A·B 비교']);
eq('admin /arena segmented', s.segmented, true);
s = N._sectionFor('/history', N._visibleMenus(admin));
eq('admin /history tabs', labels(s), ['테스트 이력', '정답지 검토', '자문 판정']);
s = N._sectionFor('/external-eval', N._visibleMenus(admin));
eq('admin /external-eval tabs', labels(s), ['문진 평가 기준', '외부 답변 평가']);
s = N._sectionFor('/settings', N._visibleMenus(admin));
eq('admin /settings tabs', labels(s), ['설정', 'RLHF 관리', 'KB 관리', '검색 API 점검']);
eq('unknown path none', N._sectionFor('/nope', N._visibleMenus(admin)), null);
const anon = {};
eq('anon / none', N._sectionFor('/', N._visibleMenus(anon)), null);

if (fail) { console.log(fail + ' failed'); process.exit(1); }
console.log('check_app_nav: all passed');
