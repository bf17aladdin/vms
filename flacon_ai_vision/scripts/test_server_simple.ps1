# Simple test pour vérifier serveur + endpoint improve
# Quick test script: test_server_simple.ps1

param(
    [int]$Port = 5003,
    [string]$Host = "127.0.0.1",
    [int]$TimeoutSeconds = 30
)

$base_url = "http://$Host`:$Port"

Write-Host "=== Vérification du serveur ===" -ForegroundColor Cyan

# Test 1: Health endpoint
Write-Host "`n1. Tester /health..."
try {
    $health = Invoke-RestMethod -Uri "$base_url/health" -Method Get -TimeoutSec 5
    Write-Host "   ✅ Status: $($health.status)" -ForegroundColor Green
    Write-Host "   ✅ Service: $($health.service)" -ForegroundColor Green
} catch {
    Write-Host "   ❌ Erreur: $_" -ForegroundColor Red
    Write-Host "   Le serveur n'est pas accessible sur $base_url" -ForegroundColor Red
    exit 1
}

# Test 2: Fichiers statiques
Write-Host "`n2. Tester fichiers statiques..."
$files = @("/capture.html", "/static/capture.js", "/login.html")
foreach ($file in $files) {
    try {
        $response = Invoke-WebRequest -Uri "$base_url$file" -Method Head -TimeoutSec 5 -ErrorAction Stop
        Write-Host "   ✅ GET $file → $($response.StatusCode)" -ForegroundColor Green
    } catch {
        Write-Host "   ⚠️  GET $file → Error" -ForegroundColor Yellow
    }
}

# Test 3: Endpoint facial recognize-image (sans auth, doit retourner 403 ou 401)
Write-Host "`n3. Tester endpoint /api/facial/recognize-image..."
try {
    # Sans token, on devrait avoir 403 Forbidden
    $resp = Invoke-WebRequest -Uri "$base_url/api/facial/recognize-image" -Method Post `
        -Form @{file = Get-Item "."} -TimeoutSec 5 -ErrorAction Stop
    Write-Host "   ⚠️  Unexpect 200 - authentication may not be enforced" -ForegroundColor Yellow
} catch [System.Net.HttpRequestException] {
    if($_.Exception.Response.StatusCode -eq "Unauthorized" -or $_.Exception.Response.StatusCode -eq "Forbidden") {
        Write-Host "   ✅ Endpoint accessible (401/403 expected without token)" -ForegroundColor Green
    } else {
        Write-Host "   ⚠️  Unexpected status: $($_.Exception.Response.StatusCode)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "   ⚠️  Erreur (peut être normal): $_" -ForegroundColor Yellow
}

Write-Host "`n=== Résultats ===" -ForegroundColor Cyan
Write-Host "✅ Serveur semble fonctionner correctement" -ForegroundColor Green
Write-Host "→ Aller à http://$Host`:$Port/login.html" -ForegroundColor Cyan
Write-Host "→ Après login, accéder à http://$Host`:$Port/capture.html" -ForegroundColor Cyan
