@echo off
REM ============================================================================
REM Falcon AI Vision - Environment Cleanup
REM Safely removes old, redundant virtual environments
REM ============================================================================

setlocal enabledelayedexpansion

color 0C
cls

echo.
echo ============================================================================
echo   Falcon AI Vision - Environment Cleanup
echo ============================================================================
echo.

set PROJECT_DIR=%~dp0
set VENV_MAIN=%PROJECT_DIR%.venv
set TO_DELETE=.venv-3.11 .venv2 .venv_prod

echo Current project directory:
echo   %PROJECT_DIR%
echo.

echo Main virtual environment (KEPT):
echo   %VENV_MAIN%
echo.

echo Old/redundant environments (TO BE DELETED):
for %%d in (%TO_DELETE%) do (
    set FULL_PATH=%PROJECT_DIR%%%d
    if exist "!FULL_PATH!" (
        echo   - %%d (found)
    )
)
echo.

echo WARNING: This will permanently delete old virtual environments!
echo.
set /p CONFIRM=Proceed with cleanup? (YES/no): 
if /i not "!CONFIRM!"=="YES" (
    if /i not "!CONFIRM!"=="Y" (
        echo Cleanup cancelled.
        pause
        exit /b 0
    )
)

echo.
echo Cleaning up...
echo.

for %%d in (%TO_DELETE%) do (
    set FULL_PATH=%PROJECT_DIR%%%d
    if exist "!FULL_PATH!" (
        echo Removing %%d...
        rmdir /s /q "!FULL_PATH!"
        if errorlevel 1 (
            echo   [WARNING] Could not delete %%d - may be in use
        ) else (
            echo   [OK] Deleted %%d
        )
    )
)

echo.
echo ============================================================================
echo   Cleanup Complete!
echo ============================================================================
echo.
echo Next steps:
echo   1. Run SETUP_BACKEND.bat to ensure .venv is properly configured
echo   2. Run RUN_BACKEND.bat to start the backend
echo.
pause
