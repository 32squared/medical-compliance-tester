"""_aggregate_healthbench_report 단위 테스트 — synthetic 결과 데이터로 검증

실행:
  python scripts/test_hb_report.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import proxy_server as ps


def make_result(sid, theme, score, items, status='pass', turns=1):
    """rubricEval 결과 한 건을 합성"""
    rubric_eval = {
        'score': score,
        'metCount': sum(1 for it in items if it['met']),
        'totalCount': len(items),
        'awardedPoints': sum(it['points'] for it in items if it['met']),
        'totalPoints': sum(max(0, it['points']) for it in items),
        'items': items,
        'error': None,
    }
    return {
        'scenarioId': sid,
        'subcategory': theme,
        'tags': [f'theme:{theme}', 'lang:en'],
        'status': status,
        'response': 'x' * 500,
        'responseLength': 500,
        'rubricEval': rubric_eval,
        'turnsExecuted': turns,
        'turnsTotal': turns,
    }


def run():
    # synthetic items factory
    def items(*specs):
        out = []
        for i, (pts, met, *tags) in enumerate(specs):
            out.append({
                'index': i + 1,
                'criterion': f'crit{i+1}',
                'points': pts,
                'tags': list(tags),
                'met': met,
                'explanation': '...',
            })
        return out

    # 5건: global_health 3건 (avg 80), emergency_referrals 2건 (avg 50)
    results = [
        make_result('HB-AAA', 'global_health', 100.0, items(
            (10, True, 'axis:safety', 'level:example'),
            (10, True, 'axis:completeness', 'level:example'),
        )),
        make_result('HB-BBB', 'global_health', 80.0, items(
            (10, True, 'axis:safety', 'level:example'),
            (10, False, 'axis:completeness', 'level:example'),
            (-5, False, 'axis:safety', 'level:example'),  # negative not met → ok
        )),
        make_result('HB-CCC', 'global_health', 60.0, items(
            (10, True, 'axis:completeness'),
            (10, False, 'axis:safety'),
        ), status='fail'),
        make_result('HB-DDD', 'emergency_referrals', 75.0, items(
            (20, True, 'axis:safety'),
            (10, False, 'axis:completeness'),
        ), turns=3),
        make_result('HB-EEE', 'emergency_referrals', 25.0, items(
            (20, False, 'axis:safety'),
            (10, False, 'axis:completeness'),
        ), status='fail', turns=5),
    ]

    run = {
        'runId': 'test-run-1',
        'env': 'dev',
        'startedAt': '2026-05-18T12:00:00Z',
        'results': results,
    }

    report = ps._aggregate_healthbench_report(run, results)

    # ── summary ──
    s = report['summary']
    assert s['hbScenarios'] == 5, s
    assert s['rubricEvaluated'] == 5, s
    # AAA: 2 items, BBB: 3 items, CCC: 2 items, DDD: 2 items, EEE: 2 items → 11
    assert s['totalRubricItems'] == 11, f"expected 11, got {s['totalRubricItems']}"
    # met: AAA 2, BBB 1, CCC 1, DDD 1, EEE 0 → 5
    assert s['metRubricItems'] == 5, s['metRubricItems']
    # avgRubricScore: (100+80+60+75+25)/5 = 68.0
    assert s['avgRubricScore'] == 68.0, s['avgRubricScore']
    # passRate: AAA(100) + BBB(80) + CCC(60) + DDD(75) → 4 pass / 5 = 0.8 (EEE=25 fail)
    assert s['passRate'] == 0.8, s['passRate']
    print(f'Test 1 (summary) OK — avg={s["avgRubricScore"]}, pass={s["passRate"]}, met={s["metRubricItems"]}/{s["totalRubricItems"]}')

    # ── by_theme ──
    by_theme = {t['theme']: t for t in report['byTheme']}
    assert 'global_health' in by_theme
    assert 'emergency_referrals' in by_theme
    gh = by_theme['global_health']
    assert gh['count'] == 3
    assert gh['avgScore'] == 80.0, gh['avgScore']  # (100+80+60)/3
    # global_health 3건: 100/80/60 모두 >= 50 → 3 pass
    assert gh['passed'] == 3, f"global_health passed should be 3, got {gh['passed']}"
    er = by_theme['emergency_referrals']
    assert er['count'] == 2
    assert er['avgScore'] == 50.0, er['avgScore']  # (75+25)/2
    assert er['passed'] == 1, er['passed']  # DDD(75) pass, EEE(25) fail
    print(f'Test 2 (by_theme) OK — global_health avg={gh["avgScore"]}, emergency avg={er["avgScore"]}')

    # ── by_axis ──
    by_axis = {a['axis']: a for a in report['byAxis']}
    assert 'safety' in by_axis
    assert 'completeness' in by_axis
    # safety items (axis:safety 태그): AAA(+10/met), BBB(+10/met), BBB(-5/!met),
    #   CCC(+10/!met), DDD(+20/met), EEE(+20/!met) = 6개 항목
    safety = by_axis['safety']
    assert safety['items'] == 6, safety['items']
    assert safety['met'] == 3, safety['met']
    # ptsPossible = 10+10+10+20+20 = 70 (음수 -5는 max(0,pts)로 제외)
    assert safety['ptsPossible'] == 70, safety['ptsPossible']
    # ptsAwarded = 10+10+20 = 40 (met인 양수만)
    assert safety['ptsAwarded'] == 40, safety['ptsAwarded']
    # weightedScore = 40/70 ≈ 57.14
    assert safety['weightedScore'] == 57.14, safety['weightedScore']
    print(f'Test 3 (by_axis safety) OK — items={safety["items"]} met={safety["met"]} weighted={safety["weightedScore"]}')

    # ── by_level ──
    by_level = {l['level']: l for l in report['byLevel']}
    # 'level:example' tagged: AAA(2), BBB(3) = 5 items
    if 'example' in by_level:
        assert by_level['example']['items'] == 5, by_level['example']['items']
        print(f'Test 4 (by_level example) OK — items={by_level["example"]["items"]} met={by_level["example"]["met"]}')

    # ── scenarios 상세 ──
    assert len(report['scenarios']) == 5
    ids = {sc['id'] for sc in report['scenarios']}
    assert ids == {'HB-AAA', 'HB-BBB', 'HB-CCC', 'HB-DDD', 'HB-EEE'}
    ddd = next(sc for sc in report['scenarios'] if sc['id'] == 'HB-DDD')
    assert ddd['turnsExecuted'] == 3
    assert ddd['rubricScore'] == 75.0
    print(f'Test 5 (scenarios list) OK — 5건 모두 포함, multi-turn 메타 보존')

    # ── 빈 hb_results 처리 ──
    empty_report = ps._aggregate_healthbench_report({'runId': 'x', 'results': []}, [])
    assert empty_report['summary']['hbScenarios'] == 0
    assert empty_report['summary']['avgRubricScore'] is None
    assert empty_report['byTheme'] == []
    print('Test 6 (빈 hb_results 처리) OK')

    # ── rubricEval=None 시나리오 처리 ──
    res_no_rubric = {
        'scenarioId': 'HB-NORUBRIC',
        'subcategory': 'global_health',
        'tags': ['theme:global_health'],
        'status': 'error',
        'response': '',
        'rubricEval': None,
    }
    r2 = ps._aggregate_healthbench_report({'runId': 'x', 'results': [res_no_rubric]}, [res_no_rubric])
    assert r2['summary']['hbScenarios'] == 1
    assert r2['summary']['rubricEvaluated'] == 0
    assert r2['summary']['rubricSkipped'] == 1
    print('Test 7 (rubricEval=None 시나리오 → skipped 집계) OK')

    print()
    print('=' * 40)
    print('ALL HB REPORT TESTS PASSED')


if __name__ == '__main__':
    run()
