param(
    [string]$VideoRoot = "$env:USERPROFILE\Downloads",
    [string[]]$CameraNames = @("cam01", "cam02", "cam03", "cam04"),
    [string]$RtspBase = "rtsp://127.0.0.1:8554",
    [string]$MediamtxPath = "..\mediamtx_v1.16.2\mediamtx.exe",
    [string]$FfmpegPath = "ffmpeg",
    [int]$Fps = 25,
    [string]$Resolution = "1280x720",
    [int]$VideoBitrateK = 1000,
    [switch]$SkipMediamtx
)

$ErrorActionPreference = "Stop"

function Resolve-VideoFile {
    param(
        [string]$Root,
        [string]$BaseName
    )

    $extensions = @(".mp4", ".mov", ".mkv", ".avi", ".webm")
    foreach ($extension in $extensions) {
        $candidate = Join-Path $Root ($BaseName + $extension)
        if (Test-Path -LiteralPath $candidate) {
            return Get-Item -LiteralPath $candidate
        }
    }

    $fallback = Get-ChildItem -LiteralPath $Root -File -ErrorAction SilentlyContinue |
        Where-Object {
            $_.BaseName -ieq $BaseName -and $_.Extension.ToLowerInvariant() -in $extensions
        } |
        Select-Object -First 1

    return $fallback
}

function Parse-Resolution {
    param([string]$Value)

    if ($Value -notmatch "^(?<width>\d+)x(?<height>\d+)$") {
        throw "Resolution must look like 1280x720. Received: $Value"
    }

    return @{
        Width = [int]$Matches["width"]
        Height = [int]$Matches["height"]
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $scriptDir "logs"
$pidFile = Join-Path $scriptDir "virtual_camera_pids.json"
$runtimeFile = Join-Path $scriptDir "virtual_camera_runtime.json"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$dimensions = Parse-Resolution -Value $Resolution
$width = [int]$dimensions.Width
$height = [int]$dimensions.Height
$gop = [Math]::Max($Fps * 2, 20)
$bufferSizeK = [Math]::Max($VideoBitrateK * 2, $VideoBitrateK + 500)
$mediamtxLogOut = Join-Path $logDir "mediamtx.stdout.log"
$mediamtxLogErr = Join-Path $logDir "mediamtx.stderr.log"

Write-Host "=== FALCON VIRTUAL CAMERAS ===" -ForegroundColor Cyan
Write-Host "Video root: $VideoRoot" -ForegroundColor Yellow
Write-Host "RTSP base: $RtspBase" -ForegroundColor Yellow
Write-Host "Profile: $Resolution @ $Fps fps / ${VideoBitrateK}k" -ForegroundColor Yellow

$selectedVideos = @()
foreach ($cameraName in $CameraNames) {
    $file = Resolve-VideoFile -Root $VideoRoot -BaseName $cameraName
    if (-not $file) {
        throw "Missing video for $cameraName in $VideoRoot. Expected cam01..cam04 style files."
    }
    $selectedVideos += [PSCustomObject]@{
        CameraName = $cameraName
        FileName = $file.Name
        FullName = $file.FullName
        FileSize = $file.Length
        LastWriteTime = $file.LastWriteTime
    }
}

$mediamtxProcess = Get-Process -Name "mediamtx" -ErrorAction SilentlyContinue | Select-Object -First 1
$mediamtxOwned = $false

if (-not $SkipMediamtx) {
    if ($mediamtxProcess) {
        Write-Host "Reusing existing MediaMTX PID $($mediamtxProcess.Id)" -ForegroundColor Green
    } else {
        $mediamtxFullPath = Join-Path $scriptDir $MediamtxPath
        $mediamtxConfigPath = Join-Path $scriptDir "..\mediamtx_v1.16.2\mediamtx.yml"
        if (-not (Test-Path -LiteralPath $mediamtxFullPath)) {
            throw "MediaMTX not found at $mediamtxFullPath"
        }
        if (-not (Test-Path -LiteralPath $mediamtxConfigPath)) {
            throw "MediaMTX config not found at $mediamtxConfigPath"
        }

        Write-Host "Starting MediaMTX..." -ForegroundColor Yellow
        Remove-Item -ErrorAction SilentlyContinue $mediamtxLogOut, $mediamtxLogErr
        $mediamtxProcess = Start-Process `
            -FilePath $mediamtxFullPath `
            -ArgumentList @($mediamtxConfigPath) `
            -PassThru `
            -WindowStyle Hidden `
            -RedirectStandardOutput $mediamtxLogOut `
            -RedirectStandardError $mediamtxLogErr
        $mediamtxOwned = $true
        Start-Sleep -Seconds 2
        if ($mediamtxProcess.HasExited) {
            throw "MediaMTX exited immediately. Check $mediamtxFullPath"
        }
    }
}

try {
    $ffmpegVersion = & $FfmpegPath -version 2>$null | Select-Object -First 1
    if (-not $ffmpegVersion) {
        throw "ffmpeg did not return version output"
    }
    Write-Host "ffmpeg: $ffmpegVersion" -ForegroundColor Green
} catch {
    throw "ffmpeg not found or not executable via '$FfmpegPath'"
}

$runtimeCameras = @()
$ffmpegPids = @()

foreach ($video in $selectedVideos) {
    $streamName = $video.CameraName
    $rtspUrl = "$RtspBase/$streamName"
    $logOut = Join-Path $logDir ("ffmpeg_{0}.log" -f $streamName)
    $logErr = Join-Path $logDir ("ffmpeg_{0}.err.log" -f $streamName)
    Remove-Item -ErrorAction SilentlyContinue $logOut, $logErr

    $filter = "scale=w=${width}:h=${height}:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:color=black,fps=${Fps},format=yuv420p"
    $arguments = @(
        "-stream_loop", "-1",
        "-re",
        "-fflags", "+genpts",
        "-i", $video.FullName,
        "-an",
        "-vf", $filter,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-g", "$gop",
        "-b:v", "${VideoBitrateK}k",
        "-maxrate", "${VideoBitrateK}k",
        "-bufsize", "${bufferSizeK}k",
        "-rtsp_transport", "tcp",
        "-muxdelay", "0.1",
        "-f", "rtsp",
        $rtspUrl
    )

    Write-Host ("Starting {0} -> {1}" -f $video.FileName, $rtspUrl) -ForegroundColor Cyan
    $proc = Start-Process `
        -FilePath $FfmpegPath `
        -ArgumentList $arguments `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logOut `
        -RedirectStandardError $logErr

    Start-Sleep -Milliseconds 700
    if ($proc.HasExited) {
        throw "ffmpeg exited early for $($video.FileName). Check $logErr"
    }

    $ffmpegPids += $proc.Id
    $runtimeCameras += [PSCustomObject]@{
        name = $streamName
        source_video = $video.FullName
        rtsp_url = $rtspUrl
        ffmpeg_pid = $proc.Id
        resolution = $Resolution
        fps = $Fps
        bitrate_k = $VideoBitrateK
    }
}

$runtimePayload = [PSCustomObject]@{
    created_at = (Get-Date).ToString("o")
    video_root = $VideoRoot
    rtsp_base = $RtspBase
    cameras = $runtimeCameras
}
$runtimePayload | ConvertTo-Json -Depth 6 | Set-Content -Path $runtimeFile

$pidPayload = [PSCustomObject]@{
    created_at = (Get-Date).ToString("o")
    ffmpeg = $ffmpegPids
    mediamtx = if ($mediamtxProcess) { $mediamtxProcess.Id } else { $null }
    mediamtx_owned = [bool]$mediamtxOwned
}
$pidPayload | ConvertTo-Json -Depth 4 | Set-Content -Path $pidFile

Write-Host ""
Write-Host "=== READY ===" -ForegroundColor Green
Write-Host "Streams started: $($runtimeCameras.Count)" -ForegroundColor Green
foreach ($camera in $runtimeCameras) {
    Write-Host ("  {0} -> {1}" -f $camera.name, $camera.rtsp_url) -ForegroundColor White
}
Write-Host ""
Write-Host "Runtime file: $runtimeFile" -ForegroundColor Yellow
Write-Host "PID file: $pidFile" -ForegroundColor Yellow
Write-Host "Stop with: powershell -ExecutionPolicy Bypass -File .\tools\virtual_cameras\stop_video_virtual_cameras.ps1" -ForegroundColor Magenta
