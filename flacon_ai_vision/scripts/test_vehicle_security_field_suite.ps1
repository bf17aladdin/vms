param(
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$Token = "",
    [int]$CameraId = 1,
    [string]$GateId = "GATE-A",
    [string]$Direction = "IN",
    [string]$PlateCleanImage = "data\\tests\\plate_clean_day.jpg",
    [string]$PlateDirtyImage = "data\\tests\\plate_dirty.jpg",
    [string]$DifferentPlateSameCarImage = "data\\tests\\plate_diff_same_car.jpg",
    [string]$GoodPlateWrongCarImage = "data\\tests\\good_plate_wrong_car.jpg"
)

if (-not $Token) {
    Write-Error "Provide -Token <JWT access token>."
    exit 1
}

$headers = @{ Authorization = "Bearer $Token" }

function Invoke-Recognize([string]$label, [string]$imagePath) {
    Write-Host "=== $label ==="
    if (-not (Test-Path $imagePath)) {
        Write-Host "Image not found: $imagePath"
        return
    }
    $form = @{
        camera_id = "$CameraId"
        gate_id = "$GateId"
        direction = "$Direction"
        persist = "true"
        save_snapshot = "true"
        file = Get-Item $imagePath
    }
    $res = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/vehicle/recognize" -Headers $headers -Form $form
    $res | Select-Object status,plate_number,plate_type,confidence,decision,decision_reason,requires_manual_review,priority,event_id,access_log_id,alert_type | Format-List
}

Write-Host "Health full check..."
$health = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/system/health/full?window_minutes=60&persist=true" -Headers $headers
$health | ConvertTo-Json -Depth 6

Invoke-Recognize "Test 1 - Plaque propre jour (expected pass)" $PlateCleanImage
Invoke-Recognize "Test 2 - Plaque sale (expected multi-frame OCR assist)" $PlateDirtyImage
Invoke-Recognize "Test 3 - Plaque differente meme voiture (expected alert)" $DifferentPlateSameCarImage
Invoke-Recognize "Test 4 - Plaque bonne mauvaise voiture (expected review/deny)" $GoodPlateWrongCarImage

Write-Host "Latest security alerts..."
$alerts = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/vehicle/access/alerts?limit=20" -Headers $headers
$alerts | ConvertTo-Json -Depth 6
