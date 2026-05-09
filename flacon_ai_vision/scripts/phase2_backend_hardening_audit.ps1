param(
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$AdminUsername = "admin",
    [string]$AdminPassword = "admin123",
    [int]$InvalidLoginAttempts = 20
)

$ErrorActionPreference = "Stop"

function Invoke-StatusCode {
    param(
        [string]$Method,
        [string]$Url,
        [hashtable]$Headers = $null,
        [object]$Body = $null,
        [string]$ContentType = "application/json"
    )
    $hasBody = ($null -ne $Body) -and (-not [string]::IsNullOrWhiteSpace([string]$Body))
    try {
        if ($hasBody -and $null -ne $Headers) {
            $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method $Method -Headers $Headers -Body $Body -ContentType $ContentType -TimeoutSec 20
        } elseif ($hasBody) {
            $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method $Method -Body $Body -ContentType $ContentType -TimeoutSec 20
        } elseif ($null -ne $Headers) {
            $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method $Method -Headers $Headers -TimeoutSec 20
        } else {
            $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method $Method -TimeoutSec 20
        }
        return 200
    } catch {
        if ($_.Exception.Response) {
            return [int]$_.Exception.Response.StatusCode
        }
        return 0
    }
}

function Login-User {
    param([string]$BaseUrl, [string]$Username, [string]$Password)
    $body = @{ username = $Username; password = $Password } | ConvertTo-Json
    return Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 30
}

Write-Host "== Phase 2 Backend Hardening Audit =="
Write-Host "API: $ApiBase"

$checks = @()

# Check 1: Protected endpoints require auth.
$protected = @(
    @{ method = "GET"; path = "/api/personnel?skip=0&limit=10"; name = "personnel_protected" },
    @{ method = "GET"; path = "/api/system/health/full"; name = "system_health_protected" },
    @{ method = "GET"; path = "/api/vehicle/access/alerts?limit=5"; name = "vehicle_alerts_protected" },
    @{ method = "POST"; path = "/api/vehicle/recognize/camera/1"; name = "vehicle_camera_protected"; body = "{}" }
)

foreach ($item in $protected) {
    $code = Invoke-StatusCode -Method $item.method -Url ($ApiBase + $item.path) -Body $item.body
    $pass = $code -in @(401, 403)
    $checks += [pscustomobject]@{
        check = $item.name
        expected = "401_or_403"
        actual = $code
        pass = $pass
    }
}

# Check 2: Admin login + refresh rotation.
$adminLogin = Login-User -BaseUrl $ApiBase -Username $AdminUsername -Password $AdminPassword
$adminToken = [string]$adminLogin.access_token
$refreshToken = [string]$adminLogin.refresh_token

$checks += [pscustomobject]@{
    check = "admin_login_success"
    expected = "token_non_empty"
    actual = if ([string]::IsNullOrWhiteSpace($adminToken)) { "empty" } else { "non_empty" }
    pass = -not [string]::IsNullOrWhiteSpace($adminToken)
}

$refreshBody = @{ refresh_token = $refreshToken } | ConvertTo-Json
$refreshCode = 0
$refreshPass = $false
for ($attempt = 1; $attempt -le 2; $attempt++) {
    try {
        $refreshResp = Invoke-RestMethod -Uri "$ApiBase/api/auth/refresh" -Method Post -ContentType "application/json" -Body $refreshBody -TimeoutSec 30
        $refreshPass = -not [string]::IsNullOrWhiteSpace([string]$refreshResp.access_token) -and (-not [string]::IsNullOrWhiteSpace([string]$refreshResp.refresh_token))
        $refreshCode = 200
        break
    } catch {
        if ($_.Exception.Response) {
            $refreshCode = [int]$_.Exception.Response.StatusCode
        }
        if ($attempt -lt 2) {
            Start-Sleep -Seconds 2
        }
    }
}
$checks += [pscustomobject]@{
    check = "refresh_token_flow"
    expected = "new_access_and_refresh"
    actual = if ($refreshPass) { "ok" } else { "http_$refreshCode" }
    pass = $refreshPass
}

# Check 3: Role enforcement for admin endpoint.
$adminHeaders = @{ Authorization = "Bearer $adminToken"; "Content-Type" = "application/json" }
$operatorUsername = "audit_operator_{0}" -f (Get-Random -Minimum 1000 -Maximum 9999)
$operatorPassword = "Op3rator!123"
$createBody = @{
    username = $operatorUsername
    password = $operatorPassword
    full_name = "Audit Operator"
    email = ($operatorUsername + "@example.com")
    role = "operator"
} | ConvertTo-Json

$operatorCheckCode = 0
$operatorCheckPass = $false
try {
    $null = Invoke-RestMethod -Uri "$ApiBase/api/users" -Headers $adminHeaders -Method Post -Body $createBody -TimeoutSec 30
    $opLogin = Login-User -BaseUrl $ApiBase -Username $operatorUsername -Password $operatorPassword
    $opToken = [string]$opLogin.access_token
    $opHeaders = @{ Authorization = "Bearer $opToken" }
    $operatorCheckCode = Invoke-StatusCode -Method "GET" -Url "$ApiBase/api/admin/health" -Headers $opHeaders
    $operatorCheckPass = ($operatorCheckCode -eq 403)
} catch {
    if ($_.Exception.Response) {
        $operatorCheckCode = [int]$_.Exception.Response.StatusCode
    }
}
$checks += [pscustomobject]@{
    check = "operator_cannot_access_admin_health"
    expected = 403
    actual = $operatorCheckCode
    pass = $operatorCheckPass
}

# Check 4: Audit endpoint available for admin.
$auditCode = Invoke-StatusCode -Method "GET" -Url "$ApiBase/api/users/audit/history?limit=5" -Headers @{ Authorization = "Bearer $adminToken" }
$checks += [pscustomobject]@{
    check = "admin_audit_history_available"
    expected = 200
    actual = $auditCode
    pass = ($auditCode -eq 200)
}

# Check 5: Login rate limiting.
$rateLimitHit = $false
for ($i = 1; $i -le $InvalidLoginAttempts; $i++) {
    $invalidBody = @{ username = "invalid_user"; password = "bad_password_$i" } | ConvertTo-Json
    $code = Invoke-StatusCode -Method "POST" -Url "$ApiBase/api/auth/login" -Body $invalidBody
    if ($code -eq 429) {
        $rateLimitHit = $true
        break
    }
}
$checks += [pscustomobject]@{
    check = "login_rate_limit_triggered"
    expected = "at_least_one_429"
    actual = if ($rateLimitHit) { "429_detected" } else { "not_detected" }
    pass = $rateLimitHit
}

$passCount = ($checks | Where-Object { $_.pass -eq $true } | Measure-Object).Count
$totalCount = ($checks | Measure-Object).Count

$report = [pscustomobject]@{
    phase = "phase2_backend_hardening_audit"
    timestamp = (Get-Date).ToString("o")
    api_base = $ApiBase
    checks_passed = $passCount
    checks_total = $totalCount
    checks = $checks
}

$null = New-Item -ItemType Directory -Force -Path "logs"
$reportPath = "logs\\phase2_hardening_audit_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ""
Write-Host "Hardening audit results:"
$checks | Format-Table check, expected, actual, pass -AutoSize
Write-Host ""
Write-Host "Report saved: $reportPath"
