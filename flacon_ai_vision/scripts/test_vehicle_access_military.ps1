param(
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$Token = "",
    [string]$ImagePath = "data\test_vehicle.jpg",
    [int]$CameraId = 1,
    [string]$GateId = "GATE-A",
    [string]$Direction = "IN"
)

if (-not $Token) {
    Write-Error "Provide -Token <JWT access token>."
    exit 1
}

if (-not (Test-Path $ImagePath)) {
    Write-Error "Image not found: $ImagePath"
    exit 1
}

$headers = @{
    Authorization = "Bearer $Token"
}

Write-Host "1) Recognize vehicle..."
$form = @{
    camera_id = "$CameraId"
    gate_id = "$GateId"
    direction = "$Direction"
    persist = "true"
    save_snapshot = "true"
    file = Get-Item $ImagePath
}
$recognize = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/vehicle/recognize" -Headers $headers -Form $form
$recognize | ConvertTo-Json -Depth 8

Write-Host "2) Read latest access logs..."
$logs = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/vehicle/access/logs?camera_id=$CameraId&limit=10" -Headers $headers
$logs | ConvertTo-Json -Depth 8

Write-Host "3) Read open security alerts..."
$alerts = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/vehicle/access/alerts?resolution_status=open&limit=10" -Headers $headers
$alerts | ConvertTo-Json -Depth 8

if ($recognize.access_log_id) {
    Write-Host "4) Optional manual override test..."
    $payload = @{
        access_log_id = $recognize.access_log_id
        forced_decision = "allowed"
        note = "Operator verification approved"
    } | ConvertTo-Json

    $override = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/vehicle/access/manual-override" -Headers ($headers + @{ "Content-Type" = "application/json" }) -Body $payload
    $override | ConvertTo-Json -Depth 8
}
