@echo off
cd /d "%~dp0"
title Falcon AI Vision - Full Rebuild Test

echo.
echo ===============================================================================
echo  Falcon AI Vision - Full Rebuild & Test
echo ===============================================================================
echo.

echo Step 1: Building Frontend...
python build_frontend.py
if errorlevel 1 (
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo Step 2: Starting Server (in background)...
start "Falcon AI Vision Server" python -m uvicorn vms.backend.main:app --reload --host 127.0.0.1 --port 5003
timeout /t 3 /nobreak

echo.
echo Step 3: Testing Frontend...
python full_rebuild_test.py
pause
