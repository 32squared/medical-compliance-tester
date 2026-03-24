param(
    [string]$ProjectId = "",
    [string]$Region = "asia-northeast3",
    [string]$ServiceName = "medical-compliance-tester"
)

Write-Host "=== Medical Compliance Tester - Cloud Run Deploy ===" -ForegroundColor Cyan

if (-not $ProjectId) {
    $ProjectId = gcloud config get-value project 2>$null
    if (-not $ProjectId) {
        Write-Host "Set your GCP project: gcloud config set project YOUR_PROJECT_ID" -ForegroundColor Red
        exit 1
    }
}
Write-Host "Project: $ProjectId"
Write-Host "Region: $Region"
Write-Host "Service: $ServiceName"
Write-Host ""

Write-Host "[1/3] Building Docker image..." -ForegroundColor Yellow
gcloud builds submit --tag "gcr.io/$ProjectId/$ServiceName" .
if ($LASTEXITCODE -ne 0) { Write-Host "Build failed!" -ForegroundColor Red; exit 1 }
Write-Host "Build done!" -ForegroundColor Green

Write-Host "[2/3] Deploying to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy $ServiceName `
    --image "gcr.io/$ProjectId/$ServiceName" `
    --region $Region `
    --platform managed `
    --allow-unauthenticated `
    --memory 512Mi `
    --timeout 300 `
    --max-instances 3 `
    --set-env-vars "PORT=8080"

if ($LASTEXITCODE -ne 0) { Write-Host "Deploy failed!" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "[3/3] Deploy complete!" -ForegroundColor Green
$url = gcloud run services describe $ServiceName --region $Region --format "value(status.url)" 2>$null
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  URL: $url" -ForegroundColor Green
Write-Host "  Chat:     $url/"
Write-Host "  Scenario: $url/manager"
Write-Host "  History:  $url/history"
Write-Host "  Settings: $url/settings"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Note: settings.json and test_history.json reset on container restart." -ForegroundColor Yellow
Write-Host "For persistent storage, integrate Cloud Storage or Firestore." -ForegroundColor Yellow
