Param(
    [string]$BaseUrl = "http://127.0.0.1:5003",
    [string]$Username = "admin",
    [string]$Password = "admin123",
    [int]$CameraId = 1,
    [Nullable[int]]$ZoneId = $null,
    [bool]$Persist = $true,
    [bool]$SaveSnapshot = $true,
    [string]$Token = ""
)

$ErrorActionPreference = "Stop"

function Print-Section([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 72)
    Write-Host $Text
    Write-Host ("=" * 72)
}

Print-Section "1) Health check -> $BaseUrl/health"
try {
    $health = Invoke-RestMethod -Method GET -Uri "$BaseUrl/health"
    $health | ConvertTo-Json -Depth 10
} catch {
    throw "Backend not reachable on $BaseUrl (expected port 5003)."
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    Print-Section "2) Login -> $BaseUrl/api/auth/login"
    $loginPayload = @{
        username = $Username
        password = $Password
    } | ConvertTo-Json

    $loginResp = Invoke-RestMethod -Method POST -Uri "$BaseUrl/api/auth/login" -ContentType "application/json" -Body $loginPayload
    $Token = $loginResp.access_token
    if ([string]::IsNullOrWhiteSpace($Token)) {
        throw "Login succeeded but access_token is missing."
    }
    Write-Host ("Token received (first 30 chars): " + $Token.Substring(0, [Math]::Min(30, $Token.Length)) + "...")
} else {
    Print-Section "2) Using provided token"
    Write-Host ("Token provided (first 30 chars): " + $Token.Substring(0, [Math]::Min(30, $Token.Length)) + "...")
}

Print-Section "3) Recognize from camera -> $BaseUrl/api/vehicle/recognize/camera/$CameraId"

$payload = @{
    persist = $Persist
    save_snapshot = $SaveSnapshot
}
if ($ZoneId -ne $null) {
    $payload["zone_id"] = $ZoneId
}

$headers = @{
    "Authorization" = "Bearer $Token"
    "Content-Type" = "application/json"
}

$response = Invoke-RestMethod `
    -Method POST `
    -Uri "$BaseUrl/api/vehicle/recognize/camera/$CameraId" `
    -Headers $headers `
    -Body ($payload | ConvertTo-Json)

Print-Section "4) Full JSON response"
$response | ConvertTo-Json -Depth 12

Print-Section "5) Key fields"
$summary = [ordered]@{
    success          = $response.success
    status           = $response.status
    vehicle_detected = $response.vehicle_detected
    plate_number     = $response.plate_number
    plate_type       = $response.plate_type
    confidence       = $response.confidence
    priority         = $response.priority
    event_id         = $response.event_id
    snapshot_path    = $response.snapshot_path
    camera_id        = $response.camera_id
    zone_id          = $response.zone_id
    timestamp        = $response.timestamp
    reason           = $response.reason
    security_tag     = $response.security_tag
}
$summary | ConvertTo-Json -Depth 12

