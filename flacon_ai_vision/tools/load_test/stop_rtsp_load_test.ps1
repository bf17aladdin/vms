Write-Host "=== ARRÊT DU TEST ===" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $scriptDir "load_test_pids.json"

if (Test-Path $pidFile) {
    $data = Get-Content $pidFile | ConvertFrom-Json
    
    # Arrêt des ffmpeg
    if ($data.ffmpeg) {
        Write-Host "Arrêt des flux ffmpeg..." -ForegroundColor Yellow
        foreach ($ffmpegPid in $data.ffmpeg) {
            Stop-Process -Id $ffmpegPid -Force -ErrorAction SilentlyContinue
            Write-Host "  ✓ PID $ffmpegPid arrêté" -ForegroundColor Green
        }
    }
    
    # Arrêt de mediamtx
    if ($data.mediamtx) {
        Write-Host "Arrêt de mediamtx..." -ForegroundColor Yellow
        Stop-Process -Id $data.mediamtx -Force -ErrorAction SilentlyContinue
        Write-Host "  ✓ mediamtx arrêté" -ForegroundColor Green
    }
    
    # Archive
    $archiveDir = Join-Path $scriptDir "logs\archive"
    New-Item -ItemType Directory -Force -Path $archiveDir | Out-Null
    $archiveName = "pids_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
    Move-Item $pidFile (Join-Path $archiveDir $archiveName) -Force
    Write-Host "✓ PID file archivé" -ForegroundColor Green
    
} else {
    Write-Host "Aucun PID file trouvé" -ForegroundColor Yellow
    Write-Host "Recherche des processus ffmpeg..." -ForegroundColor Yellow
    Get-Process -Name ffmpeg -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force
        Write-Host "  ✓ PID $($_.Id) arrêté" -ForegroundColor Green
    }
}

Write-Host "=== NETTOYAGE TERMINÉ ===" -ForegroundColor Green
