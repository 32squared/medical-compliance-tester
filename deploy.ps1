param(
    [string]$ProjectId = "medical-compliance-tester",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "medical-compliance-tester",
    [string]$SqlInstance = "medical-db",
    [string]$DbPassword = "",
    # 온톨로지 기반 v3 판정 병존 실행. 켜면 답변 1건당 판정 모델 호출이 2회 늘어난다.
    [switch]$EvalV3,
    [string]$EvalV3Model = ""
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

# --set-env-vars 는 기존 환경변수를 통째로 교체한다. v3 스위치도 여기서 함께 넘겨야 한다.
# 구분자는 기본값(',') 그대로 둔다 — DB 비밀번호에 ',' 가 없다는 전제는 이 스크립트가
# 원래부터 깔고 있던 것이라, 여기서 새로 생기는 위험은 없다.
$EnvPairs = @("DATABASE_URL=$DatabaseUrl")
if ($EvalV3) {
    $EnvPairs += "EVAL_V3=1"
    if ($EvalV3Model) { $EnvPairs += "EVAL_V3_MODEL=$EvalV3Model" }
    Write-Host "EVAL_V3:      ON (판정 모델 호출 +2회/답변)" -ForegroundColor Yellow
} else {
    Write-Host "EVAL_V3:      off (-EvalV3 로 켠다)" -ForegroundColor DarkGray
}
$EnvSpec = $EnvPairs -join ","

# [1/3] Docker 이미지 빌드
Write-Host "[1/3] Building Docker image..." -ForegroundColor Yellow
gcloud builds submit --tag "gcr.io/$ProjectId/$ServiceName" .
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "Build done!" -ForegroundColor Green

# [2/3] Cloud Run 배포 (Cloud SQL 연결)
#
# 환경변수는 --update-env-vars 로 갱신한다. --set-env-vars 는 기존 변수를 통째로 교체해서,
# 콘솔이나 수동으로 넣어 둔 OPENAI_API_KEY 가 배포 때마다 사라진다. 그러면 GPT 평가·문진 평가·
# PHR 정합성 평가가 조용히 멈추는데, 화면에는 오류가 아니라 '평가 없음' 으로만 보여 알아채기 어렵다.
Write-Host "[2/3] Deploying to Cloud Run with Cloud SQL..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --image "gcr.io/$ProjectId/$ServiceName" `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --memory 2Gi --cpu 1 `
    --timeout 900 `
    --min-instances 0 --max-instances 10 `
    --concurrency 5 `
    --execution-environment gen2 `
    --update-env-vars "$EnvSpec" `
    --add-cloudsql-instances $SqlConnection `
    --vpc-connector=medical-connector `
    --vpc-egress=all-traffic `
    --cpu-boost `
    --cpu-throttling `
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
