"""multi-turn replay 단위 테스트 — _skix_post_one 을 mock 으로 교체

실행:
  python scripts/test_skix_replay.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import proxy_server as ps


def run():
    call_log = []

    def fake_post(query, conversation_strid, *args, **kwargs):
        call_log.append({'query': query, 'strid_in': conversation_strid})
        n = len(call_log)
        return {
            'text': f'[response to turn{n}]',
            'conversation_strid': f'strid-after-{n}',
            'elapsed_ms': 100 * n,
            'http_status': 200,
            'first_token_ms': 50,
            'last_token_ms': 80,
            'stopped': True,
            'search_results': [],
            'error': None,
        }
    ps._skix_post_one = fake_post

    # Test 1: 단일 turn (기존 시나리오)
    scenario = {'prompt': 'single question', 'turns': []}
    res = ps._skix_replay(scenario, {
        'api_url': '', 'graph_type': '', 'api_key': '',
        'tenant_domain': '', 'api_uid': '', 'source_types': []
    })
    assert res['turns_executed'] == 1
    assert res['final_text'] == '[response to turn1]'
    assert res['final_strid'] == 'strid-after-1'
    assert call_log[0]['query'] == 'single question'
    assert call_log[0]['strid_in'] is None
    print('Test 1 (single turn) OK')

    # Test 2: HealthBench multi-turn
    call_log.clear()
    scenario = {
        'prompt': 'last user msg',
        'turns': [
            {'role': 'user', 'content': 'user1'},
            {'role': 'assistant', 'content': 'asst1_REFERENCE'},
            {'role': 'user', 'content': 'user2'},
            {'role': 'assistant', 'content': 'asst2_REFERENCE'},
            {'role': 'user', 'content': 'user3-FINAL'},
        ]
    }
    res = ps._skix_replay(scenario, {
        'api_url': '', 'graph_type': '', 'api_key': '',
        'tenant_domain': '', 'api_uid': '', 'source_types': []
    })
    assert res['turns_executed'] == 3
    assert res['turns_total'] == 3
    assert res['final_text'] == '[response to turn3]'
    assert res['final_strid'] == 'strid-after-3'
    assert call_log[0]['strid_in'] is None
    assert call_log[1]['strid_in'] == 'strid-after-1'
    assert call_log[2]['strid_in'] == 'strid-after-2'
    assert [c['query'] for c in call_log] == ['user1', 'user2', 'user3-FINAL']
    assert not res['aborted']
    print('Test 2 (multi-turn 3 user turns + strid chaining) OK')

    # Test 3: 중간 turn 실패 → aborted
    call_log.clear()
    turn_idx = [0]

    def fake_post_fail_mid(query, conversation_strid, *args, **kwargs):
        turn_idx[0] += 1
        call_log.append({'query': query})
        if turn_idx[0] == 2:
            return {
                'text': '', 'conversation_strid': None, 'elapsed_ms': 500,
                'http_status': 504, 'first_token_ms': None, 'last_token_ms': None,
                'stopped': False, 'search_results': [], 'error': 'timeout'
            }
        return {
            'text': f'resp{turn_idx[0]}', 'conversation_strid': f's{turn_idx[0]}',
            'elapsed_ms': 100, 'http_status': 200, 'first_token_ms': 50,
            'last_token_ms': 80, 'stopped': True, 'search_results': [], 'error': None
        }
    ps._skix_post_one = fake_post_fail_mid
    res = ps._skix_replay(scenario, {
        'api_url': '', 'graph_type': '', 'api_key': '',
        'tenant_domain': '', 'api_uid': '', 'source_types': []
    })
    assert res['aborted']
    assert res['turns_executed'] == 2
    assert res['last_error'] == 'timeout'
    print('Test 3 (mid-turn failure abort) OK')

    # Test 4: 마지막 turn 실패 → not aborted
    call_log.clear()
    turn_idx[0] = 0

    def fake_post_fail_last(query, conversation_strid, *args, **kwargs):
        turn_idx[0] += 1
        call_log.append({'query': query})
        if turn_idx[0] == 3:
            return {
                'text': '', 'conversation_strid': None, 'elapsed_ms': 500,
                'http_status': 500, 'first_token_ms': None, 'last_token_ms': None,
                'stopped': False, 'search_results': [], 'error': '500 error'
            }
        return {
            'text': f'resp{turn_idx[0]}', 'conversation_strid': f's{turn_idx[0]}',
            'elapsed_ms': 100, 'http_status': 200, 'first_token_ms': 50,
            'last_token_ms': 80, 'stopped': True, 'search_results': [], 'error': None
        }
    ps._skix_post_one = fake_post_fail_last
    res = ps._skix_replay(scenario, {
        'api_url': '', 'graph_type': '', 'api_key': '',
        'tenant_domain': '', 'api_uid': '', 'source_types': []
    })
    assert not res['aborted']
    assert res['turns_executed'] == 3
    assert res['last_error'] == '500 error'
    assert res['final_text'] == ''
    print('Test 4 (last-turn failure not aborted) OK')

    # Test 5: 실제 HealthBench 시나리오 1건으로 _extract_user_turns 검증
    import db
    all_s = db.get_scenarios()['scenarios']
    hb_multi = [s for s in all_s if s['id'].startswith('HB-') and len(s.get('turns', [])) >= 3]
    if hb_multi:
        s = hb_multi[0]
        user_turns = ps._extract_user_turns(s)
        all_user_msgs = [t['content'] for t in s['turns'] if t['role'] == 'user']
        assert user_turns == all_user_msgs, 'extracted user turns 불일치'
        print(f'Test 5 (real HB scenario {s["id"]}, {len(s["turns"])} turns → {len(user_turns)} user) OK')
    else:
        print('Test 5 SKIPPED (no multi-turn HB scenarios in DB)')

    print()
    print('=' * 40)
    print('ALL TESTS PASSED')


if __name__ == '__main__':
    run()
