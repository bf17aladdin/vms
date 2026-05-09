# Script de démarrage du serveur avec chemin correct
# Usage: .\run_server_corrected.ps1

Write-Host "🚀 Démarrage du serveur Falcon AI Vision..." -ForegroundColor Cyan

# Activer l'environnement virtuel
Write-Host "📦 Activation l'environnement virtuel..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# Vérifier que uvicorn est disponible
Write-Host "✓ Vérification des dépendances..." -ForegroundColor Yellow
$uvicorn = Get-Command uvicorn -ErrorAction SilentlyContinue
if(-not $uvicorn) {
    Write-Host "❌ uvicorn non trouvé. Installation..." -ForegroundColor Red
    pip install uvicorn
}

# Lancer le serveur
Write-Host "▶️  Démarrage du serveur sur http://127.0.0.1:5003" -ForegroundColor Green
Write-Host "📝 Logs en mode debug - appuyer Ctrl+C pour arrêter" -ForegroundColor Cyan
Write-Host "" 

uvicorn vms.backend.main:app --reload --log-level debug --port 5003 --host 127.0.0.1
