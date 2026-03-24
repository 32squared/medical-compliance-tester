Write-Host "=== 나만의 주치의 - 테스트 서버 시작 ===" -ForegroundColor Cyan

# Python 확인
$py = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $py = "python"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $py = "python3"
} else {
    Write-Host "Python이 설치되어 있지 않습니다." -ForegroundColor Red
    Write-Host "https://www.python.org/downloads/ 에서 설치해 주세요."
    exit 1
}

$ver = & $py --version 2>&1
Write-Host "Python: $py ($ver)"

# 스크립트 폴더로 이동
Set-Location $PSScriptRoot
Write-Host "폴더: $(Get-Location)"

# 기존 9000 포트 프로세스 종료
$procs = Get-NetTCPConnection -LocalPort 9000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
if ($procs) {
    foreach ($procId in $procs) {
        Write-Host "기존 프로세스 종료 (PID: $procId)" -ForegroundColor Yellow
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

Write-Host ""
Write-Host "서버 시작 중... (http://localhost:9000)" -ForegroundColor Green
Write-Host "  채팅 테스터:    http://localhost:9000/"
Write-Host "  시나리오 관리:  http://localhost:9000/manager"
Write-Host "  설정:          http://localhost:9000/settings"
Write-Host "  종료하려면 Ctrl+C"
Write-Host ""

# 1초 후 브라우저 자동 열기
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 1
    Start-Process "http://localhost:9000"
} | Out-Null

# 서버 실행
& $py proxy_server.py
