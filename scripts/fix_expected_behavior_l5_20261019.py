# -*- coding: utf-8 -*-
"""LG-02 L5 헷지 충돌 일반 시나리오 3건(DIAG-123·EDGE-048·EMER-147)의 기대 동작 문장을 고친다.

2026-10-19 사용자 결정(REQ-JVMK 16:10, A+B): 기대 동작은 법률 게이트 입력으로 쓰지 않고, 기대 동작이
원인 후보 설명을 요구해 답변이 LG-02 L5 로 FAIL 되는 문항은 호스트 쪽 기대 동작 문장을 고친다.
수정 전후 문장은 같은 폴더의 expected_behavior_fix_20261019.json 에 있다(답변 원문은 넣지 않는다).

운영 DB 는 private IP 라 서비스 API(PUT /api/scenarios/<id>, 관리자 로그인)로 반영한다.
현재 값이 JSON 의 before 와 다르면 그 건은 건너뛴다(이미 반영됐거나 누가 고친 것).

    $env:ADMIN_PW = "..."; python scripts/fix_expected_behavior_l5_20261019.py [--env prod|dev] [--dry-run]
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

URLS = {
    'prod': 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app',
    'dev': 'https://medical-compliance-tester-dev-cbtevhmzrq-du.a.run.app',
}
HERE = os.path.dirname(os.path.abspath(__file__))
CHANGES = os.path.join(HERE, 'expected_behavior_fix_20261019.json')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default='prod', choices=sorted(URLS))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--insecure', action='store_true', help='사내 TLS 가로채기 환경이면 인증서 검증 끔')
    a = ap.parse_args(argv)

    import requests
    pw = os.environ.get('ADMIN_PW', '')
    if not pw:
        print('[fix] 환경변수 ADMIN_PW 필요'); return 2
    if a.insecure:
        import urllib3; urllib3.disable_warnings()
    base = URLS[a.env]
    s = requests.Session(); s.verify = not a.insecure
    r = s.post(f'{base}/api/auth/login', json={'id': 'admin', 'password': pw}, timeout=30)
    r.raise_for_status()
    if not r.json().get('isAdmin'):
        print(f'[fix] {a.env} admin 로그인 실패'); return 2

    data = json.load(open(CHANGES, encoding='utf-8'))
    applied = []
    for it in data['items']:
        sid = it['id']
        cur = s.get(f'{base}/api/scenarios/{sid}', timeout=30)
        if cur.status_code != 200:
            print(f'[fix] {sid} 조회 실패 {cur.status_code}'); continue
        sc = cur.json().get('scenario') or cur.json()
        now_eb = (sc.get('expectedBehavior') or '').strip()
        if now_eb == it['after'].strip():
            print(f'[fix] {sid} 이미 after 와 같음 — 건너뜀'); continue
        if now_eb != it['before'].strip():
            print(f'[fix] {sid} 현재 값이 before 와 다름 — 건너뜀\n  현재: {now_eb}'); continue
        if a.dry_run:
            print(f'[fix] {sid} dry-run: 바꿀 문장\n  - {it["before_sentence"]}\n  + {it["after_sentence"]}'); continue
        r = s.put(f'{base}/api/scenarios/{sid}', json={'expectedBehavior': it['after']}, timeout=30)
        r.raise_for_status()
        chk = s.get(f'{base}/api/scenarios/{sid}', timeout=30).json()
        chk = chk.get('scenario') or chk
        ok = (chk.get('expectedBehavior') or '').strip() == it['after'].strip()
        print(f'[fix] {sid} PUT {r.status_code} 재조회 일치={ok} updatedAt={chk.get("updatedAt")}')
        if ok:
            applied.append({'id': sid, 'updatedAt': chk.get('updatedAt')})
    if applied and not a.dry_run:
        data['applied'] = {'env': a.env, 'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                           'items': applied}
        json.dump(data, open(CHANGES, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        print(f'[fix] {len(applied)}건 반영, {os.path.basename(CHANGES)} 에 applied 기록')
    return 0


if __name__ == '__main__':
    sys.exit(main())
