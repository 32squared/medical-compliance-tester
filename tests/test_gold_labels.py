# -*- coding: utf-8 -*-
"""정답지 라벨 — 검증, 판정기 스냅샷, 일치율, 저장 API."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gold_labels as gl  # noqa: E402


def _res(sid, legal='fail', hits=('LG-02',), original=None):
    v3 = {'legal_verdict': legal, 'legal_hits': list(hits), 'validity_axis': 'PV', 'validity_grade': 'B',
          'uv_grade': 'C', 'ontology_version': 'v3.5', 'judge_model': 'gpt-5.4',
          'validity_items': [{'id': 'PV-01', 'result': 'met'}, {'id': 'PV-03', 'result': 'unmet'}],
          'uv_items': [{'id': 'UV-01', 'result': 'not_scored'}]}
    if original:
        v3['judge_original'] = original
        v3['human_review'] = {'verdict': legal}
    return {'scenarioId': sid, 'prompt': 'q', 'response': 'a', 'phrCaseId': 'phr_CASE-01', 'evalV3': v3}


def test_validate_rules():
    ok, errs = gl.validate({'legal': {'verdict': 'FAIL', 'rules': ['LG-02', 'LG-02']}, 'items': {'PV-01': 'Met'}})
    assert not errs and ok['legal'] == {'verdict': 'fail', 'rules': ['LG-02'], 'note': ''}
    assert ok['items'] == {'PV-01': 'met'}
    assert gl.validate({'legal': {'verdict': 'fail'}})[1]                       # fail 인데 규칙 없음
    assert gl.validate({'legal': {'verdict': 'pass', 'rules': ['LG-01']}})[1]   # pass 인데 규칙
    assert gl.validate({'legal': {'verdict': 'maybe'}})[1]
    assert gl.validate({'legal': {'verdict': 'pass'}, 'items': {'XX-1': 'met'}})[1]
    assert gl.validate({'legal': {'verdict': 'pass'}, 'items': {'UV-01': 'partial'}})[1]
    assert gl.validate('x')[1]


def test_judge_snapshot_uses_judge_original_after_human_review():
    s = gl.judge_snapshot(_res('A', legal='pass', hits=(),
                               original={'legal_verdict': 'fail', 'legal_hits': ['LG-04']}))
    assert s['legal_verdict'] == 'fail' and s['legal_hits'] == ['LG-04'] and s['human_review'] == 'pass'
    assert s['items'] == {'PV-01': 'met', 'PV-03': 'unmet', 'UV-01': 'not_scored'}
    assert 'response' not in json.dumps(s) and s['ontology_version'] == 'v3.5'


def test_agreement_metrics():
    def row(sid, who, h, j, items=None, jitems=None):
        return {'runId': 'R', 'scenarioId': sid, 'labelerId': who,
                'labels': {'legal': {'verdict': h}, 'items': items or {}},
                'judge': {'legal_verdict': j, 'items': jitems or {}}}
    rows = [row('A', 'u1', 'fail', 'fail'), row('B', 'u1', 'pass', 'fail'), row('C', 'u1', 'fail', 'pass'),
            row('D', 'u1', 'pass', 'pass', {'PV-01': 'met', 'PV-03': 'met', 'UV-01': 'met'},
                {'PV-01': 'met', 'PV-03': 'unmet', 'UV-01': 'not_scored'}),
            row('A', 'u2', 'fail', 'fail'), row('B', 'u2', 'fail', 'fail')]
    a = gl.agreement(rows)
    assert a['legal'] == {'tp': 3, 'fp': 1, 'fn': 1, 'tn': 1, 'precision': 0.75, 'recall': 0.75}
    assert a['items']['n'] == 2 and a['items']['agree'] == 0.5            # not_scored 는 비교 안 함
    assert a['cross'] == {'pairs': 2, 'legal_agree': 0.5}
    assert a['items_labeled'] == 4
    assert gl.agreement([])['legal']['precision'] is None


_API = r"""
import json, os, sys, tempfile
sys.path.insert(0, sys.argv[1]); sys.path.insert(0, os.path.join(sys.argv[1], 'tests'))
os.environ['DATABASE_URL'] = ''
import db, dbcommon
path = tempfile.mktemp(suffix='_gold.db')
dbcommon._use_postgres, dbcommon._pg_pool, dbcommon.DB_PATH = False, None, path
db._use_postgres, db.DB_PATH = False, path
db.init_db(path)
import proxy_server as ps
from test_gold_labels import _res
try:
    db.save_test_run({'id': 'R1', 'runAt': '2026-09-28T00:00:00Z', 'total': 2, 'passed': 0, 'failed': 2,
                      'env': 'prod', 'tester': 'job', 'results': [_res('S1'), _res('S2')], 'status': 'completed'})
    ps.db.get_phr_case = lambda cid: {'case': {'checkups': {'general': []}}}
    sent = []
    who = {'admin': False, 'tester': {'id': 'u1', 'name': 'reviewer1'}}
    h = ps.ProxyHandler.__new__(ps.ProxyHandler)
    h._send_json = lambda code, obj: sent.append((code, obj))
    h._send_error = lambda code, msg: sent.append((code, {'error': msg}))
    h._is_admin = lambda: who['admin']
    h._get_tester_info = lambda: who['tester']
    lab = {'legal': {'verdict': 'pass', 'rules': [], 'note': 'L3'}, 'items': {'PV-01': 'met', 'PV-03': 'met'}}
    h._v3_save_label(json.dumps({'runId': 'R1', 'scenarioId': 'S1', 'labels': lab}).encode())
    assert sent[-1][0] == 200, sent[-1]
    h._v3_save_label(json.dumps({'runId': 'R1', 'scenarioId': 'S1',
                                 'labels': {'legal': {'verdict': 'fail'}}}).encode())
    assert sent[-1][0] == 400 and 'rules' in sent[-1][1]['error'], sent[-1]
    h._v3_save_label(json.dumps({'runId': 'R1', 'scenarioId': 'NOPE', 'labels': lab}).encode())
    assert sent[-1][0] == 404, sent[-1]
    # second labeler (u2) cannot see u1's label
    who['tester'] = {'id': 'u2', 'name': 'reviewer2'}
    h._v3_save_label(json.dumps({'runId': 'R1', 'scenarioId': 'S1',
                                 'labels': {'legal': {'verdict': 'fail', 'rules': ['LG-02']}}}).encode())
    h._v3_review_item({'run': ['R1'], 'sid': ['S1'], 'all': ['1']})
    code, obj = sent[-1]
    assert code == 200 and [l['labelerId'] for l in obj['labels']] == ['u2'], obj['labels']
    assert obj['case'] == {'checkups': {'general': []}} and obj['judge']['legal_verdict'] == 'fail'
    assert obj['result']['response'] == 'a' and 'PV-01' in obj['rules']
    h._v3_list_labels({'run': ['R1'], 'all': ['1']})
    assert sent[-1][0] == 403
    who.update(admin=True, tester=None)
    h._v3_list_labels({'run': ['R1'], 'all': ['1']})
    code, obj = sent[-1]
    assert code == 200 and len(obj['labels']) == 2, obj
    assert obj['stats']['cross'] == {'pairs': 1, 'legal_agree': 0.0}, obj['stats']
    assert obj['stats']['legal']['fp'] == 1 and obj['stats']['legal']['tp'] == 1
    stored = db.get_gold_labels(run_id='R1', labeler_id='u1')[0]
    assert stored['judge']['legal_hits'] == ['LG-02'] and stored['labelerName'] == 'reviewer1'
    # AI 검수 라벨: 사람 라벨 목록·일치율에 섞이지 않고 aiLabels / ai 요약으로 따로 나온다
    db.save_gold_label({'run_id': 'R1', 'scenario_id': 'S1', 'labeler_id': 'ai:verifier', 'labeler_name': 'AI',
                        'labels': {'legal': {'verdict': 'pass', 'rules': [], 'note': ''}, 'items': {}},
                        'judge': {'legal_verdict': 'fail'},
                        'note': json.dumps({'needs_human': True, 'confidence': 'high', 'reasons': ['불일치']})})
    h._v3_list_labels({'run': ['R1'], 'all': ['1']})
    obj = sent[-1][1]
    assert obj['stats']['cross'] == {'pairs': 1, 'legal_agree': 0.0} and obj['aiStats']['legal']['fp'] == 1, obj
    who.update(admin=False, tester={'id': 'u1', 'name': 'reviewer1'})
    h._v3_review_item({'run': ['R1'], 'sid': ['S1']})
    obj = sent[-1][1]
    assert [l['labelerId'] for l in obj['labels']] == ['u1'] and obj['aiLabels'][0]['meta']['needs_human'] is True
    h._v3_list_labels({'run': ['R1']})
    obj = sent[-1][1]
    assert obj['ai'] == [{'scenarioId': 'S1', 'verdict': 'pass', 'needs_human': True, 'confidence': 'high',
                          'reasons': ['불일치']}], obj['ai']
    print('GOLD_OK')
finally:
    try:
        os.unlink(path)
    except OSError:
        pass
"""


def test_label_api(tmp_path):
    """저장·조회 핸들러. proxy_server import 는 stdout 을 바꾸므로 별도 프로세스에서."""
    import subprocess
    script = tmp_path / 'gold_check.py'
    script.write_text(_API, encoding='utf-8')
    env = dict(os.environ, DATABASE_URL='', PYTHONIOENCODING='utf-8')
    p = subprocess.run([sys.executable, str(script), ROOT], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=env, timeout=120)
    assert p.returncode == 0 and 'GOLD_OK' in p.stdout, (p.stdout[-2000:], p.stderr[-3000:])


def test_review_page_routed():
    s = open(os.path.join(ROOT, 'proxy_server.py'), encoding='utf-8').read()
    assert "'/review': 'review.html'" in s and "'/review':                 'view_history'" in s
    assert os.path.isfile(os.path.join(ROOT, 'review.html'))
