@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo Smart Energy Forecasting -^> http://127.0.0.1:8005
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start "" http://127.0.0.1:8005"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8005
