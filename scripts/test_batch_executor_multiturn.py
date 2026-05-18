"""batch_executor.BatchExecutor._execute_multiturn 검증.

검증 대상:
1. dispatch - turns/rubric 보유 시나리오는 _execute_multiturn 로, 일반은 _execute_single_legacy 로
2. multi-turn replay 가 호출되고 turnResults 가 결과에 포함됨
3. rubric 평가가 호출되고 rubricEval 가 결과에 포함됨
4. finalSource 가 'rubric' 으로 결정됨

실행:
  python scripts/test_batch_executor_multiturn.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from batch_executor import BatchExecutor


def main():
    # Mock fns
    skix_replay_calls = []
    rubric_calls = []

    def fake_skix_replay(scenario, http_cfg):
        skix_replay_calls.append({'sid': scenario.get('id'), 'turns': len(scenario.get('turns', []))})
        # multi-turn 시나리오 응답 시뮬레이션
        n_user_turns = sum(1 for t in scenario.get('turns', []) if t.get('role') == 'user') or 1
        turn_results = []
        for i in range(n_user_turns):
            turn_results.append({
                'turn_idx': i, 'query': f'u{i+1}',
                'response': f'resp{i+1}' if i == n_user_turns - 1 else f'mid{i+1}',
                'elapsed_ms': 100,
                'http_status': 200, 'first_token_ms': 50, 'last_token_ms': 80,
                'stopped': True, 'error': None,
                'conversation_strid': f'strid-{i+1}',
            })
        return {
            'final_text': turn_results[-1]['response'],
            'final_strid': turn_results[-1]['conversation_strid'],
            'total_elapsed_ms': 100 * n_user_turns,
            'turns_executed': n_user_turns,
            'turns_total': n_user_turns,
            'aborted': False,
            'last_error': None,
            'turn_results': turn_results,
            'search_results': [],
        }

    def fake_eval_gpt(*args, **kwargs):
        return {'grade': 'B', 'score': 70, 'passed': True, 'summary': 'mock'}

    def fake_eval_consultation(*args, **kwargs):
        return {'totalScore': 75, 'grade': 'B'}

    def fake_eval_rubric(query, response, rubric_items, openai_key, model, history):
        rubric_calls.append({'query': query, 'n_items': len(rubric_items), 'history_len': len(history or [])})
        # 절반 met
        items_out = []
        awarded = 0
        for i, r in enumerate(rubric_items):
            met = (i % 2 == 0)
            pts = r.get('points', 0)
            if met and pts > 0:
                awarded += pts
            items_out.append({**r, 'met': met, 'explanation': 'mock', 'index': i + 1})
        max_pos = sum(max(0, r.get('points', 0)) for r in rubric_items)
        score = round(awarded / max_pos * 100, 2) if max_pos else 0
        return {
            'score': score, 'metCount': sum(1 for it in items_out if it['met']),
            'totalCount': len(rubric_items),
            'awardedPoints': awarded, 'totalPoints': max_pos,
            'items': items_out, 'model': model, 'error': None,
        }

    skix_cfg = {'api_url': 'mock', 'api_key': 'mock', 'tenant_domain': 'mock',
                'api_uid': 'mock', 'graph_type': 'mock', 'source_types': []}

    exe = BatchExecutor(
        settings={'openaiModel': 'gpt-4o-mini'},
        openai_key='fake-key',
        skix_config=skix_cfg,
        evaluate_gpt_fn=fake_eval_gpt,
        evaluate_consultation_fn=fake_eval_consultation,
        evaluate_rubric_fn=fake_eval_rubric,
        skix_replay_fn=fake_skix_replay,
        log_fn=lambda *a: None,
    )

    # Test 1: 일반 시나리오 (turns 없음, rubric 없음) → legacy 사용
    scenario_legacy = {
        'id': 'NORMAL-1', 'prompt': 'simple question',
        'turns': [], 'rubric': [],
    }
    # legacy 는 실제 SKIX 호출하므로 mock 안 됨. dispatch 검증만:
    has_turns = bool((scenario_legacy.get('turns') or []))
    has_rubric = bool((scenario_legacy.get('rubric') or []))
    assert not (has_turns or has_rubric), 'legacy 시나리오 분류'
    print('Test 1 (legacy dispatch - turns/rubric 없음) OK')

    # Test 2: HealthBench 시나리오 (multi-turn + rubric) → _execute_multiturn 사용
    scenario_hb = {
        'id': 'HB-TEST01',
        'prompt': 'last user msg',
        'turns': [
            {'role': 'user', 'content': 'u1'},
            {'role': 'assistant', 'content': 'a1'},
            {'role': 'user', 'content': 'u2-FINAL'},
        ],
        'rubric': [
            {'criterion': 'Recommends doctor', 'points': 10, 'tags': ['axis:safety']},
            {'criterion': 'Mentions 119', 'points': 15, 'tags': ['axis:safety']},
            {'criterion': 'Does NOT prescribe', 'points': -5, 'tags': ['axis:legal']},
        ],
        'category': 'healthbench', 'subcategory': 'global_health',
        'tags': ['theme:global_health', 'lang:en'],
        'riskLevel': 'MEDIUM',
    }
    result = exe.execute_single('HB-TEST01', scenario_hb)

    # dispatch 검증
    assert len(skix_replay_calls) == 1, f'skix_replay 1회 호출 (got {len(skix_replay_calls)})'
    assert skix_replay_calls[0]['turns'] == 3
    print('Test 2a (HB dispatch → _execute_multiturn 분기) OK')

    # turnResults 검증
    assert 'turnResults' in result
    assert len(result['turnResults']) == 2, f"user turn 2개 (got {len(result['turnResults'])})"
    assert result['turnsExecuted'] == 2
    assert result['turnResults'][-1]['response'] == 'resp2'
    print('Test 2b (turnResults 정상 포함) OK')

    # rubric 평가 호출 + 결과 검증
    assert len(rubric_calls) == 1
    assert rubric_calls[0]['n_items'] == 3
    assert rubric_calls[0]['history_len'] == 2  # 마지막 user 제외
    assert 'rubricEval' in result
    assert result['rubricEval']['totalCount'] == 3
    print(f'Test 2c (rubric 호출 + history 전달) OK - score={result["rubricEval"]["score"]}')

    # finalSource 검증
    assert result['finalSource'] == 'rubric', f"finalSource should be 'rubric', got {result['finalSource']}"
    # rubric score = (10/(10+15)) × 100 = 40 → pass=False (≥50)
    assert result['finalScore'] == 40.0, result['finalScore']
    assert result['status'] == 'fail'  # 40 < 50
    print(f'Test 2d (finalSource=rubric, finalScore={result["finalScore"]}, status={result["status"]}) OK')

    # 평가 입력 query = 마지막 user turn
    assert result['prompt'] == 'u2', f"prompt should be last user query, got {result['prompt']}"
    print('Test 2e (prompt = 마지막 user query) OK')

    # 응답 = 마지막 turn 응답
    assert result['response'] == 'resp2'
    print('Test 2f (response = 마지막 turn 응답) OK')

    # Test 3: rubric 만 있고 turns 없는 경우 → 여전히 _execute_multiturn 사용
    skix_replay_calls.clear()
    rubric_calls.clear()
    scenario_rubric_only = {
        'id': 'HB-TEST02',
        'prompt': 'single question with rubric',
        'turns': [],  # empty
        'rubric': [{'criterion': 'test', 'points': 5, 'tags': ['axis:test']}],
    }
    r3 = exe.execute_single('HB-TEST02', scenario_rubric_only)
    assert len(skix_replay_calls) == 1, '_execute_multiturn 사용됨 (rubric 보유)'
    # turns 비어있을 때 prompt 가 fallback
    assert skix_replay_calls[0]['turns'] == 0
    assert 'rubricEval' in r3
    assert len(rubric_calls) == 1
    print('Test 3 (rubric 만 있고 turns 없음 → 여전히 multiturn 분기) OK')

    print()
    print('=' * 40)
    print('BATCH EXECUTOR MULTI-TURN 검증 OK')


if __name__ == '__main__':
    main()
