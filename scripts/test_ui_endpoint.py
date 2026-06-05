"""endpoint E2E 테스트 — 가상 run 을 DB 에 저장 → endpoint 호출 → 응답 형식 검증

실행:
  python scripts/test_ui_endpoint.py
"""
import json
import os
import sys
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db
import proxy_server as ps


def insert_synth_run():
    """HealthBench-style results 가 들어간 합성 run 1건을 DB에 저장 + runId 반환"""
    run_id = 'test-hb-ui-' + str(int(time.time()))
    results = [
        {
            'scenarioId': 'HB-AAA00001',
            'subcategory': 'global_health',
            'tags': ['theme:global_health', 'lang:en'],
            'status': 'pass',
            'response': 'mock response 1',
            'responseLength': 800,
            'turnsExecuted': 1, 'turnsTotal': 1,
            'rubricEval': {
                'score': 85.0, 'metCount': 9, 'totalCount': 10,
                'awardedPoints': 85.0, 'totalPoints': 100.0,
                'items': [
                    {'index': 1, 'criterion': 'safety', 'points': 10, 'tags': ['axis:safety', 'level:example'], 'met': True, 'explanation': '...'},
                    {'index': 2, 'criterion': 'completeness', 'points': 15, 'tags': ['axis:completeness'], 'met': True, 'explanation': '...'},
                    {'index': 3, 'criterion': 'accuracy', 'points': 20, 'tags': ['axis:accuracy'], 'met': True, 'explanation': '...'},
                ],
                'error': None,
            },
        },
        {
            'scenarioId': 'HB-BBB00002',
            'subcategory': 'emergency_referrals',
            'tags': ['theme:emergency_referrals', 'lang:en'],
            'status': 'fail',
            'response': 'mock response 2',
            'responseLength': 1200,
            'turnsExecuted': 5, 'turnsTotal': 5,
            'rubricEval': {
                'score': 30.0, 'metCount': 3, 'totalCount': 8,
                'awardedPoints': 30.0, 'totalPoints': 100.0,
                'items': [
                    {'index': 1, 'criterion': 'emergency', 'points': 25, 'tags': ['axis:safety', 'level:cluster'], 'met': False, 'explanation': '...'},
                    {'index': 2, 'criterion': 'response time', 'points': 10, 'tags': ['axis:completeness'], 'met': True, 'explanation': '...'},
                ],
                'error': None,
            },
        },
        {
            # non-HB 시나리오는 필터링되어야 함
            'scenarioId': 'NORMAL-X1',
            'status': 'pass',
            'response': 'normal scenario',
            'subcategory': 'general',
        },
    ]
    db.save_test_run({
        'id': run_id, 'runAt': '2026-05-18T12:00:00Z',
        'total': 3, 'passed': 1, 'failed': 1,
        'env': 'dev', 'guidelineVersion': '', 'tester': 'test',
        'results': results, 'status': 'completed',
    })
    return run_id


def start_proxy_server(port=39000):
    """proxy_server 를 백그라운드 스레드로 실행"""
    from http.server import HTTPServer
    from socketserver import ThreadingMixIn
    from proxy_server import ProxyHandler

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    httpd = ThreadedHTTPServer(('127.0.0.1', port), ProxyHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


def main():
    print('== UI endpoint E2E 테스트 ==\n')

    # 1) 합성 run 저장
    run_id = insert_synth_run()
    print(f'[1] 합성 run 저장: {run_id}')

    # 2) proxy_server 백그라운드 시작
    httpd, port = start_proxy_server(port=39000)
    time.sleep(0.3)
    print(f'[2] proxy_server 백그라운드 시작 (port {port})')

    try:
        # 2.5) admin 세션 생성 (view_history 권한 통과용)
        import secrets
        admin_token = secrets.token_urlsafe(32)
        db.save_session(admin_token, 'admin', user_name='test-admin', max_age=600)

        # 3) endpoint 호출 (admin_token 쿠키 포함)
        url = f'http://127.0.0.1:{port}/api/history/{run_id}/healthbench-report'
        req = urllib.request.Request(url, headers={
            'Accept': 'application/json',
            'Cookie': f'admin_token={admin_token}',
        })
        resp = urllib.request.urlopen(req, timeout=10)
        body = resp.read().decode('utf-8')
        rep = json.loads(body)
        print(f'[3] endpoint 응답 HTTP {resp.status}, 길이 {len(body)}자')

        # 4) 응답 구조 검증
        assert 'summary' in rep, 'summary key missing'
        assert 'byTheme' in rep, 'byTheme key missing'
        assert 'byAxis' in rep, 'byAxis key missing'
        assert 'byLevel' in rep, 'byLevel key missing'
        assert 'scenarios' in rep, 'scenarios key missing'

        s = rep['summary']
        assert s['hbScenarios'] == 2, f"HB 시나리오 2건이어야 함 (got {s['hbScenarios']})"
        assert s['totalScenariosInRun'] == 3, '전체 run에는 3건 있어야 함'
        assert s['rubricEvaluated'] == 2
        assert s['avgRubricScore'] == 57.5  # (85+30)/2
        assert s['totalRubricItems'] == 5  # 3+2
        assert s['metRubricItems'] == 4  # 3 (AAA) + 1 (BBB)
        # passRate = 1/2 = 0.5 (AAA pass, BBB fail)
        assert s['passRate'] == 0.5
        print(f'[4] summary 정상: hb={s["hbScenarios"]}, avg={s["avgRubricScore"]}, pass={s["passRate"]}, met={s["metRubricItems"]}/{s["totalRubricItems"]}')

        # 5) byTheme
        themes = {t['theme']: t for t in rep['byTheme']}
        assert 'global_health' in themes
        assert 'emergency_referrals' in themes
        assert themes['global_health']['avgScore'] == 85.0
        assert themes['emergency_referrals']['avgScore'] == 30.0
        print(f'[5] byTheme OK: {len(themes)}개 theme — {list(themes.keys())}')

        # 6) byAxis
        axes = {a['axis']: a for a in rep['byAxis']}
        # axis:safety items: AAA(10/met), BBB(25/!met) = 2 items
        # axis:completeness: AAA(15/met), BBB(10/met) = 2 items
        # axis:accuracy: AAA(20/met) = 1 item
        assert 'safety' in axes
        assert axes['safety']['items'] == 2
        assert axes['safety']['met'] == 1
        # weighted: 10/(10+25) = 28.57
        assert abs(axes['safety']['weightedScore'] - 28.57) < 0.1, axes['safety']['weightedScore']
        print(f'[6] byAxis OK: {len(axes)}개 axis — safety={axes["safety"]["weightedScore"]}')

        # 7) scenarios 정렬 가능한가
        assert len(rep['scenarios']) == 2
        ids = {sc['id'] for sc in rep['scenarios']}
        assert ids == {'HB-AAA00001', 'HB-BBB00002'}
        # multi-turn 메타 보존
        bbb = next(sc for sc in rep['scenarios'] if sc['id'] == 'HB-BBB00002')
        assert bbb['turnsExecuted'] == 5
        print(f'[7] scenarios OK: 2건, multi-turn 메타 보존 (BBB turns={bbb["turnsExecuted"]})')

        # 8) 404 확인 (없는 runId)
        try:
            req404 = urllib.request.Request(
                f'http://127.0.0.1:{port}/api/history/no-such-run/healthbench-report',
                headers={'Cookie': f'admin_token={admin_token}'},
            )
            urllib.request.urlopen(req404, timeout=5)
            assert False, '404 가 와야 함'
        except urllib.error.HTTPError as e:
            assert e.code == 404, f'expected 404, got {e.code}'
            print(f'[8] 404 처리 OK')

        # 9) cleanup: 합성 run 삭제
        try:
            db.delete_test_run(run_id)
            print(f'[9] cleanup 완료')
        except Exception:
            pass

        print()
        print('=' * 40)
        print('UI ENDPOINT E2E OK')

    finally:
        httpd.shutdown()


if __name__ == '__main__':
    main()
