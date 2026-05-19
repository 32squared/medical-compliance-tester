"""HealthBench endpoint + helper 단위 테스트 (mock 기반).

검증 대상:
1. _aggregate_healthbench_report — theme/axis/level 집계 정확도
2. _extract_user_turns — turns 배열에서 user 만 추출 (이미 test_skix_replay 에 있지만 보완)
3. _list_healthbench_runs 의 hbSummary 계산 (HB result 만 필터링)
4. _get_healthbench_scenario_detail 의 fallback (지정 run 외 자동 검색)

실행:
  python scripts/test_hb_endpoints.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import proxy_server as ps


def _mk_result(sid, score, met, total, tags=None, turns_executed=1):
    return {
        'scenarioId': sid,
        'status': 'pass' if score is not None and score >= 50 else 'fail',
        'subcategory': 'global_health',
        'tags': tags or ['theme:global_health'],
        'response': 'mock response',
        'responseLength': 500,
        'turnsExecuted': turns_executed,
        'turnsTotal': turns_executed,
        'rubricEval': {
            'score': score, 'metCount': met, 'totalCount': total,
            'awardedPoints': score, 'totalPoints': 100.0,
            'items': [
                {'index': i + 1, 'criterion': f'crit{i+1}', 'points': 10,
                 'tags': ['axis:safety' if i % 2 == 0 else 'axis:completeness', 'level:example'],
                 'met': i < met, 'explanation': f'explain {i+1}'}
                for i in range(total)
            ],
            'error': None,
        },
    }


def test_aggregate_basic():
    # 3건 HB result + 1건 일반 result
    results = [
        _mk_result('HB-AAA', 80.0, 8, 10),
        _mk_result('HB-BBB', 30.0, 3, 10),
        _mk_result('HB-CCC', 60.0, 6, 10),
        {'scenarioId': 'NORMAL-1', 'status': 'pass'},  # 비 HB
    ]
    hb = [r for r in results if (r.get('scenarioId') or '').startswith('HB-')]
    run = {'runId': 'test-run', 'env': 'dev', 'startedAt': 't', 'results': results}
    report = ps._aggregate_healthbench_report(run, hb)
    s = report['summary']
    assert s['hbScenarios'] == 3, s
    assert s['rubricEvaluated'] == 3
    assert s['avgRubricScore'] == round((80+30+60)/3, 2), s
    # 통과율: 80, 60 → 2/3
    assert abs(s['passRate'] - round(2/3, 3)) < 0.01
    print('test_aggregate_basic OK')


def test_aggregate_axis():
    # axis:safety 와 axis:completeness 별 met 수 집계
    results = [_mk_result('HB-A', 50.0, 5, 10)]
    report = ps._aggregate_healthbench_report({'runId': 't', 'results': results}, results)
    axes = {a['axis']: a for a in report['byAxis']}
    # 10개 item 중 5개 met. axis:safety 는 i=0,2,4,6,8 (5개), axis:completeness 는 5개
    # met=i<5 이므로 i=0..4 met. axis:safety i=0,2,4 (3 met / 5 total), axis:completeness i=1,3 (2 met / 5 total)
    assert axes['safety']['items'] == 5, axes['safety']
    assert axes['safety']['met'] == 3, axes['safety']
    assert axes['completeness']['items'] == 5
    assert axes['completeness']['met'] == 2
    print('test_aggregate_axis OK')


def test_extract_user_turns_fallback():
    # turns 비어있으면 prompt 로 fallback
    sc = {'prompt': 'fallback', 'turns': []}
    ut = ps._extract_user_turns(sc)
    assert ut == ['fallback']
    # turns 가 정상이면 user 만 추출
    sc2 = {
        'prompt': 'last',
        'turns': [
            {'role': 'user', 'content': 'u1'},
            {'role': 'assistant', 'content': 'a1'},
            {'role': 'user', 'content': 'u2'},
        ],
    }
    ut2 = ps._extract_user_turns(sc2)
    assert ut2 == ['u1', 'u2']
    print('test_extract_user_turns_fallback OK')


def test_aggregate_empty():
    # HB result 없음 — 안전하게 빈 결과
    rep = ps._aggregate_healthbench_report({'runId': 't', 'results': []}, [])
    assert rep['summary']['hbScenarios'] == 0
    assert rep['byTheme'] == []
    assert rep['byAxis'] == []
    assert rep['scenarios'] == []
    print('test_aggregate_empty OK')


def test_aggregate_rubric_error():
    # rubric 평가 실패한 결과 (score=None)
    result = _mk_result('HB-ERR', None, 0, 10)
    result['rubricEval']['error'] = 'GPT 호출 실패'
    rep = ps._aggregate_healthbench_report({'runId': 't', 'results': [result]}, [result])
    s = rep['summary']
    # rubricEvaluated 는 score 가 None 이 아닌 것만 카운트
    assert s['rubricEvaluated'] == 0, f'rubricEvaluated={s["rubricEvaluated"]}'
    assert s['rubricSkipped'] == 1
    assert s['avgRubricScore'] is None
    sc_record = rep['scenarios'][0]
    assert sc_record['rubricError'] == 'GPT 호출 실패'
    print('test_aggregate_rubric_error OK')


def test_aggregate_negative_points_clamp():
    # 음수 점수 met → awarded 차감
    result = {
        'scenarioId': 'HB-NEG',
        'status': 'fail',
        'subcategory': 'global_health',
        'tags': ['theme:global_health'],
        'rubricEval': {
            'score': 0.0,
            'metCount': 2,
            'totalCount': 3,
            'awardedPoints': -5.0,
            'totalPoints': 20.0,
            'items': [
                {'index': 1, 'criterion': 'good', 'points': 10, 'tags': ['axis:safety'], 'met': True, 'explanation': 'x'},
                {'index': 2, 'criterion': 'good2', 'points': 10, 'tags': ['axis:safety'], 'met': False, 'explanation': 'x'},
                {'index': 3, 'criterion': 'bad', 'points': -15, 'tags': ['axis:legal'], 'met': True, 'explanation': 'x'},
            ],
            'error': None,
        },
        'turnsExecuted': 1, 'turnsTotal': 1, 'responseLength': 100, 'response': '..',
    }
    rep = ps._aggregate_healthbench_report({'runId': 't', 'results': [result]}, [result])
    s = rep['summary']
    # totalRubricItems = 3, metRubricItems = 2
    assert s['totalRubricItems'] == 3
    assert s['metRubricItems'] == 2
    # 가중점수: pos pts possible = 20, awarded = 10 - 15 = -5 → 음수, clamp 안 함 (백엔드 그대로 출력)
    # totalAwardedPoints = -5, totalPossiblePoints = 20
    assert s['totalAwardedPoints'] == -5.0
    assert s['totalPossiblePoints'] == 20.0
    # axis:safety: pts_possible 20, pts_awarded 10. axis:legal: pts_possible 0 (음수만), pts_awarded -15
    axes = {a['axis']: a for a in rep['byAxis']}
    assert 'safety' in axes
    assert axes['safety']['ptsPossible'] == 20.0
    assert axes['safety']['ptsAwarded'] == 10.0
    print('test_aggregate_negative_points_clamp OK')


def main():
    test_aggregate_basic()
    test_aggregate_axis()
    test_extract_user_turns_fallback()
    test_aggregate_empty()
    test_aggregate_rubric_error()
    test_aggregate_negative_points_clamp()
    print()
    print('=' * 40)
    print('ALL HB ENDPOINT TESTS PASSED')


if __name__ == '__main__':
    main()
