@echo off
REM This script runs silently via start-hidden.vbs

REM Kill any existing instances first
taskkill /F /IM python.exe 2>nul
taskkill /F /IM node.exe 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do taskkill /F /PID %%a 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /F /PID %%a 2>nul
timeout /t 1 /nobreak > nul

REM Change to script directory
cd /d "%~dp0"

REM Install Python dependencies (quick check)
python -m pip install -r requirements.txt --quiet 2>nul

REM Install frontend dependencies if needed
if not exist "frontend\node_modules" (
    cd frontend
    call npm install
    cd ..
)

REM Start backend server (background)
start /B python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 > nul 2>&1

REM Wait for backend to start
timeout /t 2 /nobreak > nul

REM Start frontend (background)
cd frontend
start /B cmd /c "npm run dev > nul 2>&1"
cd ..

REM Wait a moment then open browser
timeout /t 3 /nobreak > nul
start http://localhost:5173
