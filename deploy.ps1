param(
    [string]$ProjectId = "medical-compliance-tester",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "medical-compliance-tester",
    [string]$SqlInstance = "medical-db",
    [string]$DbPassword = ""
)

Write-Host "=== Medical Compliance Tester - Cloud Run Deploy (Cloud SQL) ===" -ForegroundColor Cyan

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"

Write-Host "Project:      $ProjectId"
Write-Host "Region:       $Region"
Write-Host "Service:      $ServiceName"
Write-Host "Cloud SQL:    $SqlConnection"
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
    Write-Host '  1. Secret Manager (권장): echo -n "password" | gcloud secrets create db-password --data-file=-'
    Write-Host '  2. 파라미터: .\deploy.ps1 -DbPassword "password"'
    Write-Host '  3. 환경변수: $env:DB_PASSWORD = "password"; .\deploy.ps1'
    exit 1
}
Write-Host "DB Password:  ****" -ForegroundColor Green

$DatabaseUrl = "postgresql://app_user:${DbPassword}@/medical_app?host=/cloudsql/${SqlConnection}"

# [1/3] Docker 이미지 빌드
Write-Host "[1/3] Building Docker image..." -ForegroundColor Yellow
gcloud builds submit --tag "gcr.io/$ProjectId/$ServiceName" .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "Build done!" -ForegroundColor Green

# [2/3] Cloud Run 배포 (Cloud SQL 연결)
Write-Host "[2/3] Deploying to Cloud Run with Cloud SQL..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --image "gcr.io/$ProjectId/$ServiceName" `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --memory 2Gi --cpu 2 `
    --timeout 900 `
    --min-instances 1 --max-instances 10 `
    --concurrency 10 `
    --execution-environment gen2 `
    --set-env-vars "DATABASE_URL=$DatabaseUrl" `
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
Write-Host "[3/3] Deploy complete!" -ForegroundColor Green
$url = gcloud run services describe $ServiceName --region $Region --format "value(status.url)" 2>$null

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  *** 운영 공식 URL (사용자/advisor 안내용) ***" -ForegroundColor Yellow
Write-Host "      $url" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Chat:       $url/"
Write-Host "  Scenario:   $url/manager"
Write-Host "  History:    $url/history"
Write-Host "  Settings:   $url/settings"
Write-Host "  Guidelines: $url/guidelines"
Write-Host "  Arena:      $url/arena"
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "참고: gcloud run deploy 출력의 'Service URL'은 다른 alias이며" -ForegroundColor DarkGray
Write-Host "      위 공식 URL과 같은 서비스를 가리킵니다 [둘 다 동작]" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Storage: Cloud SQL PostgreSQL ($SqlConnection)" -ForegroundColor Green
Write-Host ""
