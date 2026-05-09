Param(
    [string]$BaseUrl = "http://127.0.0.1:5003",
    [string]$Username = "admin",
    [string]$Password = "admin123",
    [string]$ImagePath = "",
    [int]$CameraId = 1,
    [Nullable[int]]$ZoneId = $null,
    [bool]$Persist = $true,
    [bool]$SaveSnapshot = $true
)

$ErrorActionPreference = "Stop"

function Require-File([string]$PathValue) {
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        throw "ImagePath is required. Example: -ImagePath .\samples\vehicle.jpg"
    }
    if (-not (Test-Path $PathValue)) {
        throw "Image file not found: $PathValue"
    }
}

function Print-Title([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host $Text
    Write-Host ("=" * 70)
}

Require-File -PathValue $ImagePath

Print-Title "1) Health check -> $BaseUrl/health"
try {
    $health = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health"
    $health | ConvertTo-Json -Depth 10
} catch {
    throw "Backend not reachable on $BaseUrl. Ensure backend is running on port 5003."
}

Print-Title "2) Login -> $BaseUrl/api/auth/login"
$loginPayload = @{
    username = $Username
    password = $Password
} | ConvertTo-Json

$loginResp = Invoke-RestMethod -Method POST -Uri "$BaseUrl/api/auth/login" -ContentType "application/json" -Body $loginPayload
$token = $loginResp.access_token
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "Login succeeded but access_token is missing."
}
Write-Host ("Token received (first 30 chars): " + $token.Substring(0, [Math]::Min(30, $token.Length)) + "...")

Print-Title "3) Vehicle recognize -> $BaseUrl/api/vehicle/recognize"

$curlArgs = @(
    "-sS",
    "-X", "POST",
    "$BaseUrl/api/vehicle/recognize",
    "-H", "Authorization: Bearer $token",
    "-F", "camera_id=$CameraId",
    "-F", "persist=$($Persist.ToString().ToLower())",
    "-F", "save_snapshot=$($SaveSnapshot.ToString().ToLower())",
    "-F", "file=@$ImagePath"
)

if ($ZoneId -ne $null) {
    $curlArgs += @("-F", "zone_id=$ZoneId")
}

$rawResponse = & curl.exe @curlArgs
if ($LASTEXITCODE -ne 0) {
    throw "curl request failed with exit code $LASTEXITCODE"
}

Print-Title "4) Full JSON response"
$rawResponse

Print-Title "5) Key fields"
try {
    $parsed = $rawResponse | ConvertFrom-Json
    $summary = [ordered]@{
        success          = $parsed.success
        status           = $parsed.status
        vehicle_detected = $parsed.vehicle_detected
        plate_number     = $parsed.plate_number
        plate_type       = $parsed.plate_type
        confidence       = $parsed.confidence
        priority         = $parsed.priority
        event_id         = $parsed.event_id
        snapshot_path    = $parsed.snapshot_path
        camera_id        = $parsed.camera_id
        zone_id          = $parsed.zone_id
        timestamp        = $parsed.timestamp
        reason           = $parsed.reason
        security_tag     = $parsed.security_tag
    }
    $summary | ConvertTo-Json -Depth 10
} catch {
    Write-Warning "Failed to parse response JSON. Raw response shown above."
}

