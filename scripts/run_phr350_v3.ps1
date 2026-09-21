# PHR 문항 350건(category phr_case) v3 판정 배치 실행 — 운영 batch-runner Job 1회 실행.
#
# 전제: 350건이 운영 DB 에 적재돼 있어야 한다(docs/runbook_phr350_v3.md 1단계).
#       Job 은 이미 EVAL_V3=1 · EVAL_FINAL=v3 · mini 1차 + gpt-5.4 2차 로 배포돼 있다(재배포 불필요).
# 병렬: 배치 실행기 동시 20건(BatchExecutor.DEFAULT_MAX_WORKERS). 350건 예상 25~35분.
#
# 사용:
#   .\scripts\run_phr350_v3.ps1 -Smoke        # 앞 5건만 (약 2분) — 케이스 주입·판정 확인
#   .\scripts\run_phr350_v3.ps1               # 350건 전체
param(
    [switch]$Smoke,
    [string]$ProjectId = "medical-compliance-tester",
    [string]$Region    = "asia-northeast3",
    [string]$JobName   = "batch-runner",
    [string]$RunBy     = "phr350-v3"
)
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmm")
if ($Smoke) {
    $runId = "phr350-smoke-$stamp"; $label = "PHR 350 사전 점검 5건 (v3 최종)"; $limit = "5"
} else {
    $runId = "phr350-v3-$stamp";    $label = "PHR 350건 전체 (v3 최종, 온톨로지 v3.5)"; $limit = "0"
}
# 값에 쉼표가 없으므로 기본 구분자(,)를 쓴다.
$envs = "AUTO_SELECT=all_except_hb,SELECT_CATEGORY=phr_case,SELECT_LIMIT=$limit,RUN_ID=$runId,RUN_BY=$RunBy,LABEL=$label"
Write-Host "RUN_ID: $runId" -ForegroundColor Cyan
Write-Host "ENV   : $envs" -ForegroundColor DarkGray
gcloud run jobs execute $JobName --region $Region --project $ProjectId --async --update-env-vars $envs
if ($LASTEXITCODE -ne 0) { Write-Host "실행 요청 실패" -ForegroundColor Red; exit 1 }
Write-Host ""
Write-Host "진행 로그:" -ForegroundColor Yellow
Write-Host "  gcloud logging read 'resource.type=`"cloud_run_job`" AND resource.labels.job_name=`"$JobName`" AND textPayload:`"PROGRESS`"' --project $ProjectId --freshness=2h --limit 5 --format=`"value(textPayload)`""
Write-Host "결과 화면: /eval-v3 에서 RUN_ID $runId"
