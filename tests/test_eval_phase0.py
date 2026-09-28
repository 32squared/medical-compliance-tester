# -*- coding: utf-8 -*-
"""평가체계 개선 0단계 — 적재 무결성 검사, 판정 근거 보존, 응답시간 기록."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, ROOT)

import scenario_integrity as si  # noqa: E402

CASE = {
    'checkups': {'general': [{'tc': 184, 'bp': '128/82'}],
                 'cancer': [{'exam': '위암', 'result': '이상없음'}, {'exam': '대장암', 'result': '이상없음'}]},
    'counts': {'prescription': 0},
}


def _sc(**kw):
    base = {'id': 'Q1', 'phrCaseId': 'phr_CASE-01', 'prompt': '', 'expectedBehavior': '', 'tags': []}
    base.update(kw)
    return base


def test_integrity_ok_when_values_and_exam_exist():
    sc = _sc(prompt='위암 검진 결과 알려줘', expectedBehavior='총콜레스테롤 184.0 mg/dL 을 언급')
    assert si.check_row(sc, CASE) == []


def test_integrity_flags_wrong_person():
    sc = _sc(prompt='유방암 검진 결과 어때?', expectedBehavior='총콜레스테롤 231 mg/dL 을 언급')
    codes = sorted(p['code'] for p in si.check_row(sc, CASE))
    assert codes == ['exam_missing', 'expected_value']


def test_integrity_rx_missing_is_warning_and_expect_missing_skips():
    sc = _sc(prompt='내가 먹는 약 뭐야?')
    probs = si.check_row(sc, CASE)
    assert [(p['code'], p['severity']) for p in probs] == [('rx_missing', 'warn')]
    assert si.check_row(_sc(prompt='유방암 검진 했어?', tags=['expect:missing']), CASE) == []


def test_integrity_check_rows_reads_db_row_and_caches():
    calls = []

    def get_case(cid):
        calls.append(cid)
        return {'case': json.dumps(CASE, ensure_ascii=False)} if cid == 'phr_CASE-01' else None

    rows = [_sc(id='A', prompt='유방암?'), _sc(id='B'), _sc(id='C', phrCaseId='phr_CASE-09'), {'id': 'D'}]
    errors, warns = si.check_rows(rows, get_case)
    assert sorted((e['id'], e['code']) for e in errors) == [('A', 'exam_missing'), ('C', 'case_missing')]
    assert calls == ['phr_CASE-01', 'phr_CASE-09']
    assert si.summarize(errors)['counts'] == {'exam_missing': 1, 'case_missing': 1}


def test_seed_aborts_on_integrity_error(tmp_path, monkeypatch, capsys):
    import seed_scenarios_json as seed
    f = tmp_path / 's.json'
    f.write_text(json.dumps({'scenarios': [_sc(prompt='유방암 검진?', category='phr_case', title='t')]},
                            ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(seed, 'missing_cases', lambda rows: [])
    monkeypatch.setattr(seed.db, 'get_phr_case', lambda cid: {'case': CASE})
    monkeypatch.setattr(sys, 'argv', ['seed', '--file', str(f), '--dry-run'])
    assert seed.main() == 4
    assert 'exam_missing' in capsys.readouterr().out
    monkeypatch.setattr(sys, 'argv', ['seed', '--file', str(f), '--dry-run', '--allow-integrity'])
    assert seed.main() == 0


def test_remap_file_passes_integrity_shape():
    """적재된 350(재매핑) 파일은 검사 대상 키를 갖는다 — 실제 기록 대조는 운영 적재 시 수행."""
    rows = json.load(open(os.path.join(ROOT, 'scripts', 'scenarios_phr_case_350_remap.json'),
                          encoding='utf-8'))['scenarios']
    assert all(r.get('phrCaseId') and 'expectedBehavior' in r for r in rows)


def test_compact_keeps_hit_evidence():
    import eval_v3
    ev = [{'basis': 'lexicon', 'phrase_id': 'P1', 'text': 'x' * 400, 'person_attributed': False,
           'unknown_key': 1}] * 9
    rows = eval_v3.evidence_rows(ev)
    assert len(rows) == 6 and len(rows[0]['text']) == 160 and 'unknown_key' not in rows[0]
    res = {'verdict': 'fail', 'legal': {'verdict': 'fail', 'hits': [
        {'rule_id': 'LG-02', 'severity': 'high', 'quote': 'q' * 500, 'detectors': ['lexicon'],
         'decision': 'fail', 'evidence': ev}]}}
    out = eval_v3.compact(res)
    hits = [h for v in out.values() if isinstance(v, list) for h in v if isinstance(h, dict) and h.get('rule_id')]
    assert hits, out
    h = hits[0]
    assert len(h['quote']) == eval_v3.QUOTE_MAX and h['detectors'] == ['lexicon'] and len(h['evidence']) == 6


def test_report_parses_timing():
    import report_v3_run as rep
    assert rep.TIMING.search('fallback=- ttft=1234 total=5678 len=900')['ttft'] == '1234'
    m = rep.TIMING.search('fallback=- ttft=- total=- len=0')
    assert m['ttft'] == '-' and m['total'] == '-'


def test_job_runner_ms():
    """job_runner 는 import 시 stdout 을 바꾸므로 별도 프로세스에서 본다."""
    import subprocess
    code = ("import job_runner as j; print(j._ms(1234.6), j._ms(None), j._ms(''), j._ms('x'))")
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
                         env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    assert out.stdout.strip().splitlines()[-1] == '1235 - - -', out.stderr[-500:]


_IMPORT_SCRIPT = r"""
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1])
os.environ['DATABASE_URL'] = ''
import db, dbcommon
path = tempfile.mktemp(suffix='_import_h.db')
dbcommon._use_postgres, dbcommon._pg_pool, dbcommon.DB_PATH = False, None, path
db._use_postgres, db.DB_PATH = False, path
db.init_db(path)
import proxy_server as ps
CASE = json.loads(sys.argv[2])
ps.db.get_phr_case = lambda cid: {'case': CASE} if cid == 'phr_CASE-01' else None
try:
    sent = []
    h = ps.ProxyHandler.__new__(ps.ProxyHandler)
    h._send_json = lambda code, obj: sent.append((code, obj))
    h._send_error = lambda code, msg: sent.append((code, msg))
    bad = {'id': 'IMP-1', 'title': 't', 'prompt': '유방암 검진 결과?', 'category': 'phr_case',
           'phrCaseId': 'phr_CASE-01', 'expectedBehavior': ''}
    h._import_scenarios(json.dumps({'scenarios': [bad]}).encode())
    code, obj = sent[-1]
    assert code == 400 and obj['integrity']['counts'] == {'exam_missing': 1}, sent[-1]
    assert not db.get_scenario('IMP-1')
    h._import_scenarios(json.dumps({'scenarios': [bad], 'force': True}).encode())
    assert sent[-1][0] == 200 and db.get_scenario('IMP-1'), sent[-1]
    ok = dict(bad, id='IMP-2', prompt='위암 검진 결과?')
    h._import_scenarios(json.dumps({'scenarios': [ok]}).encode())
    assert sent[-1][0] == 200 and db.get_scenario('IMP-2'), sent[-1]
    print('IMPORT_OK')
finally:
    try:
        os.unlink(path)
    except OSError:
        pass
"""


def test_import_endpoint_blocks_integrity_errors(tmp_path):
    """POST /api/scenarios/import — 무결성 error 면 400, force 면 가져온다."""
    import subprocess
    script = tmp_path / 'import_check.py'
    script.write_text(_IMPORT_SCRIPT, encoding='utf-8')
    env = dict(os.environ, DATABASE_URL='', PYTHONIOENCODING='utf-8')
    p = subprocess.run([sys.executable, str(script), ROOT, json.dumps(CASE, ensure_ascii=False)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=120)
    assert p.returncode == 0 and 'IMPORT_OK' in p.stdout, (p.stdout[-2000:], p.stderr[-3000:])


def test_report_axis_only_no_total_score():
    """보고서는 축별로만 — 총점(환산 점수) 카드는 없다(2026-09-28 결정)."""
    import report_v3_run as rep
    items = [{'id': 'Q1', 'verdict': 'pass', 'legal': 'pass', 'hits': [], 'review': [], 'axis': 'PV', 'pv': 'A',
              'pv_unmet': [], 'uv': 'B', 'uv_unmet': ['UV-01'], 'intent': None, 'prompt': 'v18', 'skip': None,
              'esc': None, 'ttft': 1200, 'total': 9000},
             {'id': 'Q2', 'verdict': 'fail', 'legal': 'fail', 'hits': ['LG-02'], 'review': [], 'axis': 'PV',
              'pv': 'C', 'pv_unmet': ['PV-01'], 'uv': None, 'uv_unmet': [], 'intent': None, 'prompt': 'v18',
              'skip': None, 'esc': '1'}]
    out = rep.render('run-x', 'ex-1', items, {}, {})
    assert '운영 환산 점수' not in out and 'score_dist' not in out
    assert 'LG 법률 게이트' in out and 'PV 기록 활용 등급' in out and 'UV 사용자 가치 등급' in out
    assert '응답 속도' in out and '1 pass' in out
def test_eval_v3_pkg_override(tmp_path):
    """EVAL_V3_PKG 로 판정기 패키지 위치를 바꾼다(재판정 후보용). 기본은 packages/medical_eval."""
    import subprocess
    code = "import eval_v3 as e; print(e._PKG); print(e._SNAPSHOT_DIR)"
    env = dict(os.environ, EVAL_V3_PKG=str(tmp_path), PYTHONIOENCODING='utf-8')
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, env=env)
    lines = out.stdout.strip().splitlines()
    assert lines[-2] == str(tmp_path) and lines[-1] == os.path.join(str(tmp_path), 'ontology', 'snapshot'), out.stderr
    env.pop('EVAL_V3_PKG')
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, env=env)
    assert out.stdout.strip().splitlines()[-2].endswith(os.path.join('packages', 'medical_eval'))
