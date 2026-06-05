param(
    [string]$ProjectId       = "medical-compliance-tester",
    [string]$Region          = "asia-northeast3",
    [string]$JobName         = "collect-public-kb",
    [string]$ServiceAccount  = "716262961556-compute@developer.gserviceaccount.com",
    [string]$VpcConnector    = "medical-connector",
    [string]$SqlInstance     = "medical-db"
)

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"

Write-Host "=== 마이그레이션 006 — kb_chunks.content_tsv 재생성 ===" -ForegroundColor Cyan
Write-Host "Job: $JobName | Project: $ProjectId | Region: $Region"
Write-Host ""

# ── Step 1: Job을 migration 006 실행 모드로 업데이트 ──────────────
Write-Host "[1/3] Job을 run_migration_006.py 실행 모드로 업데이트..." -ForegroundColor Yellow

$updateArgs = @(
    "run", "jobs", "update", $JobName,
    "--region=$Region",
    "--project=$ProjectId",
    "--command=python",
    "--args=migrations/run_migration_006.py",
    "--set-secrets=DB_PASSWORD=db-password:latest",
    "--update-env-vars=^;^DB_HOST=/cloudsql/${SqlConnection};DB_USER=app_user;DB_NAME=medical_app"
)

Write-Host "[DEBUG] gcloud $($updateArgs -join ' ')" -ForegroundColor DarkGray
& gcloud @updateArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Job 업데이트 실패!" -ForegroundColor Red
    exit 1
}
Write-Host "Job 업데이트 완료." -ForegroundColor Green
Write-Host ""

# ── Step 2: Job 실행 (--wait로 완료까지 대기) ─────────────────────
Write-Host "[2/3] 마이그레이션 006 실행 중 (--wait)..." -ForegroundColor Yellow

$execArgs = @(
    "run", "jobs", "execute", $JobName,
    "--region=$Region",
    "--project=$ProjectId",
    "--wait"
)

Write-Host "[DEBUG] gcloud $($execArgs -join ' ')" -ForegroundColor DarkGray
& gcloud @execArgs
$migExitCode = $LASTEXITCODE
Write-Host ""

# ── Step 3: 로그 확인 ─────────────────────────────────────────────
Write-Host "[3/3] 최근 실행 로그 확인..." -ForegroundColor Yellow
$logArgs = @(
    "logging", "read",
    "resource.type=cloud_run_job AND resource.labels.job_name=$JobName",
    "--project=$ProjectId",
    "--limit=40",
    "--format=value(textPayload)",
    "--freshness=5m"
)
& gcloud @logArgs
Write-Host ""

if ($migExitCode -ne 0) {
    Write-Host "[ERROR] 마이그레이션 006 실행 실패 (exit=$migExitCode)" -ForegroundColor Red
    exit 1
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  마이그레이션 006 완료 — BM25 검색 복구 확인 필요" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
