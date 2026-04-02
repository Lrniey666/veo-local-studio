@echo off
cd /d "%~dp0\.."
docker compose up --build -d
start http://127.0.0.1:7860
echo Veo 3.1 Local Studio is running on http://127.0.0.1:7860
