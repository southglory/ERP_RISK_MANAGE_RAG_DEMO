@echo off
chcp 65001 >nul
echo [AI Playground] 서비스 종료 중...

cd /d "%~dp0deploy\vllm"
docker compose down

cd /d "%~dp0deploy\infra"
docker compose down

echo [완료] 서비스 종료됨.
pause
