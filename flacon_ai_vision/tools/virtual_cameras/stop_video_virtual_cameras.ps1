param(
    [string]$PidPath = ".\tools\virtual_cameras\virtual_camera_pids.json"
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

$PidPath = Resolve-ToolPath -PathValue $PidPath

if (-not (Test-Path -LiteralPath $PidPath)) {
    Write-Host "No PID file found at $PidPath" -ForegroundColor Yellow
    exit 0
}

$state = Get-Content -LiteralPath $PidPath -Raw | ConvertFrom-Json

if ($state.ffmpeg) {
    foreach ($ffmpegPid in @($state.ffmpeg)) {
        try {
            Stop-Process -Id ([int]$ffmpegPid) -Force -ErrorAction Stop
            Write-Host "Stopped ffmpeg PID $ffmpegPid" -ForegroundColor Green
        } catch {
            Write-Host "ffmpeg PID $ffmpegPid already stopped" -ForegroundColor Yellow
        }
    }
}

if ($state.mediamtx -and [bool]$state.mediamtx_owned) {
    try {
        Stop-Process -Id ([int]$state.mediamtx) -Force -ErrorAction Stop
        Write-Host "Stopped MediaMTX PID $($state.mediamtx)" -ForegroundColor Green
    } catch {
        Write-Host "MediaMTX PID $($state.mediamtx) already stopped" -ForegroundColor Yellow
    }
} elseif ($state.mediamtx) {
    Write-Host "MediaMTX PID $($state.mediamtx) was reused and left running." -ForegroundColor Cyan
}
