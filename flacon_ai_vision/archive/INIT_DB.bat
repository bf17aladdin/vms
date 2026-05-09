@echo off
REM ============================================================
REM  INIT_DB.bat - Initialiser la base de données Falcon AI Vision
REM ============================================================

setlocal enabledelayedexpansion

REM Couleurs
for /F %%a in ('copy /Z "%~f0" nul') do set "BS=%%a"

echo.
echo ============================================================
echo  [OK] Falcon AI Vision - Database Initialization
echo ============================================================
echo.

REM Déterminer le répertoire du script
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "VENV_PYTHON=!PROJECT_DIR!\.venv\Scripts\python.exe"
set "BACKEND_DIR=!PROJECT_DIR!\vms\backend"

echo  Project Directory  : !PROJECT_DIR!
echo  Backend Folder     : !BACKEND_DIR!
echo  Python (venv)      : !VENV_PYTHON!
echo.

REM Vérifier que Python venv existe
if not exist "!VENV_PYTHON!" (
    echo [!] Python virtual environment not found at: !VENV_PYTHON!
    echo [*] Please run setup.bat first to create the environment.
    goto :eof
)

REM Aller au répertoire backend
cd /d "!BACKEND_DIR!"

echo ============================================================
echo  [*] Creating tables from SQLAlchemy models...
echo ============================================================
echo.

REM Exécuter seed_db.py
"!VENV_PYTHON!" seed_db.py

if !ERRORLEVEL! neq 0 (
    echo.
    echo [!] Error during database initialization
    echo.
    pause
    goto :eof
)

echo.
echo ============================================================
echo  [✓] Database initialization completed!
echo ============================================================
echo.
echo  Database file: !BACKEND_DIR!\falcon_ai_vision.db
echo.
echo  Next steps:
echo  1. Start the server: RUN_SERVER.bat
echo  2. Login with: admin / admin123
echo  3. Access dashboard: http://127.0.0.1:8001/
echo.
pause
