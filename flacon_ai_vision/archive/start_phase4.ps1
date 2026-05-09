# PHASE 4 - QUICK START SCRIPT (Windows)
# Run this to validate and start the system

Write-Host "🚀 Phase 4: E2E Integration & Validation" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Validate
Write-Host "1️⃣  Running pre-flight validation..." -ForegroundColor Yellow
python phase4_validate.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Validation failed. Please fix errors above." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "2️⃣  Starting FastAPI server..." -ForegroundColor Yellow
Write-Host "   Opening: http://localhost:5003" -ForegroundColor Green
Write-Host "   Client:  file:///C:/Users/boufm/Desktop/eye_of_falcon/eye-of-falcon/phase4_client.html" -ForegroundColor Green
Write-Host ""
Write-Host "   Press Ctrl+C to stop the server" -ForegroundColor Cyan
Write-Host ""

# Step 2: Start server
python -m uvicorn vms.backend.main:app --reload --host 0.0.0.0 --port 5003
