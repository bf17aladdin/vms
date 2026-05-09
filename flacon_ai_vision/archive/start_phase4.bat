@echo off
REM PHASE 4 - QUICK START SCRIPT (Windows Batch)
REM Run this to validate and start the system

cls
echo.
echo     ========================================
echo     Phase 4: E2E Integration ^& Validation
echo     ========================================
echo.

REM Step 1: Validate
echo [1] Running pre-flight validation...
python phase4_validate.py
if errorlevel 1 (
    echo.
    echo !!! Validation failed. Please fix errors above.
    pause
    exit /b 1
)

echo.
echo [2] Starting FastAPI server...
echo     Server:  http://localhost:5003
echo     Client:  file:///C:/Users/boufm/Desktop/eye_of_falcon/eye-of-falcon/phase4_client.html
echo.
echo     Press Ctrl+C to stop the server
echo.

REM Step 2: Start server
python -m uvicorn vms.backend.main:app --reload --host 0.0.0.0 --port 5003

pause
