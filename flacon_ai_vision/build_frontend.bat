@echo off
REM Falcon AI Vision - Build Frontend Script
REM Compile the React/Vite frontend

setlocal enabledelayedexpansion

echo.
echo ====================================================================
echo   ^>^> Falcon AI Vision - Frontend Build
echo ====================================================================
echo.

cd /d "%~dp0"
set "PLATFORM_DIR=%~dp0falcon-ai-vision-platform"
set "FRONTEND_DIR=%PLATFORM_DIR%\frontend"

REM Check npm
where npm >nul 2>nul
if %errorlevel% neq 0 (
    echo. ERROR: npm not found! Install Node.js first
    pause
    exit /b 1
)

echo 1. Cleaning previous build...
if exist "%FRONTEND_DIR%\dist" (
    rmdir /s /q "%FRONTEND_DIR%\dist"
    echo    ^✓ Cleaned previous build
) else (
    echo    OK No previous build found
)

echo.
echo 2. Building frontend...
echo.

cd /d "%FRONTEND_DIR%"
call npm run build

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Build failed!
    pause
    exit /b 1
)

cd /d "%~dp0"

echo.
echo ====================================================================
echo   ^✓ Frontend build completed successfully!
echo ====================================================================
echo.
echo Next steps:
echo   1. Start the backend server:
echo      python -m uvicorn vms.backend.main:app --reload
echo.
echo   2. Open browser:
echo      http://localhost:5003/
echo.
pause
