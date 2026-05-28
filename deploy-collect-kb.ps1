param(
    [string]$ProjectId       = "medical-compliance-tester",
    [string]$Region          = "asia-northeast3",
    [string]$JobName         = "collect-public-kb",
    [string]$ServiceName     = "medical-compliance-tester",
    [string]$SqlInstance     = "medical-db",
    [string]$DbPassword      = "",
    [string]$ServiceAccount  = "716262961556-compute@developer.gserviceaccount.com",
    [string]$VpcConnector    = "medical-connector",
    [int]$MaxPerSource       = 100,
    [string]$Source          = "all",
    [switch]$DryRun,
    [switch]$Execute,
    [switch]$Wait
)

Write-Host "=== collect-public-kb — Cloud Run Job ===" -ForegroundColor Cyan
Write-Host "Job:     $JobName"
Write-Host "Project: $ProjectId"
Write-Host "Region:  $Region"
Write-Host "Source:  $Source  MaxPerSource: $MaxPerSource  DryRun: $DryRun"
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

$DatabaseUrl = "postgresql://app_user:${DbPassword}@/medical_app?host=/cloudsql/${SqlConnection}"

# ── collect_public_kb.py CMD args ──────────────────────
$CollectArgs = "collect_public_kb.py,--source,$Source,--max-per-source,$MaxPerSource"
if ($DryRun) { $CollectArgs = "$CollectArgs,--dry-run" }

# ── EnvSpec (';' 구분자 — DATABASE_URL 안의 ',' 방지) ──
$EnvSpec = "^;^DATABASE_URL=$DatabaseUrl"

# ── Job 존재 여부 확인 ──────────────────────────────────
$existsOutput = ""
try {
    $existsOutput = gcloud run jobs describe $JobName `
        --region $Region --project $ProjectId `
        --format="value(metadata.name)" 2>$null
} catch {
    $existsOutput = ""
}
$Action = if ($existsOutput -and ($existsOutput -match $JobName)) { "update" } else { "create" }
Write-Host "[1/2] Job $Action: $JobName..." -ForegroundColor Yellow

# ── gcloud args 배열로 구성 ──────────────────────────────
$gcloudArgs = @(
    "run", "jobs", $Action, $JobName,
    "--image=$ImageUri",
    "--region=$Region",
    "--project=$ProjectId",
    "--service-account=$ServiceAccount",
    "--memory=2Gi",
    "--cpu=1",
    "--task-timeout=1800",
    "--max-retries=0",
    "--parallelism=1",
    "--tasks=1",
    "--command=python",
    "--args=$CollectArgs",
    "--set-env-vars=$EnvSpec",
    "--set-secrets=OPENAI_API_KEY=openai-api-key:latest",
    "--set-cloudsql-instances=$SqlConnection",
    "--vpc-connector=$VpcConnector",
    "--vpc-egress=all-traffic",
    "--execution-environment=gen2"
)

Write-Host "[DEBUG] gcloud $($gcloudArgs -join ' ')" -ForegroundColor DarkGray
& gcloud @gcloudArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Job $Action 실패!" -ForegroundColor Red
    exit 1
}
Write-Host "Job $Action 완료." -ForegroundColor Green
Write-Host ""

# ── 실행 ─────────────────────────────────────────────────
if (-not $Execute) {
    Write-Host "[2/2] 실행 생략 (-Execute 스위치 없음)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "수동 실행 명령어:" -ForegroundColor Cyan
    Write-Host "  # Dry-run (5건 미리보기):" -ForegroundColor Gray
    Write-Host "  gcloud run jobs execute $JobName --region $Region --project $ProjectId --wait" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  # 본 수집:" -ForegroundColor Gray
    Write-Host "  gcloud run jobs update $JobName --region $Region --project $ProjectId ``" -ForegroundColor Gray
    Write-Host "    --args='collect_public_kb.py,--source,all,--max-per-source,100'" -ForegroundColor Gray
    Write-Host "  gcloud run jobs execute $JobName --region $Region --project $ProjectId --wait" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

Write-Host "[2/2] Job 실행 중..." -ForegroundColor Yellow
$execArgs = @(
    "run", "jobs", "execute", $JobName,
    "--region=$Region",
    "--project=$ProjectId"
)
if ($Wait) { $execArgs += "--wait" }

& gcloud @execArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Job 실행 실패!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Job '$JobName' 실행 완료." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "로그 확인:" -ForegroundColor Yellow
Write-Host "  gcloud run jobs executions list --job=$JobName --region=$Region --project=$ProjectId" -ForegroundColor Gray
Write-Host "  gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=$JobName' --project=$ProjectId --limit=100 --format=json" -ForegroundColor Gray
Write-Host ""
