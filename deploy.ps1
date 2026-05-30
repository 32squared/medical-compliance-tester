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

# [0/3] Cloud SQL 인스턴스 상태 점검
Write-Host "[0/3] Checking Cloud SQL instance..." -ForegroundColor Yellow
$SqlStatus = gcloud sql instances describe $SqlInstance `
    --project=$ProjectId `
    --format="value(databaseVersion,state)" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $SqlStatus) {
    Write-Host "[ERROR] Cloud SQL 인스턴스 '$SqlInstance' 를 확인할 수 없습니다." -ForegroundColor Red
    Write-Host "        gcloud auth 또는 인스턴스 이름을 확인하세요."
    exit 1
}
$SqlParts = $SqlStatus -split "`t|`n| "
$SqlVersion = $SqlParts[0]
$SqlState   = $SqlParts[1]
Write-Host "  DB Version: $SqlVersion" -ForegroundColor Cyan
Write-Host "  DB State:   $SqlState" -ForegroundColor Cyan
if ($SqlState -ne "RUNNABLE") {
    Write-Host "[ERROR] Cloud SQL 인스턴스 상태가 RUNNABLE이 아닙니다 (현재: $SqlState). 배포를 중단합니다." -ForegroundColor Red
    exit 1
}
Write-Host "Cloud SQL 점검 완료!" -ForegroundColor Green
Write-Host ""

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

# [2.5/3] dev 태그를 방금 배포한 최신 리비전으로 이동
#   이 서비스는 트래픽이 특정 리비전에 고정되어 있어, deploy가 트래픽 0%의
#   스테이징 리비전을 새로 만든다. dev 미리보기 URL(https://dev---...)이 항상
#   최신 코드를 가리키도록 dev 태그를 새 리비전으로 옮긴다. 운영 트래픽은 무영향.
Write-Host "[2.5/3] Moving 'dev' tag to the newly deployed revision..." -ForegroundColor Yellow
$LatestRev = gcloud run revisions list --service $ServiceName --region $Region --project $ProjectId `
    --sort-by="~metadata.creationTimestamp" --limit 1 --format="value(metadata.name)" 2>$null
if ($LatestRev) {
    gcloud run services update-traffic $ServiceName --region $Region --project $ProjectId `
        --update-tags "dev=$LatestRev" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  dev tag -> $LatestRev  (운영 트래픽 무영향)" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] dev 태그 이동 실패. 수동 실행: gcloud run services update-traffic $ServiceName --region $Region --update-tags dev=$LatestRev" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [WARN] 최신 리비전 조회 실패 — dev 태그를 옮기지 못했습니다." -ForegroundColor Yellow
}

# [3/3] 결과 확인
Write-Host ""
Write-Host "[3/3] Deploy complete!" -ForegroundColor Green
$url = gcloud run services describe $ServiceName --region $Region --format "value(status.url)" 2>$null

# dev 미리보기 URL (방금 태그를 옮긴 최신 리비전)
$DevUrl = $null
try {
    $svcJson = gcloud run services describe $ServiceName --region $Region --project $ProjectId --format json 2>$null | ConvertFrom-Json
    $DevUrl = ($svcJson.status.traffic | Where-Object { $_.tag -eq 'dev' } | Select-Object -First 1).url
} catch {}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  URL (운영 100%): $url" -ForegroundColor Green
if ($DevUrl) { Write-Host "  DEV (미리보기, 최신코드): $DevUrl" -ForegroundColor Magenta }
Write-Host "  Chat:       $url/"
Write-Host "  Scenario:   $url/manager"
Write-Host "  History:    $url/history"
Write-Host "  Settings:   $url/settings"
Write-Host "  Guidelines: $url/guidelines"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Storage: Cloud SQL PostgreSQL ($SqlConnection)" -ForegroundColor Green
Write-Host ""
