# -*- coding: utf-8 -*-
"""rejudge_v3 — 저장된 답변 재판정: 원본 보존, 새 이력 저장, 사람 검토와 비교."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, ROOT)

import rejudge_v3 as rj  # noqa: E402
import eval_v3 as real_v3  # noqa: E402


def _res(sid, legal, hits, review=None, response='답변'):
    v3 = {'legal_verdict': legal, 'legal_hits': hits, 'validity_grade': 'A', 'versions': {'ontology': '3.5'}}
    r = {'scenarioId': sid, 'prompt': 'q ' + sid, 'response': response, 'finalSource': 'v3',
         'status': 'pass' if legal == 'pass' else 'fail', 'finalScore': 100 if legal == 'pass' else 0,
         'evalV3': v3}
    if review:
        v3['judge_original'] = {'legal_verdict': 'fail', 'legal_hits': ['LG-02']}
        v3['human_review'] = review
        r['humanReview'] = review
    return r


class FakeDB:
    def __init__(self, runs):
        self.runs = runs
        self.saved = []

    def get_test_run(self, rid):
        return self.runs.get(rid)

    def get_scenario(self, sid):
        return {'id': sid, 'prompt': 'db ' + sid, 'tags': ['case:phr_CASE-01']}

    def get_settings(self):
        return {'openaiKey': 'k'}

    def save_test_run(self, run):
        self.saved.append(run)
        self.runs[run['id']] = run


class FakeV3:
    """새 판정: B1 은 pass 로 바뀌고 나머지는 원래대로."""
    final_of = staticmethod(real_v3.final_of)
    count_status = staticmethod(real_v3.count_status)
    calls = []

    @staticmethod
    def available():
        return True, ''

    @staticmethod
    def _ensure_checklists_env():
        return 'x'

    @staticmethod
    def versions():
        return {'ontology': '3.6'}

    @classmethod
    def evaluate_scenario(cls, sc, q, a, api_key=None):
        cls.calls.append((sc['id'], q, api_key))
        sid = sc['id']
        return {'legal_verdict': 'pass' if sid in ('B1', 'B2') else 'fail',
                'legal_hits': [] if sid in ('B1', 'B2') else ['LG-01'], 'validity_grade': 'B'}


REV = {'verdict': 'pass', 'reason': '거짓 검출', 'by': 'a', 'at': 't', 'judge_verdict': 'fail'}


def _src():
    return {'id': 'SRC', 'env': 'prod', 'status': 'completed', 'guidelineVersion': 'g',
            'results': [_res('B1', 'pass', [], review=REV), _res('B2', 'fail', ['LG-02']),
                        _res('B3', 'fail', ['LG-01']), _res('B4', 'pass', [], response='')]}


def test_rejudge_saves_new_run_and_keeps_source():
    db = FakeDB({'SRC': _src()})
    FakeV3.calls = []
    code, new = rj.rejudge('SRC', 'NEW', db=db, eval_v3=FakeV3, log=lambda *_: None)
    assert code == 0 and [r['scenarioId'] for r in new] == ['B1', 'B2', 'B3']  # 답변 없는 B4 제외
    assert db.runs['SRC']['results'][1]['status'] == 'fail'                      # 원본 그대로
    run = db.saved[-1]
    assert (run['id'], run['total'], run['passed'], run['failed'], run['env']) == ('NEW', 3, 2, 1, 'prod')
    assert run['tester'] == 'rejudge:SRC'
    b1, b2, b3 = run['results']
    assert b2['status'] == 'pass' and b2['finalScore'] == 85 and b2['rejudgeOf']['legal_hits'] == ['LG-02']
    assert b1['priorHumanReview'] == REV and b1['agreesWithReview'] is True and 'humanReview' not in b1
    assert b1['rejudgeOf']['judge_original']['legal_verdict'] == 'fail'
    assert b3['status'] == 'fail' and b3['finalScore'] == 0 and 'agreesWithReview' not in b3
    assert FakeV3.calls[0] == ('B1', 'q B1', 'k')


def test_rejudge_ids_dry_run_and_guards():
    db = FakeDB({'SRC': _src(), 'OLD': {'id': 'OLD'}})
    code, new = rj.rejudge('SRC', 'NEW', ids=['B2'], dry_run=True, db=db, eval_v3=FakeV3, log=lambda *_: None)
    assert code == 0 and [r['scenarioId'] for r in new] == ['B2'] and not db.saved
    assert rj.rejudge('SRC', 'NEW', ids=['NOPE'], db=db, eval_v3=FakeV3, log=lambda *_: None)[0] == 3
    assert rj.rejudge('SRC', 'OLD', db=db, eval_v3=FakeV3, log=lambda *_: None)[0] == 5   # 덮어쓰지 않음
    assert rj.rejudge('SRC', 'SRC', db=db, eval_v3=FakeV3, log=lambda *_: None)[0] == 2
    assert rj.rejudge('X', 'NEW', db=db, eval_v3=FakeV3, log=lambda *_: None)[0] == 4


def test_rejudge_judge_error_keeps_result_as_error_verdict():
    class Boom(FakeV3):
        @classmethod
        def evaluate_scenario(cls, *a, **k):
            raise RuntimeError('x')
    db = FakeDB({'SRC': _src()})
    code, new = rj.rejudge('SRC', 'NEW', ids=['B3'], dry_run=True, db=db, eval_v3=Boom, log=lambda *_: None)
    assert code == 0 and new[0]['evalV3']['error'].startswith('RuntimeError')
    assert new[0]['status'] == 'fail'   # 판정 실패면 원래 상태 유지(final_of=None)


def test_entrypoint_has_rejudge_mode():
    s = open(os.path.join(ROOT, 'entrypoint.sh'), encoding='utf-8').read()
    assert 'RUN_MODE" = "rejudge_v3"' in s and 'scripts/rejudge_v3.py' in s
