param(
    [string]$ProjectId = "medical-compliance-tester",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "medical-compliance-tester-dev",
    [string]$SqlInstance = "medical-db",
    [string]$DbName = "medical_app_dev",
    [string]$DbPassword = ""
)

Write-Host "=== Medical Compliance Tester - DEV Cloud Run Deploy ===" -ForegroundColor Cyan
Write-Host "(운영 서비스: medical-compliance-tester)" -ForegroundColor DarkGray

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"

Write-Host "Project:      $ProjectId"
Write-Host "Region:       $Region"
Write-Host "Service:      $ServiceName  [DEV]"
Write-Host "Cloud SQL:    $SqlConnection"
Write-Host "DB:           $DbName  [DEV — 운영과 분리]"
Write-Host ""

# DB 비밀번호: 파라미터 → 환경변수 → Secret Manager → 에러
if (-not $DbPassword) {
    $DbPassword = $env:DB_PASSWORD
}
if (-not $DbPassword) {
    Write-Host "Secret Manager에서 DB 비밀번호를 가져옵니다..." -ForegroundColor Yellow
    try {
        $DbPassword = gcloud secrets versions access latest --secret=db-password --project=$ProjectId 2>$null
    } catch {}
}
if (-not $DbPassword) {
    Write-Host "DB 비밀번호를 찾을 수 없습니다. 다음 중 하나로 설정하세요:" -ForegroundColor Red
    Write-Host '  1. 환경변수: $env:DB_PASSWORD = "password"; .\deploy-dev.ps1'
    Write-Host '  2. 파라미터: .\deploy-dev.ps1 -DbPassword "password"'
    exit 1
}
Write-Host "DB Password:  ****" -ForegroundColor Green

$DatabaseUrl = "postgresql://app_user:${DbPassword}@/${DbName}?host=/cloudsql/${SqlConnection}"

# [0/3] DEV DB 생성 (없으면)
Write-Host ""
Write-Host "[0/3] DEV DB 확인/생성..." -ForegroundColor Yellow
$dbExists = gcloud sql databases list --instance=$SqlInstance --project=$ProjectId --format="value(name)" 2>$null | Select-String -Pattern "^${DbName}$"
if (-not $dbExists) {
    Write-Host "  '$DbName' DB가 없습니다. 생성합니다..." -ForegroundColor Yellow
    gcloud sql databases create $DbName --instance=$SqlInstance --project=$ProjectId
    if ($LASTEXITCODE -ne 0) {
        Write-Host "DB 생성 실패!" -ForegroundColor Red
        exit 1
    }
    Write-Host "  '$DbName' DB 생성 완료!" -ForegroundColor Green
} else {
    Write-Host "  '$DbName' DB 이미 존재합니다." -ForegroundColor Green
}

# [1/3] Docker 이미지 빌드 (dev 태그)
Write-Host ""
Write-Host "[1/3] Building Docker image (dev)..." -ForegroundColor Yellow
gcloud builds submit --tag "gcr.io/$ProjectId/$ServiceName" .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "Build done!" -ForegroundColor Green

# [2/3] Cloud Run DEV 배포
Write-Host ""
Write-Host "[2/3] Deploying DEV service to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --image "gcr.io/$ProjectId/$ServiceName" `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --memory 1Gi --cpu 1 `
    --timeout 900 `
    --min-instances 0 --max-instances 3 `
    --concurrency 5 `
    --execution-environment gen2 `
    --set-env-vars "DATABASE_URL=$DatabaseUrl,APP_ENV=development" `
    --add-cloudsql-instances $SqlConnection `
    --vpc-connector=medical-connector `
    --vpc-egress=all-traffic `
    --cpu-boost `
    --no-cpu-throttling `
    --clear-volumes `
    --clear-volume-mounts
if ($LASTEXITCODE -ne 0) {
    Write-Host "Deploy failed!" -ForegroundColor Red
    exit 1
}

# [3/3] 결과 확인
Write-Host ""
Write-Host "[3/3] DEV Deploy complete!" -ForegroundColor Green
$url = gcloud run services describe $ServiceName --region $Region --format "value(status.url)" 2>$null

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  [DEV] URL: $url" -ForegroundColor Yellow
Write-Host "  Chat:       $url/"
Write-Host "  Scenario:   $url/manager"
Write-Host "  History:    $url/history"
Write-Host "  Settings:   $url/settings"
Write-Host "  Guidelines: $url/guidelines"
Write-Host "  RLHF:       $url/rlhf_manager.html"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Storage: Cloud SQL '$DbName' on $SqlInstance (DEV DB)" -ForegroundColor Yellow
Write-Host "운영 DB(medical_app)와 완전히 분리됩니다." -ForegroundColor DarkGray
Write-Host ""
Write-Host "테스트 완료 후 운영 반영:" -ForegroundColor Cyan
Write-Host "  git checkout main && git merge feature/xxx && `$env:DB_PASSWORD='...'; .\deploy.ps1"
Write-Host ""
