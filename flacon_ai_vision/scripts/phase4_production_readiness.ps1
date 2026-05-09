[CmdletBinding()]
param(
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$FrontendBase = "http://localhost:3000",
    [string]$Username = "admin",
    [string]$Password = "admin123",
    [int]$TimeoutSec = 12,
    [switch]$RequireFrontend,
    [switch]$RequireGpu,
    [switch]$SkipGpuCheck,
    [switch]$SkipModuleVerification,
    [switch]$SkipSystemHealth,
    [switch]$SkipScalingMonitor,
    [switch]$IncludePerfProbe,
    [string]$OutputJson = ""
)

$ErrorActionPreference = "Stop"

function Resolve-PythonExe {
    $candidates = @(
        (Join-Path $PSScriptRoot "..\venv_ai\Scripts\python.exe"),
        "python"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -eq "python") {
            try {
                $null = & python --version 2>$null
                if ($LASTEXITCODE -eq 0) {
                    return "python"
                }
            } catch {
                continue
            }
        } elseif (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    throw "Python executable not found."
}

function Invoke-JsonRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        [hashtable]$Headers = $null,
        [object]$Body = $null
    )

    $invokeParams = @{
        Uri         = $Url
        Method      = $Method
        TimeoutSec  = $TimeoutSec
        ContentType = "application/json"
    }
    if ($null -ne $Headers) {
        $invokeParams["Headers"] = $Headers
    }
    if ($null -ne $Body) {
        $invokeParams["Body"] = ($Body | ConvertTo-Json -Depth 8)
    }
    return Invoke-RestMethod @invokeParams
}

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("OK", "WARN", "FAIL")] [string]$Status,
        [Parameter(Mandatory = $true)][string]$Detail,
        [double]$DurationMs = 0,
        [object]$Data = $null
    )

    $script:Checks.Add([pscustomobject]@{
        name        = $Name
        status      = $Status
        detail      = $Detail
        duration_ms = [math]::Round([double]$DurationMs, 2)
        data        = $Data
    })
}

function Invoke-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action,
        [switch]$WarnOnly
    )

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $result = & $Action
        $sw.Stop()
        $detail = "ok"
        $data = $null
        if ($result -is [hashtable]) {
            if ($result.ContainsKey("detail")) {
                $detail = [string]$result["detail"]
            }
            if ($result.ContainsKey("data")) {
                $data = $result["data"]
            } else {
                $data = $result
            }
        } elseif ($result -is [pscustomobject]) {
            if ($result.PSObject.Properties["detail"]) {
                $detail = [string]$result.detail
            }
            if ($result.PSObject.Properties["data"]) {
                $data = $result.data
            } else {
                $data = $result
            }
        } elseif ($null -ne $result) {
            $detail = [string]$result
        }
        Add-Check -Name $Name -Status "OK" -Detail $detail -DurationMs $sw.Elapsed.TotalMilliseconds -Data $data
        return $true
    } catch {
        $sw.Stop()
        $status = if ($WarnOnly) { "WARN" } else { "FAIL" }
        Add-Check -Name $Name -Status $status -Detail $_.Exception.Message -DurationMs $sw.Elapsed.TotalMilliseconds
        return $false
    }
}

function Login-GetToken {
    $resp = Invoke-JsonRequest -Method "POST" -Url "$ApiBase/api/auth/login" -Body @{
        username = $Username
        password = $Password
    }
    $token = [string]$resp.access_token
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "Login succeeded but access_token missing."
    }
    return $token
}

$script:Checks = New-Object System.Collections.Generic.List[object]
$logsDir = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "logs"
$null = New-Item -ItemType Directory -Force -Path $logsDir

if ([string]::IsNullOrWhiteSpace($OutputJson)) {
    $OutputJson = Join-Path $logsDir ("phase4_production_readiness_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
}

$pythonExe = Resolve-PythonExe
$token = $null

Write-Host "== Phase 4 Production Readiness =="
Write-Host "API:      $ApiBase"
Write-Host "Frontend: $FrontendBase"
Write-Host "Python:   $pythonExe"

Invoke-Check -Name "backend_live" -Action {
    $resp = Invoke-JsonRequest -Method "GET" -Url "$ApiBase/api/health/live"
    return @{
        detail = "status=$($resp.status)"
        data   = $resp
    }
} | Out-Null

Invoke-Check -Name "backend_ready" -Action {
    $resp = Invoke-JsonRequest -Method "GET" -Url "$ApiBase/api/health/ready"
    if (-not [bool]$resp.ready) {
        throw "Backend ready=false"
    }
    return @{
        detail = "status=$($resp.status)"
        data   = $resp
    }
} | Out-Null

$loginOk = Invoke-Check -Name "auth_login" -Action {
    $script:token = Login-GetToken
    return @{
        detail = "login ok"
        data   = @{ token_prefix = $script:token.Substring(0, [Math]::Min(16, $script:token.Length)) }
    }
}

if (-not $SkipGpuCheck) {
    Invoke-Check -Name "gpu_stack" -Action {
        $raw = & $pythonExe (Join-Path $PSScriptRoot "verify_gpu_stack.py") 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            throw "verify_gpu_stack.py failed: $raw"
        }
        $report = $raw | ConvertFrom-Json
        $gpuReady = [bool]$report.summary.gpu_ready
        if (-not $gpuReady) {
            throw "runtime verdict is $($report.summary.verdict)"
        }
        return @{
            detail = "verdict=$($report.summary.verdict)"
            data   = $report
        }
    } -WarnOnly:(!$RequireGpu) | Out-Null
}

$smokeOutputPath = Join-Path $logsDir ("phase4_smoke_api_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Invoke-Check -Name "api_smoke" -Action {
    $env:SMOKE_BASE_URL = $ApiBase
    $env:SMOKE_TIMEOUT_SEC = [string]$TimeoutSec
    $env:SMOKE_USERNAME = $Username
    $env:SMOKE_PASSWORD = $Password
    $env:SMOKE_INCLUDE_OBSERVABILITY = "true"
    $env:SMOKE_OUTPUT_JSON = $smokeOutputPath
    $raw = & $pythonExe (Join-Path $PSScriptRoot "smoke_api.py") 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    Remove-Item Env:SMOKE_BASE_URL,Env:SMOKE_TIMEOUT_SEC,Env:SMOKE_USERNAME,Env:SMOKE_PASSWORD,Env:SMOKE_INCLUDE_OBSERVABILITY,Env:SMOKE_OUTPUT_JSON -ErrorAction SilentlyContinue
    if ($exitCode -ne 0) {
        throw "smoke_api.py failed: $raw"
    }
    $report = Get-Content $smokeOutputPath -Raw | ConvertFrom-Json
    return @{
        detail = "$($report.summary.passed)/$($report.summary.total) smoke checks passed"
        data   = $report
    }
} | Out-Null

if (-not $SkipModuleVerification) {
    Invoke-Check -Name "live_modules" -Action {
        $verifyScript = Join-Path $PSScriptRoot "verify_live_modules.ps1"
        $args = @(
            "-ExecutionPolicy", "Bypass",
            "-File", $verifyScript,
            "-BackendBase", $ApiBase,
            "-FrontendBase", $FrontendBase
        )
        if ($RequireFrontend) {
            $args += "-RequireFrontend"
        }
        $raw = & powershell @args 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            throw $raw.Trim()
        }
        return @{
            detail = "verify_live_modules ok"
            data   = @{ output = $raw.Trim() }
        }
    } | Out-Null
}

if ($loginOk -and -not $SkipSystemHealth) {
    $authHeaders = @{ Authorization = "Bearer $token" }

    Invoke-Check -Name "system_health_full" -Action {
        $resp = Invoke-JsonRequest -Method "GET" -Url "$ApiBase/api/system/health/full?persist=false&window_minutes=60" -Headers $authHeaders
        $status = ""
        if ($null -ne $resp -and $resp.PSObject.Properties["status"]) {
            $status = [string]$resp.status
        }
        if ($status -eq "down") {
            throw "system health reported down"
        }
        return @{
            detail = "status=$status"
            data   = $resp
        }
    } | Out-Null

    Invoke-Check -Name "realtime_health" -Action {
        $resp = Invoke-JsonRequest -Method "GET" -Url "$ApiBase/api/realtime/health" -Headers $authHeaders
        return @{
            detail = "connections=$($resp.active_connections)"
            data   = $resp
        }
    } | Out-Null
}

if ($loginOk -and -not $SkipScalingMonitor) {
    $authHeaders = @{ Authorization = "Bearer $token" }
    Invoke-Check -Name "scaling_monitor_dashboard" -Action {
        $resp = Invoke-JsonRequest -Method "GET" -Url "$ApiBase/api/scaling-monitor/dashboard?limit=1" -Headers $authHeaders
        return @{
            detail = "history=$((@($resp.history)).Count)"
            data   = $resp
        }
    } -WarnOnly | Out-Null
}

if ($IncludePerfProbe) {
    Invoke-Check -Name "perf_probe" -Action {
        $perfScript = Join-Path $PSScriptRoot "phase3_perf_scalability_benchmark.ps1"
        $raw = & powershell -ExecutionPolicy Bypass -File $perfScript -ApiBase $ApiBase -Username $Username -Password $Password -Warmup 1 -Iterations 8 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) {
            throw $raw.Trim()
        }
        return @{
            detail = "phase3 perf probe completed"
            data   = @{ output = $raw.Trim() }
        }
    } | Out-Null
}

$failCount = @($Checks | Where-Object { $_.status -eq "FAIL" }).Count
$warnCount = @($Checks | Where-Object { $_.status -eq "WARN" }).Count
$okCount = @($Checks | Where-Object { $_.status -eq "OK" }).Count
$overall = if ($failCount -gt 0) { "FAIL" } elseif ($warnCount -gt 0) { "WARN" } else { "OK" }

$report = [ordered]@{
    phase        = "phase4_production_readiness"
    generated_at = (Get-Date).ToString("o")
    api_base     = $ApiBase
    frontend_base = $FrontendBase
    python_exe   = $pythonExe
    summary      = [ordered]@{
        overall = $overall
        ok      = $okCount
        warn    = $warnCount
        fail    = $failCount
        total   = $Checks.Count
    }
    checks       = @($Checks)
}

$report | ConvertTo-Json -Depth 8 | Set-Content -Path $OutputJson -Encoding UTF8

Write-Host ""
$Checks | Format-Table name, status, detail, duration_ms -AutoSize
Write-Host ""
Write-Host "Summary: overall=$overall ok=$okCount warn=$warnCount fail=$failCount"
Write-Host "Report:  $OutputJson"

if ($failCount -gt 0) {
    exit 1
}
exit 0
