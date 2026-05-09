param(
    [int]$Streams = 5,
    [string]$RtspBase = "rtsp://127.0.0.1:8554",
    [string]$MediamtxPath = "..\..\..\tools\mediamtx_v1.16.2\mediamtx.exe",
    [string]$FfmpegPath = "ffmpeg",
    [int]$Fps = 15,
    [string]$Resolution = "1280x720",
    [int]$VideoBitrateK = 1000,
    [switch]$SkipMediamtx
)

Write-Host "=== TEST RTSP ===" -ForegroundColor Cyan
Write-Host "Démarrage de $Streams flux à $Fps fps - $Resolution" -ForegroundColor Yellow

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $scriptDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Vérification mediamtx
if (-not $SkipMediamtx) {
    $fullPath = Join-Path $scriptDir $MediamtxPath
    if (Test-Path $fullPath) {
        Write-Host "✓ mediamtx trouvé" -ForegroundColor Green
        $mediamtxProc = Start-Process -FilePath $fullPath -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 2
    } else {
        Write-Host "✗ mediamtx non trouvé: $fullPath" -ForegroundColor Red
    }
}

# Vérification ffmpeg
try {
    $ffmpegVersion = & $FfmpegPath -version 2>$null | Select-Object -First 1
    Write-Host "✓ ffmpeg: $ffmpegVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ ffmpeg non trouvé" -ForegroundColor Red
    exit 1
}

# Démarrage des flux
$pids = @()
$gop = $Fps * 2

for ($i = 1; $i -le $Streams; $i++) {
    $streamName = "cam$i"
    $rtspUrl = "$RtspBase/$streamName"
    Write-Host "Démarrage $streamName..." -NoNewline
    
    $arguments = @(
        "-re",
        "-f", "lavfi",
        "-i", "testsrc=size=$Resolution:rate=$Fps",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-g", "$gop",
        "-b:v", "${VideoBitrateK}k",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        $rtspUrl
    )
    
    $logFile = Join-Path $logDir "ffmpeg_${streamName}.log"
    $logFileErr = Join-Path $logDir "ffmpeg_${streamName}.err.log"
    $proc = Start-Process -FilePath $FfmpegPath -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $logFile -RedirectStandardError $logFileErr
    if ($proc -and -not $proc.HasExited) {
        $pids += $proc.Id
        Write-Host " OK (PID: $($proc.Id))" -ForegroundColor Green
    } else {
        Write-Host " ÉCHEC" -ForegroundColor Red
    }
    
    Start-Sleep -Milliseconds 200
}

# Sauvegarde des PIDs
$pidFile = Join-Path $scriptDir "load_test_pids.json"
@{
    ffmpeg = $pids
    mediamtx = if ($mediamtxProc) { $mediamtxProc.Id } else { $null }
    date = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
} | ConvertTo-Json | Set-Content $pidFile

Write-Host ""
Write-Host "=== RÉSULTAT ===" -ForegroundColor Cyan
Write-Host "✓ Flux démarrés: $($pids.Count)/$Streams" -ForegroundColor Green
Write-Host "📁 Logs: $logDir" -ForegroundColor Yellow
Write-Host "📄 PID: $pidFile" -ForegroundColor Yellow
Write-Host ""
Write-Host "Exemples URLs:" -ForegroundColor Cyan
for ($i = 1; $i -le [Math]::Min(3, $pids.Count); $i++) {
    Write-Host "  $RtspBase/cam$i" -ForegroundColor White
}
Write-Host ""
Write-Host "Pour arrêter: .\stop_rtsp_load_test.ps1" -ForegroundColor Magenta
