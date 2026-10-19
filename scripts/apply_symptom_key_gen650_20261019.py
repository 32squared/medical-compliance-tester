# -*- coding: utf-8 -*-
"""일반 650 시나리오에 증상군 키(symptomKey)를 써 넣는다 (2026-10-19, REQ-IEZO 호스트 결정 ②).

값은 reports/v3_runs/gen650_symptom_key_20261019.json 의 items[].symptom_key — 42군 키 또는 "none"(42군 밖·증상 없음,
판정기가 증상군 매칭 없이 SV-02·03·04 를 na 로 둔다). 그 표를 만드는 생성기와 사람 검수 표는 같은 폴더에 있다.

운영·DEV DB 는 private IP 라 서비스 API(PUT /api/scenarios/<id>, 관리자 로그인)로 반영한다. 건마다
  1) 현재 값을 GET 으로 읽고, 2) 이미 같은 값이면 건너뛰고, 3) 다른 값이 '비어 있지 않으면' --force 없이는 건너뛰며
  (누가 손으로 넣은 값을 덮지 않는다), 4) PUT 뒤 다시 GET 해 일치를 확인한다.
반영 결과(env·시각·건수·before 값)는 JSON 의 applied[] 에 누적 기록해 되돌릴 수 있게 한다.

    $env:ADMIN_PW = "..."; python scripts/apply_symptom_key_gen650_20261019.py --env prod|dev [--dry-run] [--force] [--insecure]
"""
import argparse
import collections
import io
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

URLS = {
    'prod': 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app',
    'dev': 'https://medical-compliance-tester-dev-cbtevhmzrq-du.a.run.app',
}
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..'))
TABLE = os.path.join(ROOT, 'reports', 'v3_runs', 'gen650_symptom_key_20261019.json')
CHECKLISTS = os.path.join(ROOT, 'packages', 'medical_shared', 'compliance_rules', 'consultation_checklists.json')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default='prod', choices=sorted(URLS))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true', help='현재 값이 비어 있지 않고 표와 달라도 덮어쓴다')
    ap.add_argument('--insecure', action='store_true', help='사내 TLS 가로채기 환경이면 인증서 검증 끔')
    ap.add_argument('--table', default=TABLE)
    a = ap.parse_args(argv)

    data = json.load(open(a.table, encoding='utf-8'))
    items = data['items']
    valid = {g['symptom_key'] for g in json.load(open(CHECKLISTS, encoding='utf-8'))} | {'none'}
    bad = [it['id'] for it in items if it['symptom_key'] not in valid]
    if bad or len(items) != 650:
        print(f'[apply] 표 오류: 건수 {len(items)}, 잘못된 키 {bad[:5]}'); return 2
    print(f'[apply] {a.env} 대상 {len(items)}건, none {sum(1 for it in items if it["symptom_key"] == "none")}건'
          + (' (dry-run)' if a.dry_run else ''))

    import requests
    pw = os.environ.get('ADMIN_PW', '')
    if not pw:
        print('[apply] 환경변수 ADMIN_PW 필요'); return 2
    if a.insecure:
        import urllib3; urllib3.disable_warnings()
    base = URLS[a.env]
    s = requests.Session(); s.verify = not a.insecure
    r = s.post(f'{base}/api/auth/login', json={'id': 'admin', 'password': pw}, timeout=30)
    r.raise_for_status()
    if not r.json().get('isAdmin'):
        print(f'[apply] {a.env} admin 로그인 실패'); return 2

    stat = collections.Counter()
    applied = []
    for it in items:
        sid, want = it['id'], it['symptom_key']
        # 한글 id('피부-001' 등)는 경로에 URL 인코딩으로 실린다 — 서버가 unquote 하는 판(2026-10-19 이후)이어야 닿는다.
        url = f'{base}/api/scenarios/{quote(sid, safe="")}'
        cur = s.get(url, timeout=30)
        if cur.status_code != 200:
            print(f'[apply] {sid} 조회 실패 {cur.status_code}' + (' (한글 id — 서버 unquote 수정 배포 전이면 404)' if not sid.isascii() else ''))
            stat['missing'] += 1; continue
        sc = cur.json().get('scenario') or cur.json()
        now = (sc.get('symptomKey') or '').strip()
        if now == want:
            stat['same'] += 1; continue
        if now and not a.force:
            print(f'[apply] {sid} 현재 값 {now!r} ≠ 표 {want!r} — 건너뜀(--force 로 덮어씀)'); stat['kept'] += 1; continue
        if a.dry_run:
            stat['would_put'] += 1; continue
        r = s.put(url, json={'symptomKey': want}, timeout=30)
        r.raise_for_status()
        chk = s.get(url, timeout=30).json()
        chk = chk.get('scenario') or chk
        ok = (chk.get('symptomKey') or '').strip() == want
        stat['put' if ok else 'put_mismatch'] += 1
        if ok:
            applied.append({'id': sid, 'before': now, 'after': want, 'updatedAt': chk.get('updatedAt')})
        else:
            print(f'[apply] {sid} PUT 뒤 재조회 불일치: {chk.get("symptomKey")!r}')
    print(f'[apply] 결과 {dict(stat)}')
    if applied and not a.dry_run:
        data.setdefault('applied', []).append({'env': a.env, 'at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                               'count': len(applied), 'items': applied})
        json.dump(data, open(a.table, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'[apply] {len(applied)}건 반영, {os.path.basename(a.table)} 의 applied 에 기록')
    return 0 if not stat['put_mismatch'] and not stat['missing'] else 1


if __name__ == '__main__':
    sys.exit(main())
