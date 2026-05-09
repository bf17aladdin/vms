@echo off
REM Falcon AI Vision - Complete Startup
REM Builds frontend and starts backend

setlocal enabledelayedexpansion

echo.
echo ====================================================================
echo   ^>^> Falcon AI Vision - Complete Startup
echo ====================================================================
echo.

cd /d "%~dp0"

REM Step 1: Build frontend
echo Step 1/2: Building frontend...
echo.
cd vms\frontend
call npm run build

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Frontend build failed!
    cd /d "%~dp0"
    pause
    exit /b 1
)

cd /d "%~dp0"

echo.
echo Step 2/2: Starting backend server...
echo.
echo ====================================================================
echo.
echo   ^✓ Frontend built successfully
echo   ^✓ Starting API server...
echo.
echo   Access the application:
echo      Frontend: http://localhost:5003/
echo      API Docs: http://localhost:5003/docs
echo.
echo   Press Ctrl+C to stop the server
echo.
echo ====================================================================
echo.

REM Start server
call .venv\Scripts\activate.bat
python -m uvicorn vms.backend.main:app --reload --host 127.0.0.1 --port 5003

pause
