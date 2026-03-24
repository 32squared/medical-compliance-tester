FROM python:3.12-slim

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 전체 복사 (.dockerignore가 불필요 파일 제외)
COPY . .

# 로컬 실행 시 /data 폴백 디렉토리
RUN mkdir -p /data

# Cloud Run은 PORT 환경변수 사용
ENV PORT=8080
ENV DB_PATH=/data/app.db
ENV DATA_DIR=/data

EXPOSE 8080

CMD ["python", "proxy_server.py", "--port", "8080"]
