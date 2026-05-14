"""
DEV의 시나리오를 PROD에 복사 (수동 + 자동생성 모두).

흐름:
  1. DEV admin 로그인 → /api/scenarios 전체 조회
  2. PROD admin 로그인 → 백업(JSON) → scenarios + test_runs 삭제 → import

사용:
  $env:ADMIN_PW = "123Qwer!"
  python scripts\copy_scenarios_dev_to_prod.py
"""
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    import requests
except ImportError:
    print("[ERROR] pip install requests 후 재실행")
    sys.exit(1)

DEV_URL  = 'https://medical-compliance-tester-dev-cbtevhmzrq-du.a.run.app'
PROD_URL = 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app'
BACKUP_DIR = Path(__file__).resolve().parent.parent / 'backups'


def login(session, base_url, env_label, admin_pw):
    r = session.post(
        f"{base_url}/api/auth/login",
        json={'id': 'admin', 'password': admin_pw},
        timeout=15,
    )
    r.raise_for_status()
    if not r.json().get('isAdmin'):
        raise RuntimeError(f'{env_label} admin 로그인 실패')
    print(f"  [{env_label}] admin 로그인 OK")


def get_scenarios(session, base_url):
    r = session.get(f"{base_url}/api/scenarios", timeout=30)
    r.raise_for_status()
    return r.json().get('scenarios', [])


def get_history(session, base_url):
    r = session.get(f"{base_url}/api/history", timeout=30)
    r.raise_for_status()
    return r.json().get('runs', [])


def main():
    admin_pw = os.environ.get('ADMIN_PW', '')
    if not admin_pw:
        print("[ERROR] 환경변수 ADMIN_PW 필요")
        sys.exit(1)

    print("=" * 70)
    print("  DEV → PROD 시나리오 복사")
    print("=" * 70)

    # ─── DEV 조회 ─────────────────────────────────────────────────────
    print("\n[1/5] DEV 시나리오 조회")
    dev = requests.Session()
    login(dev, DEV_URL, 'DEV', admin_pw)
    dev_scenarios = get_scenarios(dev, DEV_URL)
    print(f"  ✓ DEV 시나리오: {len(dev_scenarios)}건")

    # source별 통계
    from collections import Counter
    by_source = Counter(s.get('source', 'manual') for s in dev_scenarios)
    by_category = Counter(s.get('category', '') for s in dev_scenarios)
    print(f"  - source별: {dict(by_source)}")
    print(f"  - 카테고리 수: {len(by_category)}")
    if len(dev_scenarios) == 0:
        print("  [ERROR] DEV에 시나리오가 없습니다. 먼저 reset_and_seed_scenarios.py를 실행하세요.")
        sys.exit(1)

    # ─── PROD 로그인 + 백업 ──────────────────────────────────────────
    print("\n[2/5] PROD 백업")
    prod = requests.Session()
    login(prod, PROD_URL, 'PROD', admin_pw)
    prod_scenarios = get_scenarios(prod, PROD_URL)
    prod_runs = get_history(prod, PROD_URL)
    print(f"  ✓ PROD 현재: scenarios={len(prod_scenarios)}건, test_runs={len(prod_runs)}건")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    backup_path = BACKUP_DIR / f"prod_backup_before_copy_{ts}.json"
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump({
            'env': 'prod',
            'backup_at': datetime.now(timezone.utc).isoformat(),
            'scenarios_count': len(prod_scenarios),
            'test_runs_count': len(prod_runs),
            'scenarios': prod_scenarios,
            'test_runs': prod_runs,
        }, f, ensure_ascii=False, indent=2)
    print(f"  ✓ 백업: {backup_path}")

    # ─── PROD 삭제 ────────────────────────────────────────────────────
    print("\n[3/5] PROD 시나리오 + test_runs 삭제")
    # scenarios: source별 batch
    for source in ('manual', 'generated', 'imported', 'auto'):
        r = prod.post(f"{PROD_URL}/api/scenarios/batch-delete",
                      json={'source': source}, timeout=60)
        if r.status_code == 200:
            n = r.json().get('deleted', 0)
            if n:
                print(f"  ✓ scenarios source={source}: {n}건 삭제")

    # 잔여 시나리오 ids 기반
    remaining = get_scenarios(prod, PROD_URL)
    if remaining:
        ids = [s['id'] for s in remaining if s.get('id')]
        r = prod.post(f"{PROD_URL}/api/scenarios/batch-delete",
                      json={'ids': ids}, timeout=60)
        if r.status_code == 200:
            n = r.json().get('deleted', 0)
            print(f"  ✓ scenarios (잔여 ids): {n}건 삭제")

    # test_runs 개별 삭제
    deleted_r = 0
    failed_r = 0
    for run in prod_runs:
        rid = run.get('runId') or run.get('id')
        if not rid:
            continue
        r = prod.delete(f"{PROD_URL}/api/history/{rid}", timeout=15)
        if r.status_code == 200:
            deleted_r += 1
        else:
            failed_r += 1
    print(f"  ✓ test_runs: {deleted_r}건 삭제 (실패 {failed_r}건)")

    # 검증
    rem_s = len(get_scenarios(prod, PROD_URL))
    rem_r = len(get_history(prod, PROD_URL))
    print(f"  ✓ 잔여: scenarios={rem_s}건, test_runs={rem_r}건")

    # ─── PROD에 DEV 시나리오 가져오기 ────────────────────────────────
    print(f"\n[4/5] PROD에 DEV 시나리오 {len(dev_scenarios)}건 import")
    # import API는 source 필드를 그대로 받으므로 DEV에서 가져온 source가 보존됨
    # 각 시나리오의 id를 제거해 새 id 발급받지 않고 DEV id 유지하도록 함
    # (create_scenario가 id 충돌 시 ValueError 던지지만 PROD는 비어있어서 OK)

    # 청크 단위로 import (한 번에 1100개는 부담)
    BATCH = 100
    imported_total = 0
    skipped_total = 0
    for i in range(0, len(dev_scenarios), BATCH):
        chunk = dev_scenarios[i:i+BATCH]
        r = prod.post(f"{PROD_URL}/api/scenarios/import",
                      json={'scenarios': chunk}, timeout=120)
        if r.status_code != 200:
            print(f"  [FAIL] chunk {i}-{i+len(chunk)}: HTTP={r.status_code} {r.text[:200]}")
            continue
        d = r.json()
        imported_total += d.get('imported', 0)
        skipped_total += d.get('skipped', 0)
        print(f"  진행 {min(i+BATCH, len(dev_scenarios))}/{len(dev_scenarios)} (누적 import {imported_total}, skip {skipped_total})")

    print(f"  ✓ import 완료: {imported_total}건 (중복 skip {skipped_total}건)")

    # ─── PROD 검증 ────────────────────────────────────────────────────
    print("\n[5/5] PROD 검증")
    final = get_scenarios(prod, PROD_URL)
    fs = Counter(s.get('source', 'manual') for s in final)
    fc = Counter(s.get('category', '') for s in final)
    print(f"  총 시나리오: {len(final)}건")
    print(f"  - source별:")
    for src, n in sorted(fs.items()):
        print(f"      {src:12s}: {n}건")
    print(f"  - category별 (상위):")
    for cat, n in sorted(fc.items(), key=lambda x: -x[1])[:12]:
        print(f"      {cat:24s}: {n}건")

    print(f"\n  ✓ 완료. PROD 백업: {backup_path}")


if __name__ == '__main__':
    main()
