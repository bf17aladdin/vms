# ===================================================================
# Phase 2 - Camera Management Test Script (PowerShell)
# Test automatisé pour la gestion des caméras
# ===================================================================

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║         Phase 2 - Camera Management Tests                      ║" -ForegroundColor Cyan
Write-Host "║         Testing test-connection endpoints                      ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Vérifier si Python est disponible
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✓ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Python not found in PATH" -ForegroundColor Red
    Write-Host "  Please ensure Python is installed and in your PATH" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Vérifier si le serveur est en cours d'exécution
Write-Host "Checking if server is running on http://localhost:5000..." -ForegroundColor Yellow

try {
    $response = Invoke-WebRequest -Uri "http://localhost:5001/api/auth/login" `
                                   -Method POST `
                                   -ContentType "application/json" `
                                   -Body '{"username":"test","password":"test"}' `
                                   -TimeoutSec 3 `
                                   -ErrorAction SilentlyContinue

    Write-Host "✓ Server is running" -ForegroundColor Green
} catch {
    Write-Host "✗ Server not responding on localhost:5000" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please start the server first:" -ForegroundColor Yellow
    Write-Host "  1. Open a terminal" -ForegroundColor White
    Write-Host "  2. Run: start_unified.bat" -ForegroundColor White
    Write-Host "  3. Wait for 'Uvicorn running on http://0.0.0.0:5000'" -ForegroundColor White
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "Running test suite..." -ForegroundColor Yellow
Write-Host ""

# Exécuter les tests
python test_phase2_camera_management.py
$testResult = $LASTEXITCODE

Write-Host ""

if ($testResult -eq 0) {
    Write-Host "✓ All tests completed successfully!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Check the documentation: PHASE2_CAMERA_MANAGEMENT.md" -ForegroundColor White
    Write-Host "  2. Implement Phase 2.1 (Dashboard): PHASE2_ADMIN_INTEGRATION.md" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "✗ Tests failed with error code $testResult" -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:" -ForegroundColor Yellow
    Write-Host "  1. Ensure the server is still running" -ForegroundColor White
    Write-Host "  2. Check vms/backend/models.py for connection_status column" -ForegroundColor White
    Write-Host "  3. Try: python backend/init_db.py (to reset database)" -ForegroundColor White
    Write-Host ""
}

Read-Host "Press Enter to exit"
