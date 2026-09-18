# -*- coding: utf-8 -*-
"""SKIX 2차 자문 리허설 — 자문위원 계정별로 고정 문항을 전부 실행하고 답변을 모은다.

자문 당일 사실이 틀린 답변으로 표현을 논의하면 1시간이 그대로 소모된다.
그래서 자문 전에 전 문항을 한 번씩 돌려 인용 수치 오류를 먼저 잡는다.

실제 자문위원이 하는 것과 같은 경로로 호출한다 — 계정으로 로그인하고,
배정된 케이스를 고르고, 그 케이스에 매인 문항을 순서대로 보낸다.
케이스와 Vital 세트는 헤더로만 넘기고 실제 PHR 은 서버가 붙인다.

실행:
    python scripts/run_advisory_rehearsal.py --plan            # 무엇을 돌릴지만 출력 (호출 없음)
    python scripts/run_advisory_rehearsal.py                   # 전 분과 실행
    python scripts/run_advisory_rehearsal.py --advisor rexsoft03
    python scripts/run_advisory_rehearsal.py --env dev --out reports/rehearsal.json

전제:
    · 서버가 떠 있고 (기본 http://localhost:9000)
    · 설정 화면에서 해당 환경의 API 키가 등록되어 있어야 한다.
      키가 없으면 SKIX 호출이 실패하므로 --plan 으로 목록만 확인할 수 있다.
"""
import argparse
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ADVISORS = [
    ('rexsoft01', '가정의학'), ('rexsoft02', '내분비내과'), ('rexsoft03', '응급의학'),
    ('rexsoft04', '소화기내과'), ('rexsoft05', '순환기내과'), ('rexsoft06', '산부인과'),
    ('rexsoft07', '영상의학'),
]
# SKIX 대화 엔드포인트. 베이스 주소만 넘기면 404 가 나므로 경로까지 붙인다
# (chat_tester 가 X-Target-URL 로 보내는 것과 같은 형태).
ENV_BASE = {
    'dev': 'https://dev-skix.phnyx.ai',
    'stg': 'https://staging-skix.phnyx.ai',
    'prod': 'https://skix.phnyx.ai',
}
GRAPH_TYPE = 'ORCHESTRATED_HYBRID_SEARCH'
ENV_URL = {k: f'{v}/api/service/conversations/{GRAPH_TYPE}' for k, v in ENV_BASE.items()}
Q_ORDER = {'Q1': 1, 'Q2': 2, 'Q3': 3, 'Q4': 4, 'Q5': 5, 'H': 6}
SPEC_INDEX = {s: i for i, (_u, s) in enumerate(ADVISORS)}


class Session:
    """자문위원 1인의 브라우저 세션 흉내."""

    def __init__(self, base):
        self.base = base.rstrip('/')
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def call(self, path, data=None, headers=None, timeout=180):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode('utf-8') if data is not None else None,
            headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with self.op.open(req, timeout=timeout) as r:
                return r.status, r.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', errors='replace')[:400]
        except Exception as e:
            return 0, f'{type(e).__name__}: {str(e)[:200]}'

    def json_call(self, path, data=None, headers=None, timeout=180):
        st, body = self.call(path, data, headers, timeout)
        try:
            return st, json.loads(body)
        except Exception:
            return st, body

    def login(self, uid, pw):
        st, _ = self.json_call('/api/tester/login', {'id': uid, 'password': pw})
        return st == 200


def parse_sse(raw):
    """프록시가 흘려준 SSE 를 답변 텍스트로 합친다 (proxy_server._skix_post_one 과 같은 규칙)."""
    out = {'text': '', 'strid': None, 'error': None, 'events': 0}
    for line in raw.split('\n'):
        line = line.strip()
        if not line.startswith('data:'):
            continue
        js = line[5:].strip()
        if not js:
            continue
        try:
            ed = json.loads(js)
        except json.JSONDecodeError:
            continue
        out['events'] += 1
        t = ed.get('type', '')
        if t == 'GENERATION':
            out['text'] += ed.get('text', '')
        elif t == 'INFO':
            d = ed.get('data') or {}
            if d.get('conversation_strid'):
                out['strid'] = d['conversation_strid']
        elif t == 'STOP':
            if not out['text'] and ed.get('text'):
                out['text'] = ed['text']
        elif t == 'ERROR':
            out['error'] = ed.get('message', 'SKIX ERROR')
    return out


def collect_plan(base, password):
    """자문위원별로 무엇을 몇 건 물을지 목록화한다. SKIX 는 호출하지 않는다."""
    plan = []
    for uid, spec in ADVISORS:
        s = Session(base)
        if not s.login(uid, password):
            print(f'  [로그인 실패] {uid}')
            continue
        st, cases = s.json_call('/api/phr/cases')
        if st != 200 or not isinstance(cases, dict):
            print(f'  [케이스 조회 실패] {uid} — HTTP {st}')
            continue
        meta = {c['id']: c for c in cases.get('cases', [])}
        # 배정된 전 케이스의 문항을 한 번에 받는다
        st, q = s.json_call('/api/advisory/questions')
        if st != 200 or not isinstance(q, dict):
            print(f'  [문항 조회 실패] {uid} — HTTP {st}')
            continue
        items = []
        for x in q.get('questions', []):
            if x.get('specialty') != spec:
                continue     # 다른 분과 문항이 같은 케이스에 붙어 있을 수 있다
            c = meta.get(x.get('caseId'), {})
            items.append({
                'advisor': uid, 'specialty': spec,
                'caseId': x.get('caseId', ''), 'caseNo': c.get('caseNo', ''),
                'personRef': c.get('personRef', ''),
                'scenarioId': x['id'], 'code': x.get('code', ''),
                'item': x.get('item', ''), 'vitals': x.get('vitals', ''),
                'prompt': x.get('prompt', ''), 'checkPoint': x.get('checkPoint', ''),
                'riskLevel': x.get('riskLevel', ''),
            })
        items.sort(key=lambda z: (z['caseNo'], Q_ORDER.get(z['code'], 9), z['vitals']))
        plan.append({'advisor': uid, 'specialty': spec, 'session': s, 'items': items})
    return plan


def run_one(s, base, target_url, item, timeout):
    """문항 1건 실행. 자문위원이 화면에서 보내는 것과 같은 헤더 구성."""
    conv_id = f"conv-rh-{item['scenarioId']}"
    headers = {
        'X-Target-URL': target_url,
        'X-Conversation-Id': conv_id,
        'X-PHR-Case-Id': item['caseId'],
    }
    if item['vitals']:
        headers['X-PHR-Vitals'] = item['vitals']
    body = {'query': item['prompt'], 'conversation_strid': None, 'source_types': []}
    t0 = time.time()
    st, raw = s.call('/', body, headers, timeout=timeout)
    elapsed = int((time.time() - t0) * 1000)
    ev = parse_sse(raw) if st == 200 else {'text': '', 'error': f'HTTP {st}: {raw[:200]}', 'events': 0}
    return {**item, 'conversationId': conv_id, 'httpStatus': st,
            'elapsedMs': elapsed, 'answer': ev['text'], 'error': ev.get('error'),
            'events': ev.get('events', 0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://localhost:9000', help='테스트 도구 주소')
    ap.add_argument('--env', default='dev', choices=list(ENV_URL), help='SKIX 환경')
    ap.add_argument('--target-url', default='', help='SKIX 주소 직접 지정 (--env 무시)')
    ap.add_argument('--advisor', default='', help='특정 자문위원만 (예: rexsoft03)')
    # 계정 비밀번호는 저장소에 적지 않는다.
    ap.add_argument('--password', default=os.environ.get('ADVISOR_PASSWORD', ''),
                    help='자문위원 계정 비밀번호 (환경변수 ADVISOR_PASSWORD 도 가능)')
    ap.add_argument('--timeout', type=int, default=300, help='문항당 최대 대기 초')
    ap.add_argument('--sleep', type=float, default=1.0, help='문항 사이 간격 초')
    ap.add_argument('--out', default='reports/advisory_rehearsal.json')
    ap.add_argument('--plan', action='store_true', help='SKIX 호출 없이 실행 계획만 출력')
    ap.add_argument('--one-per-specialty', action='store_true',
                    help='분과별 대표 1문항만 (위험도 최고 우선, 동률이면 Q1→H 순)')
    args = ap.parse_args()

    target_url = args.target_url or ENV_URL[args.env]
    print('=' * 82)
    print('SKIX 2차 자문 리허설' + (' [계획만]' if args.plan else ''))
    print('=' * 82)
    print(f'테스트 도구  {args.base}')
    if not args.plan:
        print(f'SKIX 환경    {args.env} — {target_url}')
    print()

    plan = collect_plan(args.base, args.password)
    if args.advisor:
        plan = [p for p in plan if p['advisor'] == args.advisor]
    if args.one_per_specialty:
        # 분과마다 가장 위험한 문항 1건. 프로덕션처럼 호출이 비싼 환경에서
        # 전 문항을 돌리기 전에 응답 품질과 소요 시간을 먼저 재기 위한 표본이다.
        rank = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
        for p in plan:
            if p['items']:
                p['items'] = [min(p['items'], key=lambda z: (
                    rank.get(z['riskLevel'], 4), Q_ORDER.get(z['code'], 9), z['vitals']))]

    total = sum(len(p['items']) for p in plan)
    print(f'■ 실행 대상 — 자문위원 {len(plan)}명 · 문항 {total}건\n')
    for p in plan:
        by_case = {}
        for it in p['items']:
            by_case.setdefault(it['caseNo'], []).append(it)
        detail = ' '.join(f"{k.replace('CASE-', '')}({len(v)})" for k, v in sorted(by_case.items()))
        print(f"  {p['advisor']}  {p['specialty']:<7} {len(p['items']):>2}건   {detail}")

    if args.plan:
        print('\n■ 문항 목록')
        for p in plan:
            print(f"\n  ── {p['advisor']} · {p['specialty']} ──")
            for it in p['items']:
                v = f" [{it['vitals']}]" if it['vitals'] else ''
                print(f"    {it['caseNo']} {it['code']:<3}{v:<7} {it['prompt'][:62]}")
        # 계획도 파일로 남긴다 — 답변이 없어도 문서 생성기가 그대로 읽는다
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        rows = [{**it, 'answer': '', 'error': None, 'httpStatus': None, 'elapsedMs': None}
                for p in plan for it in p['items']]
        io.open(out, 'w', encoding='utf-8').write(json.dumps(
            {'env': None, 'targetUrl': None, 'total': total, 'ok': 0, 'fail': 0,
             'planOnly': True, 'results': rows}, ensure_ascii=False, indent=1))
        print(f'\n  계획 저장: {out}')
        print('  [계획만] SKIX 를 호출하지 않았습니다. --plan 을 빼고 다시 실행하세요.')
        return

    # ── 실행 ──
    # 자문위원 7명은 서로 다른 세션이고 문항도 겹치지 않으므로 분과 단위로 동시에 돌린다.
    # 한 분과 안에서는 순서대로 — 같은 계정으로 동시에 여러 대화를 여는 상황은
    # 실제 자문에서 일어나지 않고, 서버 로그도 뒤섞여 추적이 어려워진다.
    print(f'\n■ 실행 시작 — 분과 {len(plan)}개 동시 · 문항당 최대 {args.timeout}초')
    print(f'  (프로덕션은 문항당 수 분이 걸릴 수 있다)\n')
    import threading
    results, lock = [], threading.Lock()
    done = {'n': 0}

    def worker(p):
        for it in p['items']:
            r = run_one(p['session'], args.base, target_url, it, args.timeout)
            with lock:
                results.append(r)
                done['n'] += 1
                v = f"[{it['vitals']}]" if it['vitals'] else ''
                head = f"  [{done['n']:>2}/{total}] {p['specialty']:<6} {it['caseNo']} {it['code']:<3}{v:<6}"
                if r['answer'] and not r['error']:
                    print(f"{head} {r['elapsedMs'] / 1000:6.1f}s · {len(r['answer'])}자")
                else:
                    print(f"{head} 실패 — {r.get('error') or 'HTTP ' + str(r['httpStatus'])}")
                sys.stdout.flush()
            time.sleep(args.sleep)

    t0 = time.time()
    threads = [threading.Thread(target=worker, args=(p,), daemon=True) for p in plan if p['items']]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0
    results.sort(key=lambda r: (SPEC_INDEX.get(r['specialty'], 9), r['caseNo'],
                                Q_ORDER.get(r['code'], 9), r['vitals']))
    ok = sum(1 for r in results if r['answer'] and not r['error'])
    fail = len(results) - ok
    print(f'\n  전체 소요 {wall / 60:.1f}분 (동시 실행)')

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    io.open(out, 'w', encoding='utf-8').write(
        json.dumps({'env': args.env, 'targetUrl': target_url,
                    'total': total, 'ok': ok, 'fail': fail,
                    'results': results}, ensure_ascii=False, indent=1))
    print(f'\n■ 결과 — 성공 {ok}건 / 실패 {fail}건')
    print(f'  저장: {out}')
    if ok:
        avg = sum(r['elapsedMs'] for r in results if r['answer']) / ok / 1000
        print(f'  평균 응답 {avg:.1f}초')
    print('\n  다음: python scripts/make_rehearsal_report.py 로 답변 정리 문서를 만든다')


if __name__ == '__main__':
    main()
