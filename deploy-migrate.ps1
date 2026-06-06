# 이미지 출처는 ServiceName (gcr.io/<ProjectId>/<ServiceName>).
# 기본 DbName=medical_app_dev (DEV). -Prod 스위치로만 운영 DB(medical_app) 대상.
param(
    [string]$ProjectId      = "medical-compliance-tester",
    [string]$Region         = "asia-northeast3",
    [string]$ServiceName    = "medical-compliance-tester",
    [string]$SqlInstance    = "medical-db",
    [string]$DbName         = "medical_app_dev",
    [string]$JobName        = "",
    [string]$DbPassword     = "",
    [string]$ServiceAccount = "716262961556-compute@developer.gserviceaccount.com",
    [string]$VpcConnector   = "medical-connector",
    [switch]$Prod,
    [switch]$Execute,
    [switch]$Wait
)

# -Prod 스위치: 운영 DB 대상 (안전을 위해 명시적으로만)
if ($Prod) {
    $DbName = "medical_app"
}
if (-not $JobName) {
    $JobName = if ($DbName -eq "medical_app") { "db-migrate-prod" } else { "db-migrate-dev" }
}

Write-Host "=== DB Schema Migrate — Cloud Run Job ===" -ForegroundColor Cyan
Write-Host "Job:     $JobName"
Write-Host "DB:      $DbName  $(if ($DbName -eq 'medical_app') { '[운영]' } else { '[DEV]' })" -ForegroundColor $(if ($DbName -eq 'medical_app') { 'Red' } else { 'Green' })
Write-Host "Project: $ProjectId / Region: $Region"
Write-Host "명령:    migrate_runner.py --sync (최초 baseline 후 대기분 apply, 멱등)"
Write-Host ""

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"
$ImageUri      = "gcr.io/${ProjectId}/${ServiceName}"

# ── DB 비밀번호 ──────────────────────────────────────────
if (-not $DbPassword) { $DbPassword = $env:DB_PASSWORD }
if (-not $DbPassword) {
    Write-Host "Secret Manager에서 DB 비밀번호 조회..." -ForegroundColor Yellow
    try {
        $DbPassword = gcloud secrets versions access latest `
            --secret=db-password --project=$ProjectId 2>$null
    } catch {}
}
if (-not $DbPassword) {
    Write-Host "[ERROR] DB 비밀번호 없음. -DbPassword 또는 `$env:DB_PASSWORD 지정." -ForegroundColor Red
    exit 1
}
Write-Host "DB Password: ****" -ForegroundColor Green

$DatabaseUrl = "postgresql://app_user:${DbPassword}@/${DbName}?host=/cloudsql/${SqlConnection}"

# ── Env (';' 구분자 — DATABASE_URL 안의 ',' 방지) ──
#    RUN_MODE=migrate → entrypoint.sh 가 migrate_runner.py --sync 실행
$EnvSpec = "^;^DATABASE_URL=$DatabaseUrl;RUN_MODE=migrate"

# ── Job 존재 여부 확인 → create / update ──
$existsOutput = ""
try {
    $existsOutput = gcloud run jobs describe $JobName `
        --region $Region --project $ProjectId `
        --format="value(metadata.name)" 2>$null
} catch { $existsOutput = "" }
$Action = if ($existsOutput -and ($existsOutput -match $JobName)) { "update" } else { "create" }
Write-Host "[1/2] Job ${Action}: $JobName..." -ForegroundColor Yellow

$gcloudArgs = @(
    "run", "jobs", $Action, $JobName,
    "--image=$ImageUri",
    "--region=$Region",
    "--project=$ProjectId",
    "--service-account=$ServiceAccount",
    "--memory=1Gi",
    "--cpu=1",
    "--task-timeout=900",
    "--max-retries=0",
    "--parallelism=1",
    "--tasks=1",
    "--set-env-vars=$EnvSpec",
    "--set-cloudsql-instances=$SqlConnection",
    "--vpc-connector=$VpcConnector",
    "--vpc-egress=private-ranges-only",
    "--execution-environment=gen2"
)
Write-Host "[DEBUG] gcloud run jobs $Action $JobName ... (DATABASE_URL 마스킹)" -ForegroundColor DarkGray
& gcloud @gcloudArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Job $Action 실패!" -ForegroundColor Red
    exit 1
}
Write-Host "Job $Action 완료." -ForegroundColor Green
Write-Host ""

# ── 실행 ─────────────────────────────────────────────────
if (-not $Execute) {
    Write-Host "[2/2] 실행 생략 (-Execute 없음)." -ForegroundColor Yellow
    Write-Host "수동 실행:" -ForegroundColor Cyan
    Write-Host "  gcloud run jobs execute $JobName --region $Region --project $ProjectId --wait" -ForegroundColor Gray
    exit 0
}

Write-Host "[2/2] Job 실행 중..." -ForegroundColor Yellow
$execArgs = @("run", "jobs", "execute", $JobName, "--region=$Region", "--project=$ProjectId")
if ($Wait) { $execArgs += "--wait" }
& gcloud @execArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Job 실행 실패!" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  마이그레이션 Job '$JobName' 실행 완료 ($DbName)." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "로그:" -ForegroundColor Yellow
Write-Host "  gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=$JobName' --project=$ProjectId --limit=50" -ForegroundColor Gray
