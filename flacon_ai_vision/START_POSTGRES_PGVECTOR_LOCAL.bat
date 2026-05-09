@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

set "PS1_SCRIPT=scripts\start_postgres_pgvector_local.ps1"
if not exist "%PS1_SCRIPT%" (
  echo [ERROR] Script introuvable: %PS1_SCRIPT%
  exit /b 1
)

set "DB_HOST=127.0.0.1"
set "DB_PORT=5434"
set "DB_USER=falcon"
set "DB_PASSWORD=eye_of_falcon_pwd"
set "DB_NAME=eye_of_falcon"
set "RUN_MIGRATIONS=0"
set "START_APP=0"
set "START_SCRIPT=START_FINAL.ps1"

:parse_args
if "%~1"=="" goto run
if /i "%~1"=="--host" (
  set "DB_HOST=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--port" (
  set "DB_PORT=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--user" (
  set "DB_USER=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--password" (
  set "DB_PASSWORD=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--db" (
  set "DB_NAME=%~2"
  shift
  shift
  goto parse_args
)
if /i "%~1"=="--migrate" (
  set "RUN_MIGRATIONS=1"
  shift
  goto parse_args
)
if /i "%~1"=="--start-app" (
  set "START_APP=1"
  shift
  goto parse_args
)
if /i "%~1"=="--help" goto help

echo [WARN] Argument ignore: %~1
shift
goto parse_args

:run
echo [1/2] Tentative de demarrage du service PostgreSQL local...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $svcs = Get-Service | Where-Object { $_.Name -match '^postgresql' -or $_.DisplayName -match 'PostgreSQL' }; foreach ($s in $svcs) { if ($s.Status -ne 'Running') { Start-Service -Name $s.Name -ErrorAction Stop; Write-Host ('Service demarre: ' + $s.Name) } }; exit 0 } catch { Write-Warning $_.Exception.Message; exit 0 }"

echo [2/2] Verification PostgreSQL + activation pgvector...
set "MIG_SWITCH="
if "%RUN_MIGRATIONS%"=="1" set "MIG_SWITCH=-RunMigrations"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1_SCRIPT%" ^
  -DbHost "%DB_HOST%" ^
  -DbPort %DB_PORT% ^
  -DbUser "%DB_USER%" ^
  -DbPassword "%DB_PASSWORD%" ^
  -DbName "%DB_NAME%" ^
  -EnsurePgvector %MIG_SWITCH%

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] Echec initialisation PostgreSQL/pgvector.
  echo Verifiez le port, les credentials et l'installation pgvector locale.
  exit /b %EXIT_CODE%
)

echo.
echo [OK] PostgreSQL local pret avec pgvector.
echo DATABASE_URL=postgresql+psycopg://%DB_USER%:%DB_PASSWORD%@%DB_HOST%:%DB_PORT%/%DB_NAME%
echo FACE_PGVECTOR_ENABLED=true
echo.
echo Pour activer en session PowerShell:
echo   $env:DATABASE_URL='postgresql+psycopg://%DB_USER%:%DB_PASSWORD%@%DB_HOST%:%DB_PORT%/%DB_NAME%'
echo   $env:FACE_PGVECTOR_ENABLED='true'
echo.
echo Ce script prepare PostgreSQL/pgvector uniquement.
echo Utilisez --start-app pour lancer ensuite backend + frontend en mode dev.
if not "%START_APP%"=="1" exit /b 0

if not exist "%START_SCRIPT%" (
  echo [ERROR] Script introuvable: %START_SCRIPT%
  exit /b 1
)

echo.
echo [3/3] Demarrage Falcon AI Vision en mode dev...
set "DATABASE_URL=postgresql+psycopg://%DB_USER%:%DB_PASSWORD%@%DB_HOST%:%DB_PORT%/%DB_NAME%"
set "FACE_PGVECTOR_ENABLED=true"
set "APP_ENV=development"
set "ENVIRONMENT=development"
set "SERVE_FRONTEND_FROM_BACKEND=false"
if not defined RELOAD set "RELOAD=true"
echo Backend/API: 127.0.0.1:5003
echo Frontend: localhost:3000
echo Frontend sur backend 5003: desactive
powershell -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%"
exit /b %ERRORLEVEL%

:help
echo Usage:
echo   START_POSTGRES_PGVECTOR_LOCAL.bat [--host 127.0.0.1] [--port 5433] [--user falcon] [--password eye_of_falcon_pwd] [--db eye_of_falcon] [--migrate] [--start-app]
echo.
echo Exemples:
echo   START_POSTGRES_PGVECTOR_LOCAL.bat
echo   START_POSTGRES_PGVECTOR_LOCAL.bat --migrate
echo   START_POSTGRES_PGVECTOR_LOCAL.bat --migrate --start-app
echo   START_POSTGRES_PGVECTOR_LOCAL.bat --port 5432 --user postgres --password secret --db eye_of_falcon
exit /b 0
