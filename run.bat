@echo off
REM Build the frontend and start the app on http://localhost:8000 (Windows)
cd /d "%~dp0"
echo [1/3] Installing Python packages...
python -m pip install -r backend\requirements.txt || goto :error
echo [2/3] Installing and building the web interface...
cd frontend
call npm install || goto :error
call npx vite build || goto :error
cd ..\backend
echo [3/3] Starting the app. Open http://localhost:8000 in your browser. Press Ctrl+C to stop.
python -m uvicorn structural.api:app --port 8000
goto :eof
:error
echo.
echo Something failed above. Check that Python 3.10+ and Node.js 18+ are installed and on PATH.
pause
