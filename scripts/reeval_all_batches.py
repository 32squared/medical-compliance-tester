"""5개 batch 모두 LLM-only 재평가 (순차 호출).

각 호출은 동기. 클라이언트는 OpenAI 호출 완료까지 기다림.
PowerShell보다 timeout 처리가 안정적이라 python 사용.
"""
import io
import os
import sys
import time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import requests

PROD_URL = 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app'

# 5개 batch 모두 (gptEval 보강용)
RUN_IDS = [
    'batch-20260514-175526-0ae23b',
    'batch-20260514-213809-e490cd',
    'batch-20260514-222243-6560d9',
    'batch-20260514-222443-95d155',
    'batch-20260514-233533-dfcaef',
]


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def main():
    admin_pw = os.environ.get('ADMIN_PW', '')
    if not admin_pw:
        log("[ERROR] ADMIN_PW 필요")
        sys.exit(1)

    s = requests.Session()
    r = s.post(f"{PROD_URL}/api/auth/login",
               json={'id': 'admin', 'password': admin_pw}, timeout=15)
    r.raise_for_status()
    if not r.json().get('isAdmin'):
        log("[ERROR] admin 로그인 실패")
        sys.exit(1)
    log("admin 로그인 OK")

    total_started = time.time()
    for i, run_id in enumerate(RUN_IDS, start=1):
        log("=" * 70)
        log(f"[{i}/{len(RUN_IDS)}] 재평가 시작: {run_id}")

        # 사이즈 확인
        try:
            rr = s.get(f"{PROD_URL}/api/history/{run_id}", timeout=60)
            if rr.status_code == 200:
                jj = rr.json()
                pre = len(jj.get('results', []))
                pre_gpt = sum(1 for x in jj.get('results', [])
                              if x.get('gptEval') and x['gptEval'].get('grade'))
                log(f"  현재 results: {pre}건, 이미 GPT 평가됨: {pre_gpt}건")
        except Exception:
            log("  사이즈 조회 실패")

        # 재평가 호출 (단일 동기 호출, 매우 긴 timeout)
        started = time.time()
        try:
            r = s.post(f"{PROD_URL}/api/history/re-evaluate",
                       json={'runId': run_id, 'includeGpt': True},
                       timeout=3600)  # 1시간
            if r.status_code == 200:
                d = r.json()
                elapsed_min = int((time.time() - started) / 60)
                log(f"  ✓ 완료 ({elapsed_min}분) — reEvaluated={d.get('reEvaluated')}, gptReEvaluated={d.get('gptReEvaluated')}")
                log(f"    message: {d.get('message', '')}")
            else:
                log(f"  ✗ HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            log(f"  ✗ 예외: {str(e)[:300]}")
        log(f"  단계 누적 시간: {int((time.time() - total_started) / 60)}분")
        log("")

    log("=" * 70)
    log(f"전체 완료 — 총 {int((time.time() - total_started) / 60)}분")


if __name__ == '__main__':
    main()
