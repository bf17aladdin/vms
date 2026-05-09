# Installation des dépendances Python pour testing local
$ErrorActionPreference = "Continue"

Write-Host "🔧 Activating venv..." -ForegroundColor Green
& .\venv_test\Scripts\Activate.ps1

Write-Host "📦 Installing dependencies from requirements.txt..." -ForegroundColor Green
pip install -r requirements.txt

Write-Host "`n✅ Installation complete!" -ForegroundColor Green

# Test imports
Write-Host "`n🧪 Testing imports..." -ForegroundColor Cyan
python -c "from fastapi import FastAPI; from pydantic import BaseModel; from email_validator import validate_email; from sqlalchemy import create_engine; print('✅ All imports successful!')"

if ($?) {
    Write-Host "`n✨ Environment ready for testing!`n" -ForegroundColor Green
} else {
    Write-Host "`n❌ Import test failed - check installation`n" -ForegroundColor Red
}
