param(
    [string]$RuntimePath = ".\tools\virtual_cameras\virtual_camera_runtime.json",
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$Token = "",
    [string]$Username = "",
    [string]$Password = "",
    [string]$NamePrefix = "Virtual",
    [string]$LocationPrefix = "Virtual Camera",
    [string]$ZoneName = "Virtual Lab",
    [switch]$EnableAi
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

function Resolve-CameraList {
    param([object]$Payload)

    if ($null -eq $Payload) {
        return @()
    }
    if ($Payload -is [System.Array]) {
        return $Payload
    }
    if ($Payload.PSObject.Properties.Name -contains "cameras") {
        return @($Payload.cameras)
    }
    if ($Payload.PSObject.Properties.Name -contains "data" -and $Payload.data) {
        if ($Payload.data.PSObject.Properties.Name -contains "cameras") {
            return @($Payload.data.cameras)
        }
    }
    return @()
}

if (-not (Test-Path -LiteralPath $RuntimePath)) {
    throw "Runtime file not found: $RuntimePath. Start the virtual cameras first."
}

$runtime = Get-Content -LiteralPath $RuntimePath -Raw | ConvertFrom-Json
$runtimeCameras = @($runtime.cameras)
if ($runtimeCameras.Count -eq 0) {
    throw "No camera streams found in runtime file: $RuntimePath"
}

if (-not $Token) {
    if (-not $Username -or -not $Password) {
        throw "Provide -Token or -Username/-Password."
    }
    $loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
    $login = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/auth/login" -ContentType "application/json" -Body $loginBody
    $Token = $login.access_token
}

$headers = @{ Authorization = "Bearer $Token" }
$existingPayload = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/cameras" -Headers $headers
$existingCameras = Resolve-CameraList -Payload $existingPayload

$created = 0
$updated = 0

foreach ($camera in $runtimeCameras) {
    $streamName = [string]$camera.name
    $rtspUrl = [string]$camera.rtsp_url
    $sourceVideo = [string]$camera.source_video

    $matching = $existingCameras | Where-Object {
        [string]$_.rtsp_url -eq $rtspUrl -or [string]$_.name -eq "$NamePrefix $streamName"
    } | Select-Object -First 1

    $payload = @{
        name = "$NamePrefix $streamName"
        description = "Virtual camera fed by $sourceVideo"
        rtsp_url = $rtspUrl
        ip_address = "127.0.0.1"
        port = 8554
        location = "$LocationPrefix $streamName"
        zone_name = $ZoneName
        streaming_enabled = $true
        is_active = $true
        motion_detection_enabled = $true
        object_detection_enabled = $true
        detection_sensitivity = 60
        ai_enabled = [bool]$EnableAi
    }

    if ($matching) {
        Invoke-RestMethod `
            -Method Put `
            -Uri ("$ApiBase/api/cameras/{0}" -f [int]$matching.id) `
            -Headers $headers `
            -ContentType "application/json" `
            -Body ($payload | ConvertTo-Json)
        Write-Host ("Updated {0} -> {1}" -f $payload.name, $rtspUrl) -ForegroundColor Yellow
        $updated++
    } else {
        Invoke-RestMethod `
            -Method Post `
            -Uri "$ApiBase/api/cameras" `
            -Headers $headers `
            -ContentType "application/json" `
            -Body ($payload | ConvertTo-Json)
        Write-Host ("Created {0} -> {1}" -f $payload.name, $rtspUrl) -ForegroundColor Green
        $created++
    }
}

Write-Host ""
Write-Host "=== FALCON REGISTRATION COMPLETE ===" -ForegroundColor Green
Write-Host "Created: $created" -ForegroundColor Green
Write-Host "Updated: $updated" -ForegroundColor Yellow
