<#
.SYNOPSIS
    Monte progressivement le nombre de flux RTSP pour identifier la charge maximale.

.DESCRIPTION
    Exécute une série de tests en lançant progressivement un nombre croissant de flux ffmpeg
    via start_rtsp_load_test.ps1. À chaque palier, il attend un certain temps, vérifie si les
    processus ffmpeg sont toujours là et collecte quelques métriques simples.

    À la fin de chaque palier, le script appelle stop_rtsp_load_test.ps1 pour faire le ménage.

.EXAMPLE
    .\auto_rtsp_load_test.ps1 -MaxStreams 50 -Step 5 -HoldSeconds 20
#>

param(
    [int]$MaxStreams = 50,
    [int]$Step = 5,
    [int]$HoldSeconds = 30,
    [int]$StartStreams = 5,
    [string]$Resolution = "1280x720",
    [int]$Fps = 15,
    [int]$VideoBitrateK = 1000,
    [switch]$SkipMediamtx,
    [string]$OutputCsv = "load_test_results.csv"
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$results = @()

function Write-Header {
    $line = "`n=== $($args[0]) ==="
    Write-Host $line -ForegroundColor Cyan
}

function Stop-CurrentTest {
    # Arrête proprement tous les ffmpeg / mediamtx lancés par start_rtsp_load_test
    & "$scriptDir\stop_rtsp_load_test.ps1" | Out-Null
}

Write-Header "AUTO RTSP LOAD TEST"
Write-Host "MaxStreams=$MaxStreams Step=$Step HoldSeconds=$HoldSeconds" -ForegroundColor Yellow
Write-Host "Resolution=$Resolution Fps=$Fps Bitrate=${VideoBitrateK}k" -ForegroundColor Yellow

for ($streams = $StartStreams; $streams -le $MaxStreams; $streams += $Step) {
    Write-Header "Test $streams streams"

    # Démarrage
    $cmd = "& '$scriptDir\\start_rtsp_load_test.ps1' -Streams $streams -Resolution '$Resolution' -Fps $Fps -VideoBitrateK $VideoBitrateK"
    if ($SkipMediamtx) { $cmd += ' -SkipMediamtx' }

    Invoke-Expression $cmd | Out-Null

    # Attendre stabilisation
    Start-Sleep -Seconds $HoldSeconds

    # Contrôler l'état
    $ffmpegs = Get-Process -Name ffmpeg -ErrorAction SilentlyContinue
    $running = if ($ffmpegs) { $ffmpegs.Count } else { 0 }

    $cpuPct = 0
    if ($ffmpegs) {
        # CPU total depuis le démarrage (approximatif)
        $cpuPct = [math]::Round(($ffmpegs | Measure-Object -Property CPU -Sum).Sum, 2)
    }

    $status = if ($running -ge $streams) { 'OK' } else { 'FAIL' }

    $results += [pscustomobject]@{
        Date = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        StreamsRequested = $streams
        StreamsRunning = $running
        Status = $status
        CpuTotal = $cpuPct
    }

    $color = if ($status -eq 'OK') { 'Green' } else { 'Red' }
    Write-Host "  Streams en cours: $running / $streams    CPU (total): $cpuPct" -ForegroundColor $color

    # Si échec, on arrête et on quitte
    if ($status -ne 'OK') {
        Write-Host "Échec détecté à $streams streams, arrêt du test." -ForegroundColor Red
        Stop-CurrentTest
        break
    }

    Stop-CurrentTest
}

# Export des résultats
$results | Export-Csv -Path (Join-Path $scriptDir $OutputCsv) -NoTypeInformation -Force
Write-Header "TERMINE"
Write-Host "Résultats enregistrés dans $(Join-Path $scriptDir $OutputCsv)" -ForegroundColor Green
