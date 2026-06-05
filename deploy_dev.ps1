param(
    [string]$ProjectId = "medical-compliance-tester",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "medical-compliance-tester",
    [string]$SqlInstance = "medical-db",
    [string]$DbPassword = ""
)

Write-Host "=== Medical Compliance Tester - Cloud Run Dev Deploy (--tag dev --no-traffic) ===" -ForegroundColor Cyan
Write-Host "Production traffic NOT affected: --no-traffic applied" -ForegroundColor Yellow
Write-Host ""

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"

Write-Host "Project:      $ProjectId"
Write-Host "Region:       $Region"
Write-Host "Service:      $ServiceName"
Write-Host "Cloud SQL:    $SqlConnection"
Write-Host "Tag:          dev"
Write-Host "Traffic:      0% (--no-traffic)"
Write-Host ""

# DB password: param -> env var -> Secret Manager -> error
if (-not $DbPassword) {
    $DbPassword = $env:DB_PASSWORD
}
if (-not $DbPassword) {
    Write-Host "Fetching DB password from Secret Manager..." -ForegroundColor Yellow
    try {
        $DbPassword = gcloud secrets versions access latest --secret=db-password --project=$ProjectId 2>$null
    } catch {}
}
if (-not $DbPassword) {
    Write-Host "DB password not found. Set it via one of:" -ForegroundColor Red
    Write-Host '  1. Secret Manager: echo -n "password" | gcloud secrets create db-password --data-file=-'
    Write-Host '  2. Param: .\deploy_dev.ps1 -DbPassword "password"'
    Write-Host '  3. Env var: $env:DB_PASSWORD = "password"; .\deploy_dev.ps1'
    exit 1
}
Write-Host "DB Password:  ****" -ForegroundColor Green

$DatabaseUrl = "postgresql://app_user:${DbPassword}@/medical_app?host=/cloudsql/${SqlConnection}"

# [0/3] Cloud SQL instance check
Write-Host "[0/3] Checking Cloud SQL instance..." -ForegroundColor Yellow
$SqlStatus = gcloud sql instances describe $SqlInstance --project=$ProjectId --format="value(databaseVersion,state)" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $SqlStatus) {
    Write-Host "[ERROR] Cannot verify Cloud SQL instance '$SqlInstance'." -ForegroundColor Red
    Write-Host "        Check gcloud auth or instance name."
    exit 1
}
$SqlParts = $SqlStatus -split "`t|`n| "
$SqlVersion = $SqlParts[0]
$SqlState   = $SqlParts[1]
Write-Host "  DB Version: $SqlVersion" -ForegroundColor Cyan
Write-Host "  DB State:   $SqlState" -ForegroundColor Cyan
if ($SqlState -ne "RUNNABLE") {
    Write-Host "[ERROR] Cloud SQL state is not RUNNABLE (current: $SqlState). Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "Cloud SQL check OK!" -ForegroundColor Green
Write-Host ""

# [1/3] Docker image build
Write-Host "[1/3] Building Docker image..." -ForegroundColor Yellow
$BuildStart = Get-Date
gcloud builds submit --tag "gcr.io/$ProjectId/$ServiceName" .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}
$BuildEnd = Get-Date
$BuildMin = [math]::Round(($BuildEnd - $BuildStart).TotalMinutes, 1)
Write-Host "Build done! ($BuildMin min)" -ForegroundColor Green

# [2/3] Cloud Run deploy (dev tag, no-traffic)
Write-Host "[2/3] Deploying to Cloud Run with --tag dev --no-traffic..." -ForegroundColor Yellow
$DeployStart = Get-Date
gcloud run deploy $ServiceName --image "gcr.io/$ProjectId/$ServiceName" --region $Region --platform managed --allow-unauthenticated --tag dev --no-traffic --memory 2Gi --cpu 2 --timeout 900 --min-instances 0 --max-instances 5 --concurrency 10 --execution-environment gen2 --set-env-vars "DATABASE_URL=$DatabaseUrl,DEPLOYMENT_ENV=dev,RETRIEVAL_GATE_ENFORCE=false,GATE_TOP1_PASS=0.55,GATE_TOP1_WEAK=0.42,GATE_CHUNK_COUNT_PASS=3,GATE_TOPIC_MATCH_PASS=2,GATE_WEIGHTED_PASS=2.0" --update-secrets "OPENAI_API_KEY=openai-api-key:latest" --add-cloudsql-instances $SqlConnection --vpc-connector=medical-connector --vpc-egress=all-traffic --cpu-boost --no-cpu-throttling --clear-volumes --clear-volume-mounts
if ($LASTEXITCODE -ne 0) {
    Write-Host "Deploy failed!" -ForegroundColor Red
    exit 1
}
$DeployEnd = Get-Date
$DeployMin = [math]::Round(($DeployEnd - $DeployStart).TotalMinutes, 1)
Write-Host "Deploy done! ($DeployMin min)" -ForegroundColor Green

# [3/3] Extract dev URL and report
Write-Host ""
Write-Host "[3/3] Extracting dev URL..." -ForegroundColor Yellow

$DevUrl = gcloud run services describe $ServiceName --region $Region --format=json 2>$null | python -c "import json,sys; data=json.load(sys.stdin); tags=data.get('status',{}).get('traffic',[]); urls=[t['url'] for t in tags if t.get('tag')=='dev']; print(urls[0] if urls else '')"
$ProdUrl = gcloud run services describe $ServiceName --region $Region --format "value(status.url)" 2>$null

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  [PROD] Unchanged:  $ProdUrl" -ForegroundColor Green
Write-Host "  [DEV]  Test URL:   $DevUrl" -ForegroundColor Magenta
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Chat:     $DevUrl/"
Write-Host "  KB Mgr:   $DevUrl/kb_manager"
Write-Host "  Scenario: $DevUrl/manager"
Write-Host "  History:  $DevUrl/history"
Write-Host "  Settings: $DevUrl/settings"
Write-Host ""
Write-Host "Storage: Cloud SQL PostgreSQL ($SqlConnection) -- shared with prod" -ForegroundColor Yellow
Write-Host "NOTE: KB writes in dev also affect prod DB." -ForegroundColor Yellow
Write-Host ""
Write-Host "Remove dev tag (rollback):" -ForegroundColor Cyan
Write-Host "  gcloud run services update-traffic $ServiceName --remove-tags dev --region $Region" -ForegroundColor Cyan
Write-Host ""
Write-Host "Build: $BuildMin min / Deploy: $DeployMin min" -ForegroundColor Green
