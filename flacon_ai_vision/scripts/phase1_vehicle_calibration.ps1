param(
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$Token = "",
    [string]$Username = "admin",
    [string]$Password = "admin123",
    [int]$CameraId = 1,
    [string]$GateId = "GATE-A",
    [string]$Direction = "IN",
    [string]$PlateCleanImage = "data\\tests\\plate_clean_day.jpg",
    [string]$PlateDirtyImage = "data\\tests\\plate_dirty.jpg",
    [string]$DifferentPlateSameCarImage = "data\\tests\\plate_diff_same_car.jpg",
    [string]$GoodPlateWrongCarImage = "data\\tests\\good_plate_wrong_car.jpg"
)

$ErrorActionPreference = "Stop"

function Get-AccessToken {
    param([string]$BaseUrl, [string]$User, [string]$Pass)
    $body = @{ username = $User; password = $Pass } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 30
    return [string]$resp.access_token
}

function Invoke-MultipartRecognize {
    param(
        [string]$BaseUrl,
        [string]$AccessToken,
        [int]$CamId,
        [string]$ImagePath,
        [string]$Gate,
        [string]$Dir
    )
    $raw = curl.exe -sS -m 90 -w "`nHTTPSTATUS:%{http_code}`n" `
        -X POST "$BaseUrl/api/vehicle/recognize" `
        -H "Authorization: Bearer $AccessToken" `
        -F "camera_id=$CamId" `
        -F "gate_id=$Gate" `
        -F "direction=$Dir" `
        -F "persist=true" `
        -F "save_snapshot=true" `
        -F "file=@$ImagePath"

    $status = (($raw | Select-String "HTTPSTATUS:" | Select-Object -Last 1).ToString().Replace("HTTPSTATUS:", "")).Trim()
    $bodyRaw = ($raw -split "HTTPSTATUS:")[0].Trim()
    $json = $null
    try { $json = $bodyRaw | ConvertFrom-Json } catch { }

    return [pscustomobject]@{
        status_code = [int]($status)
        body_raw = $bodyRaw
        body = $json
    }
}

function Evaluate-TestResult {
    param([string]$Target, [object]$Response)
    if ($null -eq $Response.body) { return "failed:non_json_response" }
    if ([int]$Response.status_code -ne 200) { return "failed:http_$($Response.status_code)" }

    $decision = [string]$Response.body.decision
    $alertType = [string]$Response.body.alert_type

    switch ($Target) {
        "allowed" {
            if ($decision -eq "allowed") { return "pass" }
            return "failed:decision_$decision"
        }
        "allowed_or_review" {
            if ($decision -in @("allowed", "review_required")) { return "pass" }
            return "failed:decision_$decision"
        }
        "alert_generated" {
            if (($Response.body.security_alert_ids | Measure-Object).Count -gt 0 -or -not [string]::IsNullOrWhiteSpace($alertType)) { return "pass" }
            return "failed:no_alert"
        }
        "review_or_denied" {
            if ($decision -in @("review_required", "denied")) { return "pass" }
            return "failed:decision_$decision"
        }
        default { return "unknown_target" }
    }
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    $Token = Get-AccessToken -BaseUrl $ApiBase -User $Username -Pass $Password
}

$headers = @{ Authorization = "Bearer $Token" }

Write-Host "== Phase 1 Calibration Terrain =="
Write-Host "API: $ApiBase"
Write-Host "CameraId: $CameraId"

$health = Invoke-RestMethod -Uri "$ApiBase/api/system/health/full?window_minutes=60&persist=true" -Headers $headers -Method Get -TimeoutSec 30
Write-Host ("System health status: " + [string]$health.status)

$tests = @(
    @{ id = "T1_clean_day"; label = "Plaque propre jour"; image = $PlateCleanImage; target = "allowed" },
    @{ id = "T2_dirty_plate"; label = "Plaque sale"; image = $PlateDirtyImage; target = "allowed_or_review" },
    @{ id = "T3_diff_plate_same_car"; label = "Plaque differente meme voiture"; image = $DifferentPlateSameCarImage; target = "alert_generated" },
    @{ id = "T4_good_plate_wrong_car"; label = "Plaque bonne mauvaise voiture"; image = $GoodPlateWrongCarImage; target = "review_or_denied" }
)

$results = @()
foreach ($test in $tests) {
    $exists = Test-Path $test.image
    if (-not $exists) {
        $results += [pscustomobject]@{
            id = $test.id
            label = $test.label
            image = $test.image
            target = $test.target
            verdict = "skipped:image_not_found"
            http_status = 0
            decision = $null
            alert_type = $null
            confidence = $null
        }
        continue
    }

    $resp = Invoke-MultipartRecognize -BaseUrl $ApiBase -AccessToken $Token -CamId $CameraId -ImagePath $test.image -Gate $GateId -Dir $Direction
    $verdict = Evaluate-TestResult -Target $test.target -Response $resp
    $results += [pscustomobject]@{
        id = $test.id
        label = $test.label
        image = $test.image
        target = $test.target
        verdict = $verdict
        http_status = $resp.status_code
        decision = if ($resp.body) { [string]$resp.body.decision } else { $null }
        alert_type = if ($resp.body) { [string]$resp.body.alert_type } else { $null }
        confidence = if ($resp.body) { [double]$resp.body.confidence } else { $null }
    }
}

$passCount = ($results | Where-Object { $_.verdict -eq "pass" } | Measure-Object).Count
$totalCount = ($results | Measure-Object).Count

$report = [pscustomobject]@{
    phase = "phase1_calibration_terrain"
    timestamp = (Get-Date).ToString("o")
    api_base = $ApiBase
    camera_id = $CameraId
    thresholds = [pscustomobject]@{
        VEHICLE_ACCESS_MIN_CONF_ALLOW = $env:VEHICLE_ACCESS_MIN_CONF_ALLOW
        VEHICLE_ACCESS_MIN_CONF_REVIEW = $env:VEHICLE_ACCESS_MIN_CONF_REVIEW
        VEHICLE_ACCESS_VISUAL_MISMATCH_THRESHOLD = $env:VEHICLE_ACCESS_VISUAL_MISMATCH_THRESHOLD
    }
    system_health_status = [string]$health.status
    passed = $passCount
    total = $totalCount
    results = $results
}

$null = New-Item -ItemType Directory -Force -Path "logs"
$reportPath = "logs\\phase1_calibration_report_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ""
Write-Host "Calibration results:"
$results | Format-Table id, verdict, http_status, decision, alert_type, confidence -AutoSize
Write-Host ""
Write-Host "Report saved: $reportPath"
