#!/bin/bash
echo "=== 나만의 주치의 - 테스트 서버 시작 ==="

# Python 확인
if command -v python3 &>/dev/null; then
    PY=python3
elif command -v python &>/dev/null; then
    PY=python
else
    echo "❌ Python이 설치되어 있지 않습니다."
    echo "   brew install python3 으로 설치해 주세요."
    exit 1
fi

echo "Python: $PY ($($PY --version 2>&1))"

# 스크립트가 있는 폴더로 이동
cd "$(dirname "$0")"
echo "폴더: $(pwd)"

# requests 설치
$PY -m pip install requests --break-system-packages 2>/dev/null || $PY -m pip install requests 2>/dev/null || true

# 기존 9000 포트 프로세스 종료
lsof -ti:9000 | xargs kill -9 2>/dev/null || true

echo ""
echo "✅ 서버 시작 중... (http://localhost:9000)"
echo "   종료하려면 Ctrl+C"
echo ""

# 브라우저 자동 열기 (1초 후)
(sleep 1 && open "http://localhost:9000") &

$PY proxy_server.py
