@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul || (echo Python 3.10+ is needed. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH". & pause & exit /b 1)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" || (echo Python 3.10 or newer is needed. & pause & exit /b 1)

if not exist .venv\Scripts\python.exe (echo Setting up, first run only... & python -m venv .venv)
if not exist .env (copy .env.example .env >nul & echo Created .env. You can paste your free Groq key in the app.)
echo Installing requirements...
.venv\Scripts\python -m pip install --disable-pip-version-check -q -r requirements.txt || (echo Install failed. Check your internet connection and run start.bat again. & pause & exit /b 1)

set PORT=8005
set HOST=127.0.0.1
for /f "tokens=1,* delims==" %%a in ('findstr /b "PORT= HOST=" .env') do set %%a=%%b

start "" powershell -NoProfile -WindowStyle Hidden -Command "for($i=0;$i -lt 60;$i++){try{Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/health | Out-Null; Start-Process http://127.0.0.1:%PORT%; break}catch{Start-Sleep 1}}"
echo Open http://127.0.0.1:%PORT%  (close this window to stop)
.venv\Scripts\python -m uvicorn app.main:app --host %HOST% --port %PORT%
pause
