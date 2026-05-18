param(
    [string]$ProjectId    = "medical-compliance-tester",
    [string]$Region       = "asia-northeast3",
    [string]$JobName      = "batch-runner",
    [string]$ServiceName  = "medical-compliance-tester",
    [string]$SqlInstance  = "medical-db",
    [string]$DbPassword   = "",
    [string]$ServiceAccount = "716262961556-compute@developer.gserviceaccount.com",
    [string]$VpcConnector = "medical-connector"
)

Write-Host "=== Cloud Run Jobs Deploy (batch-runner) ===" -ForegroundColor Cyan

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"
Write-Host "Project:    $ProjectId"
Write-Host "Region:     $Region"
Write-Host "Job Name:   $JobName"
Write-Host "Cloud SQL:  $SqlConnection"
Write-Host "Service SA: $ServiceAccount"
Write-Host "VPC:        $VpcConnector"
Write-Host ""

# DB 비밀번호 (deploy.ps1과 동일 로직)
if (-not $DbPassword) { $DbPassword = $env:DB_PASSWORD }
if (-not $DbPassword) {
    Write-Host "Secret Manager에서 DB 비밀번호를 가져옵니다..." -ForegroundColor Yellow
    try {
        $DbPassword = gcloud secrets versions access latest --secret=db-password --project=$ProjectId 2>$null
    } catch {}
}
if (-not $DbPassword) {
    Write-Host "DB 비밀번호를 찾을 수 없습니다. -DbPassword 또는 \$env:DB_PASSWORD 로 지정하세요." -ForegroundColor Red
    exit 1
}
Write-Host "DB Password: ****" -ForegroundColor Green

$DatabaseUrl = "postgresql://app_user:${DbPassword}@/medical_app?host=/cloudsql/${SqlConnection}"

# 이미지는 deploy.ps1 으로 빌드/푸시된 service 이미지 재사용
$ImageUri = "gcr.io/${ProjectId}/${ServiceName}"
Write-Host "[DEBUG] ImageUri=[$ImageUri] len=$($ImageUri.Length)" -ForegroundColor DarkGray
Write-Host "Image:      $ImageUri" -ForegroundColor Green
Write-Host ""
if ([string]::IsNullOrEmpty($ImageUri) -or $ImageUri.Length -lt 10) {
    Write-Host "FATAL: ImageUri is empty. ProjectId=$ProjectId ServiceName=$ServiceName" -ForegroundColor Red
    exit 1
}

# Job 존재 여부 확인 → create or update
$existsOutput = ""
try {
    $existsOutput = gcloud run jobs describe $JobName --region $Region --project $ProjectId --format="value(metadata.name)" 2>$null
} catch {
    $existsOutput = ""
}
$Action = if ($existsOutput -and ($existsOutput -match $JobName)) { "update" } else { "create" }
Write-Host "[1/2] Action: $Action Job '$JobName'..." -ForegroundColor Yellow

# Cloud Run Jobs CLI는 set-env-vars 가 ',' 를 구분자로 인식.
# DATABASE_URL 안에 ',' '@' 들어있을 수 있으므로 ';' 구분자 사용 (URL 표준에 ';' 없음).
$EnvSpec = "^;^RUN_MODE=job;DATABASE_URL=$DatabaseUrl"

# 배열로 인자 구성해서 PowerShell line continuation 이슈 회피
$gcloudArgs = @(
    "run", "jobs", $Action, $JobName,
    "--image=$ImageUri",
    "--region=$Region",
    "--project=$ProjectId",
    "--service-account=$ServiceAccount",
    "--memory=8Gi",
    "--cpu=4",
    "--task-timeout=86400",
    "--max-retries=0",
    "--parallelism=1",
    "--tasks=1",
    "--set-env-vars=$EnvSpec",
    "--set-cloudsql-instances=$SqlConnection",
    "--vpc-connector=$VpcConnector",
    "--vpc-egress=all-traffic",
    "--execution-environment=gen2"
)
Write-Host "[DEBUG] gcloud $($gcloudArgs -join ' ')" -ForegroundColor DarkGray
& gcloud @gcloudArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "Job $Action failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[2/2] Verifying Job..." -ForegroundColor Yellow
gcloud run jobs describe $JobName --region $Region --project $ProjectId --format="value(metadata.name,spec.template.spec.template.spec.containers[0].image,status.conditions[0].type)" 2>$null
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Job '$JobName' 배포 완료." -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "트리거 예시 (RUN_ID, SCENARIO_IDS_JSON 환경변수 override):" -ForegroundColor Yellow
Write-Host "  gcloud run jobs execute $JobName --region $Region --project $ProjectId \``" -ForegroundColor Gray
Write-Host "    --update-env-vars 'RUN_ID=job-test-001,SCENARIO_IDS_JSON=[\"DIAG-001\",\"DIAG-002\"]'" -ForegroundColor Gray
Write-Host ""
Write-Host "비동기 실행은 --async 옵션 추가." -ForegroundColor DarkGray
