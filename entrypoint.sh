#!/bin/sh
# Cloud Run 서비스/Job 공용 진입점.
# RUN_MODE=job 이면 Cloud Run Jobs (batch 1회 실행 후 종료),
# 그 외엔 Cloud Run Service (HTTP 서버 상주).
set -e

if [ "$RUN_MODE" = "job" ]; then
    echo "[entrypoint] mode=job → python /app/job_runner.py"
    exec python /app/job_runner.py
else
    PORT_USED="${PORT:-8080}"
    echo "[entrypoint] mode=service → python /app/proxy_server.py --port ${PORT_USED}"
    exec python /app/proxy_server.py --port "${PORT_USED}"
fi
