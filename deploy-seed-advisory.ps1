# 2차 자문 준비 데이터를 DEV(또는 지정 DB)에 투입하는 Cloud Run Job.
#
# Cloud SQL 인스턴스가 private IP 만 갖고 있어 로컬에서 직접 넣을 수 없다.
# 그래서 방금 빌드한 이미지로 Job 을 만들어 GCP 안에서 seed_advisory.py 를 돌린다.
# DB 비밀번호는 Secret Manager 에서 가져오며 화면에 출력하지 않는다.
param(
    [string]$ProjectId  = "medical-compliance-tester",
    [string]$Region     = "asia-northeast3",
    [string]$Image      = "gcr.io/medical-compliance-tester/medical-compliance-tester-dev",
    [string]$JobName    = "seed-advisory-dev",
    [string]$SqlInstance = "medical-db",
    [string]$DbName     = "medical_app_dev",
    [string]$DbPassword = "",
    [switch]$Execute
)

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"

if (-not $DbPassword) { $DbPassword = $env:DB_PASSWORD }
if (-not $DbPassword) {
    Write-Host "Secret Manager에서 DB 비밀번호를 가져옵니다..." -ForegroundColor Yellow
    $DbPassword = gcloud secrets versions access latest --secret=db-password --project=$ProjectId 2>$null
}
if (-not $DbPassword) {
    Write-Host "DB 비밀번호를 찾을 수 없습니다." -ForegroundColor Red
    exit 1
}
Write-Host "DB Password:  ****" -ForegroundColor Green

$DatabaseUrl = "postgresql://app_user:${DbPassword}@/${DbName}?host=/cloudsql/${SqlConnection}"

Write-Host ""
Write-Host "Job:    $JobName" -ForegroundColor Cyan
Write-Host "Image:  $Image"
Write-Host "DB:     $DbName"
Write-Host ""

$exists = gcloud run jobs list --region $Region --project $ProjectId --format "value(metadata.name)" 2>$null |
          Select-String -Pattern "^${JobName}$"

# Cloud SQL 이 private IP(10.12.0.3) 라 Job 도 서비스와 같은 VPC 커넥터를 타야 한다.
# 이게 없으면 /cloudsql 소켓이 열려도 3307 로 나가지 못해 i/o timeout 이 난다.
$common = @(
    "--region", $Region, "--project", $ProjectId,
    "--image", $Image,
    "--set-cloudsql-instances", $SqlConnection,
    "--vpc-connector", "medical-connector",
    "--vpc-egress", "private-ranges-only",
    "--set-env-vars", "RUN_MODE=seed_advisory,DATABASE_URL=$DatabaseUrl",
    "--max-retries", "0",
    "--task-timeout", "900s",
    "--memory", "2Gi"
)

if ($exists) {
    Write-Host "기존 Job 갱신..." -ForegroundColor Yellow
    gcloud run jobs update $JobName @common | Out-Null
} else {
    Write-Host "Job 생성..." -ForegroundColor Yellow
    gcloud run jobs create $JobName @common | Out-Null
}
if ($LASTEXITCODE -ne 0) { Write-Host "Job 생성/갱신 실패" -ForegroundColor Red; exit 1 }
Write-Host "Job 준비 완료." -ForegroundColor Green

if ($Execute) {
    Write-Host ""
    Write-Host "Job 실행 (완료까지 대기)..." -ForegroundColor Yellow
    gcloud run jobs execute $JobName --region $Region --project $ProjectId --wait
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Job 실행 실패 — 로그를 확인하세요." -ForegroundColor Red
        exit 1
    }
    Write-Host "시딩 완료." -ForegroundColor Green
}
