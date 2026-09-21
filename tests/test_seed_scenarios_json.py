# -*- coding: utf-8 -*-
"""seed_scenarios_json — PHR 케이스 존재 검사와 350건 적재 파일 형식."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
sys.path.insert(0, ROOT)

import seed_scenarios_json as seed  # noqa: E402

CASES = [{'id': 'phr_CASE-01', 'case_no': 'CASE-01'}, {'id': 'phr_CASE-02', 'case_no': 'CASE-02'}]


def test_missing_cases_empty_when_no_case_ids():
    assert seed.missing_cases([{'id': 'X', 'prompt': 'q'}], get_cases=lambda: []) == []


def test_missing_cases_matches_id_or_case_no():
    rows = [{'phrCaseId': 'phr_CASE-01'}, {'phrCaseId': 'CASE-02'}, {'phrCaseId': 'phr_CASE-09'}]
    assert seed.missing_cases(rows, get_cases=lambda: CASES) == ['phr_CASE-09']


def test_phr_case_350_file_loads_with_host_keys():
    rows = seed.load(os.path.join(ROOT, 'scripts', 'scenarios_phr_case_350.json'))
    assert len(rows) == 350
    assert len({r['id'] for r in rows}) == 350
    assert {r['category'] for r in rows} == {'phr_case'}
    assert all(r['phrCaseId'].startswith('phr_CASE-') for r in rows)
    assert len({r['phrCaseId'] for r in rows}) == 70
    assert all(isinstance(r['shouldRefuse'], bool) and r['enabled'] is True for r in rows)
    assert all(set(r) <= seed.ALLOWED for r in rows)
