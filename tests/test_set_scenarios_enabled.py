# -*- coding: utf-8 -*-
"""set_scenarios_enabled — 조건·건수 확인 후 enabled 만 바꾸고 태그로 이유를 남긴다."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import set_scenarios_enabled as se  # noqa: E402


class FakeDB:
    def __init__(self):
        self.rows = {r['id']: r for r in (
            [{'id': f'PHRQ-B{i:04d}', 'category': 'phr_case', 'enabled': True, 'tags': ['a']} for i in range(3)]
            + [{'id': 'PHRQR-B0001', 'category': 'phr_case_r', 'enabled': True, 'tags': []},
               {'id': 'GEN-1', 'category': 'phr_case', 'enabled': True, 'tags': []}])}

    def get_scenarios(self):  # db.get_scenarios 와 같은 scenarios.json 형식
        return {'version': '1.0', 'categories': [], 'scenarios': [dict(r) for r in self.rows.values()]}

    def update_scenario(self, sid, data):
        self.rows[sid].update(data)


def test_disables_only_matching_and_tags():
    db = FakeDB()
    kw = dict(category='phr_case', id_prefix='PHRQ-B', enabled=False, tag='retired:x', db=db, log=lambda *_: None)
    assert se.apply(expect=3, dry_run=True, **kw) == 0 and db.rows['PHRQ-B0000']['enabled'] is True
    assert se.apply(expect=3, **kw) == 0
    assert all(not db.rows[f'PHRQ-B{i:04d}']['enabled'] for i in range(3))
    assert db.rows['PHRQ-B0001']['tags'] == ['a', 'retired:x']
    assert db.rows['PHRQR-B0001']['enabled'] and db.rows['GEN-1']['enabled']
    assert se.apply(expect=3, **kw) == 0 and db.rows['PHRQ-B0001']['tags'] == ['a', 'retired:x']  # 재실행 무해


def test_guards():
    db = FakeDB()
    assert se.apply(enabled=False, db=db, log=lambda *_: None) == 2
    assert se.apply(category='phr_case', enabled=False, expect=3, db=db, log=lambda *_: None) == 3  # 4건 ≠ 3
    assert all(r['enabled'] for r in db.rows.values())
