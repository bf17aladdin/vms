param(
    [string]$RuntimePath = ".\tools\virtual_cameras\virtual_camera_runtime.json",
    [int]$ProbeTimeoutSec = 10
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")

function Resolve-ToolPath {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $PathValue
    }
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }

    $trimmed = $PathValue -replace '^[.\\/]+', ''
    $candidates = @(
        $PathValue,
        (Join-Path $scriptDir (Split-Path -Leaf $PathValue)),
        (Join-Path $repoRoot $trimmed)
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    return $candidates[-1]
}

$RuntimePath = Resolve-ToolPath -PathValue $RuntimePath

if (-not (Test-Path -LiteralPath $RuntimePath)) {
    throw "Runtime file not found: $RuntimePath"
}

$runtime = Get-Content -LiteralPath $RuntimePath -Raw | ConvertFrom-Json
$cameras = @($runtime.cameras)
if ($cameras.Count -eq 0) {
    throw "No camera streams found in runtime file: $RuntimePath"
}

$logDir = Join-Path $scriptDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-StreamProbeResult {
    param(
        [string]$CameraName,
        [string]$RtspUrl,
        [int]$TimeoutSec
    )

    $stdout = Join-Path $logDir ("ffprobe_{0}.out.json" -f $CameraName)
    $stderr = Join-Path $logDir ("ffprobe_{0}.err.log" -f $CameraName)
    Remove-Item -ErrorAction SilentlyContinue $stdout, $stderr

    $arguments = @(
        "-v", "error",
        "-rtsp_transport", "tcp",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate",
        "-of", "json",
        $RtspUrl
    )

    $proc = Start-Process `
        -FilePath "ffprobe" `
        -ArgumentList $arguments `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        Start-Sleep -Milliseconds 250
        if (Test-Path -LiteralPath $stdout) {
            $partial = Get-Content -LiteralPath $stdout -Raw
            if ($partial -and $partial.Contains('"codec_name"')) {
                break
            }
        }
    } while ((Get-Date) -lt $deadline -and -not $proc.HasExited)

    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force
    }

    $payloadText = if (Test-Path -LiteralPath $stdout) {
        Get-Content -LiteralPath $stdout -Raw
    } else {
        ""
    }
    $errorText = if (Test-Path -LiteralPath $stderr) {
        $rawError = Get-Content -LiteralPath $stderr -Raw
        if ($null -eq $rawError) { "" } else { $rawError.Trim() }
    } else {
        ""
    }

    $streamInfo = $null
    if ($payloadText) {
        try {
            $payload = $payloadText | ConvertFrom-Json
            $streamInfo = @($payload.streams)[0]
        } catch {
            $streamInfo = $null
        }
    }

    return [PSCustomObject]@{
        stream = $streamInfo
        error = $errorText
        raw = $payloadText
    }
}

$results = @()
foreach ($camera in $cameras) {
    $cameraName = [string]$camera.name
    $rtspUrl = [string]$camera.rtsp_url
    $ffmpegPid = [int]$camera.ffmpeg_pid
    $ffmpegRunning = $false

    try {
        $ffmpegRunning = $null -ne (Get-Process -Id $ffmpegPid -ErrorAction Stop)
    } catch {
        $ffmpegRunning = $false
    }

    $probe = Get-StreamProbeResult -CameraName $cameraName -RtspUrl $rtspUrl -TimeoutSec $ProbeTimeoutSec
    $stream = $probe.stream
    $reachable = $null -ne $stream
    $codec = if ($stream) { [string]$stream.codec_name } else { "" }
    $width = if ($stream) { [int]$stream.width } else { 0 }
    $height = if ($stream) { [int]$stream.height } else { 0 }
    $frameRate = if ($stream) { [string]$stream.r_frame_rate } else { "" }
    $ok = $reachable -and $ffmpegRunning -and [bool]$codec

    $results += [PSCustomObject]@{
        camera = $cameraName
        ok = $ok
        reachable = $reachable
        codec = $codec
        width = $width
        height = $height
        frame_rate = $frameRate
        ffmpeg_pid = $ffmpegPid
        ffmpeg_running = $ffmpegRunning
        rtsp_url = $rtspUrl
        error = [string]$probe.error
    }
}

Write-Host "=== SMOKE TEST ===" -ForegroundColor Cyan
foreach ($result in $results) {
    if ($result.ok) {
        Write-Host ("{0} OK codec={1} {2}x{3} fps={4} pid={5}" -f $result.camera, $result.codec, $result.width, $result.height, $result.frame_rate, $result.ffmpeg_pid) -ForegroundColor Green
    } else {
        $why = if ($result.error) { $result.error } elseif (-not $result.ffmpeg_running) { "ffmpeg process not running" } else { "probe failed" }
        Write-Host ("{0} FAIL {1}" -f $result.camera, $why) -ForegroundColor Red
    }
}

$results | ConvertTo-Json -Depth 4
