# ===================================================
# Google Maps Installation Helper - Falcon AI Vision
# ===================================================

Write-Host "🚀 Falcon AI Vision - Google Maps Installation" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Vérifier si on est dans le bon répertoire
if (-Not (Test-Path "falcon-ai-vision-platform/frontend")) {
    Write-Host "❌ Erreur: Exécute ce script depuis la racine du projet" -ForegroundColor Red
    Write-Host "   cd falcon-ai-vision-platform" -ForegroundColor Yellow
    Write-Host "   .\install_maps.ps1" -ForegroundColor Yellow
    exit 1
}

# Aller au dossier frontend
$currentLocation = Get-Location
Set-Location falcon-ai-vision-platform/frontend

Write-Host "📦 Installation des packages Google Maps..." -ForegroundColor Green
Write-Host ""

# Installer les packages
Write-Host "   Exécution: npm install @react-google-maps/api @types/google.maps" -ForegroundColor Yellow

npm install @react-google-maps/api @types/google.maps

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ Packages installés avec succès!" -ForegroundColor Green
    Write-Host ""
    Write-Host "📋 Prochaines étapes:" -ForegroundColor Cyan
    Write-Host "   1. 🔑 Crée .env.local avec ta clé API" -ForegroundColor Yellow
    Write-Host "      Fichier: falcon-ai-vision-platform/frontend/.env.local" -ForegroundColor Gray
    Write-Host "      Contenu: VITE_GOOGLE_MAPS_API_KEY=AIzaSy..." -ForegroundColor Gray
    Write-Host ""
    Write-Host "   2. 🌐 Obtiens une clé API Google" -ForegroundColor Yellow
    Write-Host "      - Visite: https://console.cloud.google.com" -ForegroundColor Gray
    Write-Host "      - Consulte: GOOGLE_MAPS_SETUP_GUIDE.md (sections 1-4)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "   3. ▶️  Lance le développement" -ForegroundColor Yellow
    Write-Host "      npm run dev" -ForegroundColor Gray
    Write-Host ""
    Write-Host "   4. 🗺️  Visite la page carte" -ForegroundColor Yellow
    Write-Host "      http://localhost:5173 → Map View" -ForegroundColor Gray
    Write-Host ""
}
else {
    Write-Host ""
    Write-Host "❌ Erreur lors de l'installation" -ForegroundColor Red
    Write-Host "   - Vérifiez que Node.js et npm sont installés" -ForegroundColor Yellow
    Write-Host "   - Tapez: node --version" -ForegroundColor Yellow
    exit 1
}

# Retour au répertoire initial
Set-Location $currentLocation
