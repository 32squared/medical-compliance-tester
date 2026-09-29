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
elif [ "$RUN_MODE" = "run_phr_sample" ]; then
    # PHR 배치 평가 샘플 실행 — 소수 건으로 세 평가 축 확인. DB 이력에 남기지 않는다.
    echo "[entrypoint] mode=run_phr_sample → scripts/run_phr_sample.py (count=${SAMPLE_COUNT:-30})"
    exec python /app/scripts/run_phr_sample.py --count "${SAMPLE_COUNT:-30}"
elif [ "$RUN_MODE" = "seed_scenarios" ]; then
    # 시나리오 JSON 적재 (Cloud Run Job 전용) — scripts/seed_scenarios_json.py 참고.
    # 기본 파일은 v17→v18 회귀 문항 6종(REQ-0012). SEED_SCENARIOS_JSON 으로 바꿀 수 있다.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=seed_scenarios → scripts/seed_scenarios_json.py ${SEED_ARGS}"
    exec python /app/scripts/seed_scenarios_json.py --file "${SEED_SCENARIOS_JSON:-/app/scripts/scenarios_v18_regression.json}" ${SEED_ARGS}
elif [ "$RUN_MODE" = "apply_v3_review" ]; then
    # v3 법률 판정 사람 검토 정정 (Cloud Run Job 전용) — scripts/apply_v3_review.py 참고.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=apply_v3_review → scripts/apply_v3_review.py ${REVIEW_FILE} ${SEED_ARGS}"
    exec python /app/scripts/apply_v3_review.py --file "/app/${REVIEW_FILE}" ${SEED_ARGS}
elif [ "$RUN_MODE" = "rejudge_v3" ]; then
    # 저장된 답변을 v3 판정기로 다시 판정해 새 이력(RUN_ID)으로 저장 — scripts/rejudge_v3.py 참고.
    # REJUDGE_SOURCE=원본 runId, SCENARIO_IDS_JSON=대상 id(비우면 전체). EVAL_V3=1 이어야 판정기가 켜진다.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=rejudge_v3 → scripts/rejudge_v3.py source=${REJUDGE_SOURCE} new=${RUN_ID} ${SEED_ARGS}"
    exec python /app/scripts/rejudge_v3.py ${SEED_ARGS}
elif [ "$RUN_MODE" = "ai_verify" ]; then
    # 판정 결과 AI 독립 검수 — scripts/ai_verify.py 참고 (VERIFY_RUNS·VERIFY_PASS·VERIFY_MODEL).
    # 결과는 gold_labels(labeler ai:verifier)에 저장되고 검토 화면의 'AI: 확인 필요' 로 사람에게 넘어간다.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=ai_verify → scripts/ai_verify.py runs=${VERIFY_RUNS} ${SEED_ARGS}"
    exec python /app/scripts/ai_verify.py ${SEED_ARGS}
elif [ "$RUN_MODE" = "scenario_inventory" ]; then
    # 시험 문항 현황표 + v3 축 분류(문항 재편 1·2단계) — scripts/scenario_inventory.py 참고.
    # INVENTORY_OUT=gs://… 로 결과 JSON(문항 원문 제외)을 올린다. INVENTORY_LLM=0 이면 분류 없이 현황만.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=scenario_inventory → scripts/scenario_inventory.py out=${INVENTORY_OUT} ${SEED_ARGS}"
    exec python /app/scripts/scenario_inventory.py ${SEED_ARGS}
elif [ "$RUN_MODE" = "apply_scenario_set" ]; then
    # v3 시험 세트 반영 — scripts/apply_scenario_set.py 참고. SET_PLAN(기본: 이미지 안 v3set-1 plan)의
    # 태그·증상군을 붙이고 세트 밖 문항은 enabled 만 끈다(retired:<set>-unselected 태그, 지우지 않음).
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=apply_scenario_set → scripts/apply_scenario_set.py plan=${SET_PLAN:-/app/scripts/v3set_1_plan.json} ${SEED_ARGS}"
    exec python /app/scripts/apply_scenario_set.py --plan "${SET_PLAN:-/app/scripts/v3set_1_plan.json}" ${SEED_ARGS}
elif [ "$RUN_MODE" = "gen_gap_items" ]; then
    # v3 세트 빈 칸 문항 AI 작성 + 자동 검사(형식·중복·분류) — scripts/gen_gap_items.py 참고.
    # SET_PLAN·GEN_OUT(gs://…)·GEN_MODEL·GEN_ROUNDS·GEN_WORKERS·GEN_ONLY. SEED_DRY_RUN=1 이면 저장 안 함.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=gen_gap_items → scripts/gen_gap_items.py out=${GEN_OUT} ${SEED_ARGS}"
    exec python /app/scripts/gen_gap_items.py ${SEED_ARGS}
elif [ "$RUN_MODE" = "set_scenarios_enabled" ]; then
    # 시나리오 사용 여부 일괄 변경 — scripts/set_scenarios_enabled.py 참고 (SET_CATEGORY·SET_ID_PREFIX·
    # SET_ENABLED·SET_EXPECT·SET_TAG). 지우지 않고 enabled 만 바꾼다.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=set_scenarios_enabled → scripts/set_scenarios_enabled.py ${SEED_ARGS}"
    exec python /app/scripts/set_scenarios_enabled.py ${SEED_ARGS}
elif [ "$RUN_MODE" = "seed_phr_batch" ]; then
    # PHR 배치 평가 문항 시드 (Cloud Run Job 전용) — scripts/seed_phr_batch.py 참고.
    SEED_ARGS=""
    if [ "$SEED_DRY_RUN" = "1" ]; then SEED_ARGS="--dry-run"; fi
    echo "[entrypoint] mode=seed_phr_batch → scripts/seed_phr_batch.py ${SEED_ARGS}"
    exec python /app/scripts/seed_phr_batch.py ${SEED_ARGS}
else
    PORT_USED="${PORT:-8080}"
    echo "[entrypoint] mode=service → python /app/proxy_server.py --port ${PORT_USED}"
    exec python /app/proxy_server.py --port "${PORT_USED}"
fi
