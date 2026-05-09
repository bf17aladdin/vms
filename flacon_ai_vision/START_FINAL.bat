@echo off
setlocal

set "BASE_DIR=%~dp0"
echo Starting Falcon AI Vision via START_FINAL.ps1...

powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE_DIR%START_FINAL.ps1"

if errorlevel 1 (
  echo.
  echo Startup failed. Check backend startup logs, database connectivity, and port conflicts, then try again.
  pause
)
