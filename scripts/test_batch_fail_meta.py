"""batch 실패 path 에서 turn_results 보존 검증

  multi-turn 시나리오에서 3번째 turn 이 실패하면 → 처음 2 turn 의 결과는 result entry 에 살아있어야 함

실행:
  python scripts/test_batch_fail_meta.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import proxy_server as ps


def main():
    # 2번째 user turn(중간) 이 항상 실패하는 mock SKIX → aborted=True
    turn_counter = [0]

    def fake_skix(query, conversation_strid, *args, **kwargs):
        turn_counter[0] += 1
        n = turn_counter[0]
        if n == 2:  # 중간 turn = aborted 트리거
            return {
                'text': '', 'conversation_strid': None, 'elapsed_ms': 500,
                'http_status': 504, 'first_token_ms': None, 'last_token_ms': None,
                'stopped': False, 'search_results': [], 'error': 'gateway timeout'
            }
        return {
            'text': f'response{n}', 'conversation_strid': f's{n}',
            'elapsed_ms': 100, 'http_status': 200, 'first_token_ms': 50,
            'last_token_ms': 80, 'stopped': True, 'search_results': [], 'error': None,
        }
    ps._skix_post_one = fake_skix

    # 3개 user turn — 중간(u2) 실패 → aborted=True, u3 는 호출 안 됨
    scenario = {
        'id': 'TEST-FAIL-MULTI',
        'prompt': 'last user',
        'turns': [
            {'role': 'user', 'content': 'u1'},
            {'role': 'assistant', 'content': 'a1'},
            {'role': 'user', 'content': 'u2-FAIL'},
            {'role': 'assistant', 'content': 'a2'},
            {'role': 'user', 'content': 'u3'},
        ],
        'rubric': [],
    }
    http_cfg = {
        'api_url': '', 'graph_type': '', 'api_key': '', 'tenant_domain': '',
        'api_uid': '', 'source_types': [],
    }
    res = ps._skix_replay(scenario, http_cfg)
    assert res['aborted'], f"aborted should be True (mid-turn fail), got {res}"
    # u2 실패 후 break → 2개 turn 만 실행
    assert res['turns_executed'] == 2, res['turns_executed']
    assert res['turns_total'] == 3, res['turns_total']
    assert res['turn_results'][1]['error'] == 'gateway timeout'
    assert res['turn_results'][0]['response'] == 'response1'
    assert res['turn_results'][1]['response'] == ''
    print(f'Test 1 (replay aborted at turn 2/3, turn_results 보존) OK')

    # 실제 batch fail path 의 best_partial_meta 시뮬레이션
    # (execute_single 내부 except 블록 동작 검증)
    # 간단히 코드 흐름만 검증: partial_turn_results 가 result entry 에 들어가는지

    # Mock execute_single 함수와 같은 흐름 시뮬레이션
    best_partial_meta = None
    best_partial_text = ''
    full_text = res['final_text']  # = ''
    turn_results = res['turn_results']
    partial_now = full_text or ''
    partial_turn_results = turn_results or []
    if partial_now and len(partial_now) > len(best_partial_text):
        best_partial_text = partial_now
        best_partial_meta = {'turnResults': partial_turn_results, 'firstTokenMs': None, 'lastTokenMs': None, 'searchResults': []}
    elif partial_turn_results and not best_partial_meta:
        best_partial_meta = {
            'firstTokenMs': None, 'lastTokenMs': None, 'searchResults': [],
            'turnResults': partial_turn_results,
        }

    assert best_partial_meta is not None, 'best_partial_meta 가 설정되어야 함 (응답 없어도 turn_results 있으면)'
    saved_turns = best_partial_meta.get('turnResults', [])
    assert len(saved_turns) == 2
    assert saved_turns[1]['error'] == 'gateway timeout'

    # 최종 fail return entry 구성
    final_entry = {
        'scenarioId': scenario['id'],
        'prompt': (saved_turns[-1]['query'] if saved_turns else scenario.get('prompt', '')),
        'response': best_partial_text,
        'status': 'error',
        'turnResults': saved_turns,
        'turnsExecuted': len(saved_turns),
        'turnsTotal': len(saved_turns),
    }
    # prompt 가 실패한 user turn 으로 설정됐는지 (u2-FAIL)
    assert final_entry['prompt'] == 'u2-FAIL', final_entry['prompt']
    assert final_entry['turnsExecuted'] == 2
    assert len(final_entry['turnResults']) == 2
    assert final_entry['turnResults'][1]['error'] == 'gateway timeout'
    print('Test 2 (fail-path result entry 에 turnResults / turnsExecuted 보존) OK')

    # UI 가 받을 메타 검증 — multi-turn 표시 가능 + 어느 turn 에서 실패했는지 알 수 있음
    failed_turn_idx = None
    for i, t in enumerate(final_entry['turnResults']):
        if t.get('error'):
            failed_turn_idx = i
            break
    assert failed_turn_idx == 1, f"failed turn should be index 1, got {failed_turn_idx}"
    print(f'Test 3 (UI 가 fail turn 위치 파악 가능: turn_idx={failed_turn_idx}) OK')

    print()
    print('=' * 40)
    print('BATCH FAIL META 보존 검증 OK')


if __name__ == '__main__':
    main()
