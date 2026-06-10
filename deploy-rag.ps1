# RAG 독립 HTTP 서비스 배포 (저장소 분리 Phase 3, additive)
# rag_server.py 를 RUN_MODE=rag 로 단독 Cloud Run 서비스에 배포한다.
# 호스트(테스트 시스템)는 RAG_SERVICE_URL 을 이 서비스 URL 로 설정해 리버스 프록시한다.
# 기본 DEV DB(medical_app_dev). -Prod 스위치로만 운영 DB.
# ※ 검증은 나중에: 배포 후 호스트에 RAG_SERVICE_URL 을 주면 분리 모드가 활성화된다.
param(
    [string]$ProjectId   = "medical-compliance-tester",
    [string]$Region      = "asia-northeast3",
    [string]$ServiceName = "medical-rag-dev",
    [string]$SqlInstance = "medical-db",
    [string]$DbName      = "medical_app_dev",
    [string]$DbPassword  = "",
    [string]$TrustSecret = "",
    [switch]$Prod
)

if ($Prod) {
    $DbName = "medical_app"
    if ($ServiceName -eq "medical-rag-dev") { $ServiceName = "medical-rag" }
}

Write-Host "=== RAG 독립 서비스 배포 (Phase 3) ===" -ForegroundColor Cyan
Write-Host "Service: $ServiceName"
Write-Host "DB:      $DbName  $(if ($DbName -eq 'medical_app') { '[운영]' } else { '[DEV]' })"
Write-Host ""

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"
$ImageUri      = "gcr.io/${ProjectId}/${ServiceName}"

# ── DB 비밀번호 ──
if (-not $DbPassword) { $DbPassword = $env:DB_PASSWORD }
if (-not $DbPassword) {
    try { $DbPassword = gcloud secrets versions access latest --secret=db-password --project=$ProjectId 2>$null } catch {}
}
if (-not $DbPassword) {
    Write-Host "[ERROR] DB 비밀번호 없음. -DbPassword 또는 `$env:DB_PASSWORD 지정." -ForegroundColor Red
    exit 1
}
Write-Host "DB Password: ****" -ForegroundColor Green

$DatabaseUrl = "postgresql://app_user:${DbPassword}@/${DbName}?host=/cloudsql/${SqlConnection}"

# ── 이미지 빌드 ──
Write-Host "[1/2] Building image..." -ForegroundColor Yellow
gcloud builds submit --tag $ImageUri .
if ($LASTEXITCODE -ne 0) { Write-Host "Build failed!" -ForegroundColor Red; exit 1 }

# ── 배포 (RUN_MODE=rag) ──
Write-Host "[2/2] Deploying RAG service..." -ForegroundColor Yellow
# 전체 env 변수 레퍼런스: docs/env_reference.md (섹션 3 — RAG 서비스)
$EnvVars = "DATABASE_URL=$DatabaseUrl,RUN_MODE=rag,RAG_ENABLED=true,RAG_LLM_MODEL=gpt-5.4-mini,RAG_LLM_FALLBACK_MODEL=gpt-5.4-mini,RAG_GUARDRAIL_FP_FILTER=true,LLM_REASONING_EFFORT=low"
if ($TrustSecret) { $EnvVars = "$EnvVars,RAG_TRUST_SECRET=$TrustSecret" }

gcloud run deploy $ServiceName `
    --image $ImageUri `
    --region $Region `
    --platform managed `
    --no-allow-unauthenticated `
    --memory 2Gi --cpu 1 `
    --timeout 900 `
    --min-instances 0 --max-instances 3 `
    --concurrency 5 `
    --execution-environment gen2 `
    --set-env-vars $EnvVars `
    --set-secrets "OPENAI_API_KEY=openai-api-key:latest,DB_PASSWORD=db-password:latest" `
    --add-cloudsql-instances $SqlConnection `
    --vpc-connector=medical-connector `
    --vpc-egress=private-ranges-only `
    --cpu-boost `
    --no-cpu-throttling `
    --clear-volumes `
    --clear-volume-mounts
if ($LASTEXITCODE -ne 0) { Write-Host "Deploy failed!" -ForegroundColor Red; exit 1 }

$url = gcloud run services describe $ServiceName --region $Region --format "value(status.url)" 2>$null
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  RAG 서비스 배포 완료: $ServiceName" -ForegroundColor Green
Write-Host "  URL: $url" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "다음(분리 모드 활성화): 호스트 서비스에 RAG_SERVICE_URL 주입" -ForegroundColor Yellow
Write-Host "  gcloud run services update <host-service> --region $Region \" -ForegroundColor Gray
Write-Host "    --update-env-vars RAG_SERVICE_URL=$url$(if ($TrustSecret) { ',RAG_TRUST_SECRET=****' })" -ForegroundColor Gray
Write-Host ""
Write-Host "※ RAG_SERVICE_URL 미설정 시 호스트는 기존 in-process 경로 유지(현재 동작 불변)." -ForegroundColor DarkGray
