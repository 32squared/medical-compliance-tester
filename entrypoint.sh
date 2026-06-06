#!/bin/sh
# Cloud Run 서비스/Job 공용 진입점.
# RUN_MODE=job 이면 Cloud Run Jobs (batch 1회 실행 후 종료),
# 그 외엔 Cloud Run Service (HTTP 서버 상주).
set -e

if [ "$RUN_MODE" = "job" ]; then
    echo "[entrypoint] mode=job → python /app/job_runner.py"
    exec python /app/job_runner.py
elif [ "$RUN_MODE" = "migrate" ]; then
    # DB 스키마 마이그레이션 1회 실행 후 종료 (Cloud Run Job 용).
    # --sync: 최초 baseline(현재 스키마 채택) 후 대기 마이그레이션 apply (멱등).
    echo "[entrypoint] mode=migrate → python /app/migrations/migrate_runner.py --sync"
    exec python /app/migrations/migrate_runner.py --sync
else
    PORT_USED="${PORT:-8080}"
    echo "[entrypoint] mode=service → python /app/proxy_server.py --port ${PORT_USED}"
    exec python /app/proxy_server.py --port "${PORT_USED}"
fi
