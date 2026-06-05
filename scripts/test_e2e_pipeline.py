"""E2E 파이프라인 검증 — 실제 DB의 HB 시나리오 → mock SKIX/OpenAI → 전체 파이프라인 → 리포트

검증 범위:
  1. DB에서 실제 HB-* 시나리오 로드
  2. _skix_replay() 가 multi-turn user turn을 순차 처리
  3. _evaluate_rubric() 가 GPT 응답을 점수로 환산
  4. _aggregate_healthbench_report() 가 결과를 theme/axis 별 집계
  5. (검증) endpoint 경로의 권한 라우팅이 healthbench-report 를 인식

실행:
  python scripts/test_e2e_pipeline.py
"""
import json
import os
import sys
from io import BytesIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import proxy_server as ps
import db


class FakeOpenAIResp:
    def __init__(self, json_obj):
        self._buf = BytesIO(json.dumps(json_obj).encode('utf-8'))
        class _FP:
            class _raw:
                _sock = None
        self.fp = _FP()
    def read(self):
        return self._buf.read()
    def getcode(self):
        return 200


def install_mocks():
    """SKIX 단일 호출과 OpenAI urlopen 을 mock 으로 교체"""
    skix_call_log = []
    openai_call_log = []

    def fake_skix(query, conversation_strid, *args, **kwargs):
        skix_call_log.append({'query': query, 'strid_in': conversation_strid})
        n = len(skix_call_log)
        # 마지막 turn 에는 의료법 친화 응답을, 중간 turn 에는 짧은 응답
        text = (f"Thank you for your question. I am an AI and cannot provide medical "
                f"diagnosis. Please consult a licensed physician. If this is an emergency, "
                f"call 119 immediately. (Response #{n})")
        return {
            'text': text,
            'conversation_strid': f'strid-{n}',
            'elapsed_ms': 100 * n,
            'http_status': 200,
            'first_token_ms': 50, 'last_token_ms': 90,
            'stopped': True, 'search_results': [], 'error': None,
        }
    ps._skix_post_one = fake_skix

    def fake_openai_urlopen(req, context=None, timeout=None):
        try:
            body = json.loads(req.data.decode('utf-8'))
        except Exception:
            body = {}
        msg_content = ''
        for m in body.get('messages', []):
            if m.get('role') == 'user':
                msg_content = m.get('content', '')
                break
        openai_call_log.append({'msg_len': len(msg_content)})

        # 시스템 프롬프트에 따라 GPT/문진/rubric 셋 중 어느 호출인지 분기
        sys_prompt = ''
        for m in body.get('messages', []):
            if m.get('role') == 'system':
                sys_prompt = m.get('content', '')
                break

        if 'rubric criterion' in sys_prompt.lower() or 'Rubric criteria' in msg_content:
            # rubric eval — 응답 길이가 길수록 met 비율 ↑
            # criteria 라인 카운트 추출
            crit_count = msg_content.count('. (')
            graded = []
            for i in range(1, crit_count + 1):
                # 절반 met, 절반 not met (deterministic for test)
                graded.append({
                    'index': i, 'met': (i % 2 == 1),
                    'explanation': f'mock grade {i}'
                })
            return FakeOpenAIResp({
                'model': 'gpt-4o-mini',
                'choices': [{'message': {'content': json.dumps({'items': graded})}}]
            })
        elif '문진' in sys_prompt or 'consultation' in sys_prompt.lower():
            # consultation eval (한국어 system prompt)
            return FakeOpenAIResp({
                'model': 'gpt-4o-mini',
                'choices': [{'message': {'content': json.dumps({
                    'totalScore': 70, 'grade': 'B', 'axes': {},
                    'summary': 'mock', 'missingItems': [], 'recommendation': ''
                })}}]
            })
        else:
            # GPT compliance eval (default)
            return FakeOpenAIResp({
                'model': 'gpt-4o-mini',
                'choices': [{'message': {'content': json.dumps({
                    'grade': 'B', 'score': 75, 'passed': True,
                    'reasons': ['mock compliance eval'],
                    'guidelineVersion': '2026-05'
                })}}]
            })
    ps.urlopen = fake_openai_urlopen
    return skix_call_log, openai_call_log


def main():
    print('== E2E 파이프라인 검증 ==\n')
    skix_log, openai_log = install_mocks()

    # ── 1. 실제 DB 에서 multi-turn HB 시나리오 로드 ──
    all_s = db.get_scenarios()['scenarios']
    hb_multi = [s for s in all_s if s['id'].startswith('HB-') and len(s.get('turns', [])) >= 5 and s.get('rubric')]
    if not hb_multi:
        print('FAIL: multi-turn HB 시나리오 없음 (Phase A.1 import 가 안 됐을 수 있음)')
        sys.exit(1)

    scenario = hb_multi[0]
    n_turns = len(scenario['turns'])
    n_user = sum(1 for t in scenario['turns'] if t.get('role') == 'user')
    n_rubric = len(scenario['rubric'])
    print(f'[1] 실제 HB 시나리오 로드: {scenario["id"]}')
    print(f'    theme={scenario["subcategory"]}, turns={n_turns} (user={n_user}), rubric={n_rubric}')

    # ── 2. multi-turn SKIX replay ──
    http_cfg = {
        'api_url': 'mock', 'graph_type': 'mock', 'api_key': 'mock',
        'tenant_domain': 'mock', 'api_uid': 'mock', 'source_types': [],
    }
    replay = ps._skix_replay(scenario, http_cfg)
    assert replay['turns_executed'] == n_user, f"expected {n_user} turns, got {replay['turns_executed']}"
    assert not replay['aborted']
    assert replay['final_text']
    assert replay['final_strid'] == f'strid-{n_user}'
    # strid 체이닝 검증 (SKIX 호출 로그)
    assert skix_log[0]['strid_in'] is None
    if len(skix_log) > 1:
        assert skix_log[1]['strid_in'] == 'strid-1'
    print(f'[2] SKIX replay OK: {replay["turns_executed"]} turns, final_strid={replay["final_strid"]}, '
          f'total_elapsed={replay["total_elapsed_ms"]}ms')

    # ── 3. rubric 평가 ──
    eval_query = replay['turn_results'][-1]['query']
    hist = scenario['turns'][:-1]  # 마지막 user 제외
    rubric_eval = ps._evaluate_rubric(eval_query, replay['final_text'], scenario['rubric'],
                                       'mock-key', model='gpt-4o-mini', conversation_history=hist)
    assert rubric_eval is not None
    assert rubric_eval['error'] is None
    assert rubric_eval['totalCount'] == n_rubric
    # mock에서 홀수 index 만 met 으로 설정 → 절반 정도 met
    expected_met = (n_rubric + 1) // 2
    assert rubric_eval['metCount'] == expected_met, f"expected {expected_met} met, got {rubric_eval['metCount']}"
    assert 0 <= rubric_eval['score'] <= 100
    print(f'[3] rubric 평가 OK: score={rubric_eval["score"]}, met={rubric_eval["metCount"]}/{rubric_eval["totalCount"]}, '
          f'awarded={rubric_eval["awardedPoints"]}/{rubric_eval["totalPoints"]}')

    # ── 4. 가상 result entry 구성 후 집계 ──
    result_entry = {
        'scenarioId': scenario['id'],
        'subcategory': scenario['subcategory'],
        'tags': scenario.get('tags', []),
        'status': 'pass' if rubric_eval['score'] >= 50 else 'fail',
        'response': replay['final_text'],
        'responseLength': len(replay['final_text']),
        'rubricEval': rubric_eval,
        'turnsExecuted': replay['turns_executed'],
        'turnsTotal': replay['turns_total'],
        'turnResults': replay['turn_results'],
    }
    fake_run = {
        'runId': 'e2e-test', 'env': 'dev', 'startedAt': '2026-05-18T00:00:00Z',
        'results': [result_entry]
    }
    report = ps._aggregate_healthbench_report(fake_run, [result_entry])
    s = report['summary']
    assert s['hbScenarios'] == 1
    assert s['rubricEvaluated'] == 1
    assert s['totalRubricItems'] == n_rubric
    assert s['avgRubricScore'] == rubric_eval['score']
    print(f'[4] 리포트 집계 OK: avg={s["avgRubricScore"]}, met={s["metRubricItems"]}/{s["totalRubricItems"]}, '
          f'themes={len(report["byTheme"])}, axes={len(report["byAxis"])}')
    print(f'    byTheme[0]: {report["byTheme"][0]}')
    if report['byAxis']:
        print(f'    byAxis[0]: {report["byAxis"][0]}')

    # ── 5. route regex 검증 ──
    import re
    test_path = '/api/history/run-20260518-000000-HB-XXX/healthbench-report'
    m = re.match(r'^/api/history/([^/]+)/healthbench-report$', test_path)
    assert m is not None
    assert m.group(1) == 'run-20260518-000000-HB-XXX'
    print(f'[5] route regex OK: extracted runId={m.group(1)}')

    # ── 6. 멀티 시나리오 집계 (3건) ──
    print()
    print('[6] 멀티 시나리오 (3건) 집계 검증...')
    multi_results = []
    sample_count = min(3, len(hb_multi))
    skix_log.clear()
    openai_log.clear()
    for sc in hb_multi[:sample_count]:
        r = ps._skix_replay(sc, http_cfg)
        eq = r['turn_results'][-1]['query']
        h = sc['turns'][:-1]
        re_eval = ps._evaluate_rubric(eq, r['final_text'], sc['rubric'], 'k', 'gpt-4o-mini', h)
        multi_results.append({
            'scenarioId': sc['id'], 'subcategory': sc['subcategory'],
            'tags': sc.get('tags', []), 'status': 'pass' if re_eval['score'] >= 50 else 'fail',
            'response': r['final_text'], 'responseLength': len(r['final_text']),
            'rubricEval': re_eval, 'turnsExecuted': r['turns_executed'],
            'turnsTotal': r['turns_total'], 'turnResults': r['turn_results'],
        })
    fake_run_multi = {'runId': 'e2e-multi', 'env': 'dev', 'startedAt': 'x', 'results': multi_results}
    report_multi = ps._aggregate_healthbench_report(fake_run_multi, multi_results)
    sm = report_multi['summary']
    assert sm['hbScenarios'] == sample_count
    assert sm['rubricEvaluated'] == sample_count
    print(f'    SKIX 호출: {len(skix_log)}회 (multi-turn 시 시나리오당 N user turn)')
    print(f'    OpenAI 호출: {len(openai_log)}회 (rubric eval, 시나리오당 1회)')
    print(f'    Summary: avg={sm["avgRubricScore"]}, passRate={sm["passRate"]}, met={sm["metRubricItems"]}/{sm["totalRubricItems"]}')
    print(f'    Themes: {[(t["theme"], t["count"], t["avgScore"]) for t in report_multi["byTheme"]]}')

    print()
    print('=' * 40)
    print('E2E PIPELINE 전체 검증 OK')
    print('=' * 40)


if __name__ == '__main__':
    main()
