#!/bin/sh
# medical-compliance-tester (호스트) Cloud Run 진입점.
# RUN_MODE=job 이면 Cloud Run Jobs (batch 1회 실행 후 종료), 그 외엔 HTTP 서버 상주.
# ※ RAG 서비스 모드(rag)와 DB 마이그레이션 모드(migrate)는 medical-rag-service repo 로
#    분리됨 (4-E). 호스트 이미지엔 rag_server.py/migrations/ 가 더 이상 존재하지 않는다.
set -e

if [ "$RUN_MODE" = "job" ]; then
    echo "[entrypoint] mode=job → python /app/job_runner.py"
    exec python /app/job_runner.py
else
    PORT_USED="${PORT:-8080}"
    echo "[entrypoint] mode=service → python /app/proxy_server.py --port ${PORT_USED}"
    exec python /app/proxy_server.py --port "${PORT_USED}"
fi
