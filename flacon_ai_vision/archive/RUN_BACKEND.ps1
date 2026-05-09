# Falcon AI Vision - PowerShell Backend Launcher
# Clean, stable startup script for the FastAPI backend

param(
    [switch]$Setup = $false
)

# Get paths
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommandPath
$BackendDir = Join-Path $ProjectDir "vms" "backend"
$VenvDir = Join-Path $ProjectDir ".venv"
$Python = Join-Path $VenvDir "Scripts" "python.exe"
$Port = 5000
$Host = "127.0.0.1"

Write-Host ""
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "   Falcon AI Vision - Backend Server" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "   Project Dir:  $ProjectDir"
Write-Host "   Backend Dir:  $BackendDir"
Write-Host "   Python:       $Python"
Write-Host "   URL:          http://$Host`:$Port"
Write-Host "   Docs:         http://$Host`:$Port/docs"
Write-Host ""

# Check virtual environment
if (-not (Test-Path $Python)) {
    Write-Host "[ERROR] Virtual environment not found!" -ForegroundColor Red
    Write-Host "Please run SETUP_BACKEND.bat first to set up the environment." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Check backend exists
if (-not (Test-Path (Join-Path $BackendDir "main.py"))) {
    Write-Host "[ERROR] Backend main.py not found at $BackendDir\main.py" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "   Starting FastAPI backend..." -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Start the backend
Set-Location $ProjectDir
& $Python -m uvicorn vms.backend.main:app --host $Host --port $Port --reload

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Backend failed to start" -ForegroundColor Red
    Write-Host "Check the error messages above" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
