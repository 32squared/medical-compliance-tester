#!/bin/sh
# medical-compliance-tester (호스트) Cloud Run 진입점.
# RUN_MODE=job 이면 Cloud Run Jobs (batch 1회 실행 후 종료), 그 외엔 HTTP 서버 상주.
# ※ RAG 서비스 모드(rag)와 DB 마이그레이션 모드(migrate)는 medical-rag-service repo 로
#    분리됨 (4-E). 호스트 이미지엔 rag_server.py/migrations/ 가 더 이상 존재하지 않는다.
set -e

if [ "$RUN_MODE" = "job" ]; then
    echo "[entrypoint] mode=job → python /app/job_runner.py"
    exec python /app/job_runner.py
elif [ "$RUN_MODE" = "seed_advisory" ]; then
    # 2차 자문 준비 데이터 투입 (Cloud Run Job 전용).
    # Cloud SQL 이 private IP 라 로컬에서 직접 넣을 수 없어 GCP 안에서 실행한다.
    # SEED_DRY_RUN=1 이면 저장하지 않고 계획만 출력한다.
    # 운영 DB 처럼 이미 데이터가 있는 곳에서는 무엇을 덮어쓰는지 먼저 확인한다.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=seed_advisory → scripts/seed_advisory.py ${SEED_ARGS}"
    exec python /app/scripts/seed_advisory.py \
        --phr "${SEED_PHR_XLSX:-/app/seed_data/phr_70.xlsx}" \
        --questions "${SEED_Q_XLSX:-/app/seed_data/questions.xlsx}" \
        ${SEED_ARGS}
else
    PORT_USED="${PORT:-8080}"
    echo "[entrypoint] mode=service → python /app/proxy_server.py --port ${PORT_USED}"
    exec python /app/proxy_server.py --port "${PORT_USED}"
fi
