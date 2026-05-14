@echo off
chcp 65001 >nul
echo [AI Playground] 서비스 시작 중...

REM infra (pgvector + Langfuse + MinIO + ClickHouse + Redis)
cd /d "%~dp0deploy\infra"
docker compose up -d
if errorlevel 1 (
    echo [오류] infra 시작 실패.
    pause
    exit /b 1
)

REM vLLM + infinity-emb (GPU 필요)
cd /d "%~dp0deploy\vllm"
docker compose up -d
if errorlevel 1 (
    echo [오류] vllm 시작 실패.
    pause
    exit /b 1
)

echo.
echo [완료] 실행 중인 컨테이너:
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo.
echo 포트 안내:
echo   pgvector  : localhost:5432
echo   Langfuse  : localhost:3000
echo   MinIO     : localhost:9001  (langfuse / langfuse_minio)
echo   vLLM      : localhost:8000/v1
echo   infinity  : localhost:8001
echo.
echo 앱 실행: run.bat
pause
