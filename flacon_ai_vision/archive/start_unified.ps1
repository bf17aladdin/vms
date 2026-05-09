#!/usr/bin/env powershell
# ============================================================================
# Falcon AI Vision - Unified Server Launcher (PowerShell)
# Script stable pour Windows avec auto-restart en cas de crash
# ============================================================================

[CmdletBinding()]
param()

# Configuration
$ProjectDir = "C:\Users\boufm\Desktop\eye of falcon"
$BackendDir = "$ProjectDir\vms\backend"
$VenvPython = "$ProjectDir\.venv\Scripts\python.exe"
$Port = 5000
$Host_IP = "127.0.0.1"
$MaxRestarts = 10

# Fonction pour afficher les messages avec couleurs
function Write-Status {
    param([string]$Message, [string]$Type = "Info")
    
    $Timestamp = Get-Date -Format "HH:mm:ss"
    
    switch ($Type) {
        "Success" { Write-Host "[$Timestamp] [OK] $Message" -ForegroundColor Green }
        "Error"   { Write-Host "[$Timestamp] [!] $Message" -ForegroundColor Red }
        "Warning" { Write-Host "[$Timestamp] [*] $Message" -ForegroundColor Yellow }
        default   { Write-Host "[$Timestamp] [*] $Message" -ForegroundColor Cyan }
    }
}

# Nettoyer la console
Clear-Host

# Afficher l'en-tête
Write-Host ""
Write-Host "=" * 80
Write-Host "  Falcon AI Vision - Unified Server Launcher" -ForegroundColor Cyan
Write-Host "=" * 80
Write-Host ""
Write-Status "Projet    : $ProjectDir"
Write-Status "Backend   : $BackendDir"
Write-Status "Python    : $VenvPython"
Write-Status "URL       : http://$Host_IP:$Port"
Write-Status "Docs API  : http://$Host_IP:$Port/docs"
Write-Host ""
Write-Host "=" * 80
Write-Host ""

# Vérifier que le venv existe
if (-not (Test-Path $VenvPython)) {
    Write-Status "Virtual environment non trouvé!" "Error"
    Write-Status "Chemin attendu: $VenvPython" "Error"
    Write-Host ""
    Write-Status "Solution : créer le venv avec :" "Warning"
    Write-Host "    python -m venv .venv" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Appuyez sur Entrée pour quitter"
    exit 1
}

# Vérifier que main.py existe
if (-not (Test-Path "$BackendDir\main.py")) {
    Write-Status "main.py non trouvé!" "Error"
    Write-Status "Chemin attendu: $BackendDir\main.py" "Error"
    Write-Host ""
    Read-Host "Appuyez sur Entrée pour quitter"
    exit 1
}

# Boucle de redémarrage automatique
$RestartCount = 0

while ($RestartCount -lt $MaxRestarts) {
    $RestartCount++
    
    if ($RestartCount -gt 1) {
        Write-Host ""
        Write-Status "Redémarrage du serveur... (tentative $RestartCount/$MaxRestarts)" "Warning"
        Write-Host ""
        Start-Sleep -Seconds 2
    }
    
    # Afficher le démarrage
    Write-Status "Démarrage du serveur FastAPI..." "Info"
    Write-Status "Appuyez sur Ctrl+C pour arrêter le serveur." "Warning"
    Write-Host ""
    
    # Changer de répertoire et lancer le serveur
    Push-Location $BackendDir
    
    try {
        # Lancer le serveur
        & $VenvPython -m uvicorn main:app `
            --host $Host_IP `
            --port $Port `
            --log-level info
    }
    catch {
        Write-Status "Erreur lors du lancement du serveur: $_" "Error"
    }
    finally {
        Pop-Location
    }
    
    # Si le serveur s'arrête
    if ($RestartCount -lt $MaxRestarts) {
        Write-Host ""
        Write-Status "Le serveur s'est arrêté de manière inattendue!" "Error"
        Write-Status "Tentative de redémarrage dans 3 secondes..." "Warning"
        Write-Host ""
        Start-Sleep -Seconds 3
    }
}

# Si on sort de la boucle
Write-Host ""
Write-Status "Nombre maximum de redémarrages atteint ($MaxRestarts)" "Error"
Write-Status "Le serveur ne peut pas redémarrer automatiquement." "Error"
Write-Host ""
Read-Host "Appuyez sur Entrée pour quitter"
exit 1
