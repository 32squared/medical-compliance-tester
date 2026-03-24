param(
    [string]$ProjectId = "",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "medical-compliance-tester",
    [string]$BucketName = ""
)

Write-Host "=== Medical Compliance Tester - Cloud Run Deploy (SQLite + GCS) ===" -ForegroundColor Cyan

if (-not $ProjectId) {
    $ProjectId = gcloud config get-value project 2>$null
    if (-not $ProjectId) {
        Write-Host "Set your GCP project: gcloud config set project YOUR_PROJECT_ID" -ForegroundColor Red
        exit 1
    }
}
if (-not $BucketName) {
    $BucketName = "$ProjectId-medical-data"
}

Write-Host "Project:  $ProjectId"
Write-Host "Region:   $Region"
Write-Host "Service:  $ServiceName"
Write-Host "Bucket:   gs://$BucketName"
Write-Host ""

# [0/4] GCS 버킷 생성 (최초 1회, 이미 있으면 skip)
Write-Host "[0/4] Checking GCS bucket..." -ForegroundColor Yellow
$bucketExists = gcloud storage ls -b "gs://$BucketName" 2>$null
if (-not $bucketExists) {
    Write-Host "Creating bucket gs://$BucketName ..." -ForegroundColor Yellow
    gcloud storage buckets create "gs://$BucketName" `
        --location=$Region `
        --uniform-bucket-level-access
    if ($LASTEXITCODE -ne 0) { Write-Host "Bucket creation failed!" -ForegroundColor Red; exit 1 }
    Write-Host "Bucket created!" -ForegroundColor Green

    # 초기 가이드라인/위반규칙 파일 업로드
    if (Test-Path "guidelines.json") {
        gcloud storage cp guidelines.json "gs://$BucketName/guidelines.json"
    }
    if (Test-Path "violation_rules.json") {
        gcloud storage cp violation_rules.json "gs://$BucketName/violation_rules.json"
    }
} else {
    Write-Host "Bucket already exists." -ForegroundColor Green
}

# [1/4] Docker 이미지 빌드
Write-Host "[1/4] Building Docker image..." -ForegroundColor Yellow
gcloud builds submit --tag "gcr.io/$ProjectId/$ServiceName" .
if ($LASTEXITCODE -ne 0) { Write-Host "Build failed!" -ForegroundColor Red; exit 1 }
Write-Host "Build done!" -ForegroundColor Green

# [2/4] Cloud Run 배포 (GCS FUSE 볼륨 마운트)
Write-Host "[2/4] Deploying to Cloud Run with GCS volume mount..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --image "gcr.io/$ProjectId/$ServiceName" `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --memory 512Mi `
    --timeout 300 `
    --max-instances 3 `
    --execution-environment gen2 `
    --set-env-vars "PORT=8080,DB_PATH=/data/app.db,DATA_DIR=/data" `
    --add-volume "name=data-vol,type=cloud-storage,bucket=$BucketName" `
    --add-volume-mount "volume=data-vol,mount-path=/data"

if ($LASTEXITCODE -ne 0) { Write-Host "Deploy failed!" -ForegroundColor Red; exit 1 }

# [3/4] 결과 확인
Write-Host ""
Write-Host "[3/4] Deploy complete!" -ForegroundColor Green
$url = gcloud run services describe $ServiceName --region $Region --format "value(status.url)" 2>$null

# [4/4] 기존 데이터 마이그레이션 안내
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  URL: $url" -ForegroundColor Green
Write-Host "  Chat:       $url/"
Write-Host "  Scenario:   $url/manager"
Write-Host "  History:    $url/history"
Write-Host "  Settings:   $url/settings"
Write-Host "  Guidelines: $url/guidelines"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Storage: SQLite on GCS FUSE (gs://$BucketName)" -ForegroundColor Green
Write-Host "  - app.db: 자동 생성됨 (영구 보존)" -ForegroundColor Green
Write-Host "  - guidelines.json: 가이드라인 규칙" -ForegroundColor Green
Write-Host "  - violation_rules.json: 위반 규칙" -ForegroundColor Green
Write-Host ""
Write-Host "기존 데이터 마이그레이션:" -ForegroundColor Yellow
Write-Host "  python migrate.py  (로컬에서 실행 후 app.db를 GCS에 업로드)" -ForegroundColor Yellow
Write-Host "  gcloud storage cp app.db gs://$BucketName/app.db" -ForegroundColor Yellow
