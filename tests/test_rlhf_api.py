"""
RLHF API 통합 테스트 — DEV 서버 대상
실행: python tests/test_rlhf_api.py [DEV_URL]
기본 URL: https://medical-compliance-tester-dev-cbtevhmzrq-du.a.run.app
"""
import sys
import json
import time
import urllib.request
import urllib.error
import urllib.parse

DEV_URL = sys.argv[1] if len(sys.argv) > 1 else \
    'https://medical-compliance-tester-dev-cbtevhmzrq-du.a.run.app'

PASS = '\033[92m✓\033[0m'
FAIL = '\033[91m✗\033[0m'
WARN = '\033[93m⚠\033[0m'

results = {'pass': 0, 'fail': 0, 'skip': 0}

def req(method, path, body=None, headers=None, token=None):
    url = DEV_URL + path
    data = json.dumps(body).encode() if body else None
    h = {'Content-Type': 'application/json', **(headers or {})}
    if token:
        h['Cookie'] = f'tester_token={token}'
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as res:
            raw = res.read().decode()
            return res.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {'error': raw[:200]}

def check(name, condition, info=''):
    if condition:
        print(f'  {PASS} {name}')
        results['pass'] += 1
    else:
        print(f'  {FAIL} {name}' + (f'  [{info}]' if info else ''))
        results['fail'] += 1

def skip(name, reason):
    print(f'  {WARN} {name} (SKIP: {reason})')
    results['skip'] += 1

print(f'\n{"="*55}')
print(f'  RLHF API 통합 테스트')
print(f'  대상: {DEV_URL}')
print(f'{"="*55}\n')

# ──────────────────────────────────────────────────────
# 0. 서버 헬스 체크
# ──────────────────────────────────────────────────────
print('[0] 서버 헬스 체크')
status, body = req('GET', '/health')
check('GET /health → 200', status == 200, f'status={status}')
check('status: ok', body.get('status') == 'ok', str(body))

# ──────────────────────────────────────────────────────
# 1. 피드백 저장 (POST /api/feedback)
# ──────────────────────────────────────────────────────
print('\n[1] 피드백 저장 — POST /api/feedback')

fb_payload = {
    'message_id': f'test-msg-{int(time.time())}',
    'conversation_id': f'test-conv-{int(time.time())}',
    'rating': 5,
    'labels': ['우수답변'],
    'feedback_note': 'API 통합 테스트 피드백',
    'original_query': '두통이 있어요',
    'full_response': '충분한 휴식을 취하시고 의사와 상담하세요',
}
status, body = req('POST', '/api/feedback', fb_payload)
check('POST /api/feedback → 201', status == 201, f'status={status}, body={body}')
check('응답에 id 포함', 'id' in body, str(body))
saved_fb_id = body.get('id')

# 나쁜 피드백 (수정된 응답 포함)
fb_bad_payload = {
    'message_id': f'test-msg-bad-{int(time.time())}',
    'conversation_id': f'test-conv-{int(time.time())}',
    'rating': 1,
    'labels': ['진단언급', '처방시도'],
    'corrected_response': '저는 의료 정보를 제공할 수 없습니다. 전문의와 상담하세요.',
    'feedback_note': '진단 언급 있음',
}
status2, body2 = req('POST', '/api/feedback', fb_bad_payload)
check('나쁜 피드백 저장 → 201', status2 == 201, f'status={status2}')

# ──────────────────────────────────────────────────────
# 2. 피드백 목록 조회 (GET /api/feedback)
# ──────────────────────────────────────────────────────
print('\n[2] 피드백 목록 조회 — GET /api/feedback')

status, body = req('GET', '/api/feedback?limit=20')
check('GET /api/feedback → 200', status == 200, f'status={status}')
check('응답이 배열', isinstance(body, list), type(body).__name__)
if isinstance(body, list) and body:
    first = body[0]
    check('evaluator_id 필드 존재', 'evaluator_id' in first, str(list(first.keys())[:5]))
    check('rating 필드 존재', 'rating' in first)
    check('created_at 필드 존재', 'created_at' in first)

# 특정 conversation 필터
conv_id = fb_payload['conversation_id']
status, body = req('GET', f'/api/feedback?conversation_id={conv_id}')
check(f'conversation_id 필터 → 200', status == 200)
check('저장한 피드백 포함', isinstance(body, list) and len(body) > 0, f'count={len(body) if isinstance(body,list) else body}')

# ──────────────────────────────────────────────────────
# 3. 피드백 통계 (GET /api/feedback/stats)
# ──────────────────────────────────────────────────────
print('\n[3] 피드백 통계 — GET /api/feedback/stats')

status, body = req('GET', '/api/feedback/stats?days=30')
check('GET /api/feedback/stats → 200', status == 200, f'status={status}')
check('total 필드 존재', 'total' in body, str(body))
check('total >= 1', body.get('total', 0) >= 1, f"total={body.get('total')}")

# ──────────────────────────────────────────────────────
# 4. 선호도 쌍 저장 (POST /api/rlhf/pairs)
# ──────────────────────────────────────────────────────
print('\n[4] 선호도 쌍 저장 — POST /api/rlhf/pairs')

pair_payload = {
    'prompt': '두통이 심해요, 어떻게 해야 하나요?',
    'response_chosen': '충분한 휴식과 수분 섭취를 권장하며, 증상이 지속되면 신경과 전문의 상담을 권합니다.',
    'response_rejected': '타이레놀 500mg을 드세요. 하루 3번 복용하시면 됩니다.',
    'label_source': 'human',
    'chosen_score': 0.88,
    'rejected_score': 0.12,
}
status, body = req('POST', '/api/rlhf/pairs', pair_payload)
if status == 403:
    skip('POST /api/rlhf/pairs', 'admin 권한 필요 (예상된 403)')
    saved_pair_id = None
else:
    check('POST /api/rlhf/pairs → 201', status == 201, f'status={status}, body={body}')
    check('응답에 id 포함', 'id' in body, str(body))
    saved_pair_id = body.get('id')

# ──────────────────────────────────────────────────────
# 5. 선호도 쌍 목록 (GET /api/rlhf/pairs)
# ──────────────────────────────────────────────────────
print('\n[5] 선호도 쌍 목록 — GET /api/rlhf/pairs')

status, body = req('GET', '/api/rlhf/pairs?limit=20')
check('GET /api/rlhf/pairs → 200', status == 200, f'status={status}')
check('응답이 배열', isinstance(body, list), type(body).__name__)
if isinstance(body, list) and body:
    first = body[0]
    check('prompt 필드 존재', 'prompt' in first)
    check('response_chosen 필드 존재', 'response_chosen' in first)
    check('response_rejected 필드 존재', 'response_rejected' in first)

# ──────────────────────────────────────────────────────
# 6. RLHF 통계 — admin 전용
# ──────────────────────────────────────────────────────
print('\n[6] RLHF 통계 — GET /api/rlhf/stats (admin 전용)')

status, body = req('GET', '/api/rlhf/stats')
if status == 403:
    skip('GET /api/rlhf/stats', 'admin 권한 필요 (예상된 403)')
elif status == 200:
    check('GET /api/rlhf/stats → 200', True)
    check('total_feedback 필드', 'total_feedback' in body, str(body))
    check('total_pairs 필드', 'total_pairs' in body)
    check('total_pairs >= 1', body.get('total_pairs', 0) >= 1)
else:
    check('GET /api/rlhf/stats 예상치 못한 응답', False, f'status={status}')

# ──────────────────────────────────────────────────────
# 7. DPO Export (GET /api/feedback/export)
# ──────────────────────────────────────────────────────
print('\n[7] DPO Export — GET /api/feedback/export')

status, body = req('GET', '/api/feedback/export?format=openai&limit=5')
if status == 403:
    skip('GET /api/feedback/export', 'admin 권한 필요 (예상된 403)')
elif status == 200:
    check('GET /api/feedback/export → 200', True)
    check('응답이 배열', isinstance(body, list))
else:
    check('DPO Export 응답', False, f'status={status}, body={str(body)[:100]}')

# ──────────────────────────────────────────────────────
# 결과 요약
# ──────────────────────────────────────────────────────
total = results['pass'] + results['fail'] + results['skip']
print(f'\n{"="*55}')
print(f'  결과: {results["pass"]}개 통과 / {results["fail"]}개 실패 / {results["skip"]}개 스킵  (총 {total}개)')
print(f'{"="*55}\n')

if results['fail'] > 0:
    sys.exit(1)
