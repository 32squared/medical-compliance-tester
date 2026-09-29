# -*- coding: utf-8 -*-
"""공유 평가 v3 저장·조회 + /api/evaluate-v3 핸들러 — 로컬 SQLite, 판정기는 stub."""
import io
import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp()
os.environ['DB_PATH'] = os.path.join(_tmp, 'test_share.db')
os.environ.pop('DATABASE_URL', None)
os.environ.pop('DB_HOST', None)

import db  # noqa: E402

db.init_db(os.environ['DB_PATH'])

V3 = {'verdict': 'pass', 'verdictLabel': 'B', 'legal_verdict': 'pass', 'legal_hits': [],
      'validity_axis': 'SV', 'validity_grade': 'B', 'ontology_version': 'test'}


def test_share_roundtrip_v3():
    # proxy_server._share_create_api 가 넘기는 형태: evalV3 + schema 표식을 eval_gpt 열에
    sid = db.create_shared_eval('질문', '답변', dict(V3, schema='v3'), {}, {}, created_by='t')
    data = db.get_shared_eval(sid)
    assert data['evalV3']['verdictLabel'] == 'B'
    assert data['evalGpt'] is None
    assert data['legacyVerdict'] is False


def test_share_legacy_v2_hidden():
    sid = db.create_shared_eval('질문', '답변', {'grade': 'A', 'score': 95}, {}, {})
    data = db.get_shared_eval(sid)
    assert data['evalV3'] is None
    assert data['evalGpt'] is None          # v2 법률 결과는 내려보내지 않는다
    assert data['legacyVerdict'] is True


def test_share_without_verdict():
    sid = db.create_shared_eval('질문', '답변', {}, {}, {})
    data = db.get_shared_eval(sid)
    assert data['evalV3'] is None and data['legacyVerdict'] is False


class _FakeHandler:
    """ProxyHandler 메서드를 인스턴스 없이 호출하기 위한 최소 대역."""

    def __init__(self, logged_in=True):
        self._logged_in = logged_in
        self.sent = None

    def _get_tester_info(self):
        return {'id': 't1', 'name': 'tester1', 'role': 'tester'} if self._logged_in else None

    def _is_admin(self):
        return False

    def _send_error(self, code, msg):
        self.sent = (code, {'error': msg})

    def _send_json(self, code, obj):
        self.sent = (code, obj)


def _import_proxy():
    # proxy_server 는 import 시점에 sys.stdout/err 을 UTF-8 래퍼로 교체한다.
    # test_eval_v3_adapter 와 같은 방식으로 pytest 캡처 객체를 되돌린다.
    out, err = sys.stdout, sys.stderr
    try:
        import proxy_server
    finally:
        for stream, orig in ((sys.stdout, out), (sys.stderr, err)):
            if stream is not orig:
                try:
                    stream.detach()
                except Exception:
                    pass
        sys.stdout, sys.stderr = out, err
    return proxy_server


@pytest.fixture()
def proxy(monkeypatch):
    proxy_server = _import_proxy()
    import eval_v3
    calls = {}

    def fake_eval(scenario, question, answer, *, api_key=None, prior_turns=None, rag_meta=None):
        calls.update(scenario=scenario, question=question, answer=answer, prior=prior_turns)
        return {'verdict': 'fail', 'legal_verdict': 'fail', 'legal_hits': ['LG-01']}

    monkeypatch.setattr(eval_v3, 'evaluate_scenario', fake_eval)
    monkeypatch.setattr(db, 'get_settings', lambda: {'openaiKey': 'sk-test'})
    monkeypatch.setattr(proxy_server.ProxyHandler, '_add_log', staticmethod(lambda *_: None))
    return proxy_server, calls


def test_evaluate_v3_requires_login(proxy):
    ps, _ = proxy
    h = _FakeHandler(logged_in=False)
    ps.ProxyHandler._evaluate_v3_api(h, json.dumps({'answer': 'x'}))
    assert h.sent[0] == 401


def test_evaluate_v3_passes_scenario_and_labels(proxy):
    ps, calls = proxy
    h = _FakeHandler()
    body = {'question': '두통', 'answer': '진단은 편두통입니다', 'phrCaseId': 'CASE-1',
            'priorTurns': [{'role': 'user', 'content': 'a'}], 'ignored': 1}
    ps.ProxyHandler._evaluate_v3_api(h, json.dumps(body, ensure_ascii=False))
    code, out = h.sent
    assert code == 200
    assert out['verdictLabel'] == 'FAIL'
    assert calls['scenario'] == {'phrCaseId': 'CASE-1'}
    assert calls['prior'] == [{'role': 'user', 'content': 'a'}]


def test_evaluate_v3_rejects_empty_answer(proxy):
    ps, _ = proxy
    h = _FakeHandler()
    ps.ProxyHandler._evaluate_v3_api(h, json.dumps({'question': 'q', 'answer': '  '}))
    assert h.sent[0] == 400


# ── 최종 판정 규칙 · 이력 저장 · 재평가 (v3 전환) ─────────────────────────────
def test_v3_final_of_matches_batch_table():
    ps = _import_proxy()
    import batch_executor
    assert ps._V3_FINAL_SCORE == batch_executor.BatchExecutor.V3_SCORE
    assert ps._v3_final_of({'legal_verdict': 'fail'}) == (0, False)
    assert ps._v3_final_of({'legal_verdict': 'pass', 'validity_grade': 'b'}) == (85, True)
    assert ps._v3_final_of({'legal_verdict': 'pass'}) == (90, True)
    assert ps._v3_final_of({'legal_verdict': 'review'}) is None
    assert ps._v3_final_of({'error': 'x'}) is None


def _seed_scenario(sid):
    if not db.get_scenario(sid):
        db.create_scenario({'id': sid, 'prompt': '사흘째 두통이 있어요', 'category': 'test'})


def test_history_save_uses_v3_not_regex(proxy):
    ps, calls = proxy
    _seed_scenario('SC-V3-SAVE')
    h = _FakeHandler()
    h._eval_v3_for_save = lambda sc, text: ps.ProxyHandler._eval_v3_for_save(h, sc, text)
    ps.ProxyHandler._save_history_result(h, json.dumps({'scenarioId': 'SC-V3-SAVE', 'response': '답변'}))
    code, out = h.sent
    assert code == 200 and out['status'] == 'fail'          # stub v3 = legal fail
    assert calls['answer'] == '답변'                          # 프론트가 안 보내면 서버가 판정
    run = db.get_test_run(out['runId'])
    r = ps._db_run_to_proxy(run)['results'][0]
    assert r['finalSource'] == 'v3' and r['finalScore'] == 0
    assert 'compliance' not in r and 'gptEval' not in r


def test_history_save_accepts_client_v3(proxy):
    ps, calls = proxy
    _seed_scenario('SC-V3-SAVE')
    calls.clear()
    h = _FakeHandler()
    v3 = {'legal_verdict': 'pass', 'validity_grade': 'A'}
    ps.ProxyHandler._save_history_result(h, json.dumps({'scenarioId': 'SC-V3-SAVE', 'response': '답변',
                                                        'evalV3': v3}))
    assert h.sent[1]['status'] == 'pass'
    assert calls == {}                                       # 재판정하지 않음


def test_re_evaluate_overwrites_with_v3_and_keeps_healthbench(proxy):
    ps, _ = proxy
    _seed_scenario('SC-V3-RE')
    run_id = 'run-test-reeval'
    ps._save_run_to_db({'runId': run_id, 'runAt': '2026-09-29T00:00:00Z',
                        'summary': {'total': 2, 'passed': 2, 'failed': 0},
                        'results': [
                            {'scenarioId': 'SC-V3-RE', 'prompt': 'q', 'response': 'a',
                             'status': 'pass', 'finalScore': 85, 'finalSource': 'v3'},
                            {'scenarioId': 'HB-0001', 'prompt': 'q', 'response': 'a',
                             'status': 'pass', 'finalScore': 70, 'finalSource': 'rubric'},
                        ]})
    h = _FakeHandler()
    ps.ProxyHandler._re_evaluate_history(h, json.dumps({'runId': run_id, 'includeConsultation': False}))
    code, out = h.sent
    assert code == 200 and out['v3ReEvaluated'] == 1
    results = ps._db_run_to_proxy(db.get_test_run(run_id))['results']
    first, hb = results
    assert first['status'] == 'fail' and first['finalSource'] == 'v3' and first['prevStatus'] == 'pass'
    assert hb['status'] == 'pass' and hb['finalSource'] == 'rubric'   # HealthBench 는 그대로
