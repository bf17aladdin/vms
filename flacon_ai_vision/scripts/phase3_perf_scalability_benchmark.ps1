param(
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$Token = "",
    [string]$Username = "admin",
    [string]$Password = "admin123",
    [int]$Warmup = 3,
    [int]$Iterations = 25,
    [int]$CameraIdForAsync = 1,
    [switch]$IncludeCameraAsyncTest
)

$ErrorActionPreference = "Stop"

function Login-GetToken {
    param([string]$BaseUrl, [string]$User, [string]$Pass)
    $body = @{ username = $User; password = $Pass } | ConvertTo-Json
    $resp = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 30
    return [string]$resp.access_token
}

function Invoke-TimedRequest {
    param(
        [string]$Method,
        [string]$Url,
        [hashtable]$Headers = $null,
        [object]$Body = $null
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $status = 0
    $hasBody = ($null -ne $Body) -and (-not [string]::IsNullOrWhiteSpace([string]$Body))
    try {
        if ($hasBody -and $null -ne $Headers) {
            $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method $Method -Headers $Headers -Body $Body -ContentType "application/json" -TimeoutSec 30
        } elseif ($hasBody) {
            $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method $Method -Body $Body -ContentType "application/json" -TimeoutSec 30
        } elseif ($null -ne $Headers) {
            $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method $Method -Headers $Headers -TimeoutSec 30
        } else {
            $null = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method $Method -TimeoutSec 30
        }
        $status = 200
    } catch {
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
        } else {
            $status = 0
        }
    } finally {
        $sw.Stop()
    }

    return [pscustomobject]@{
        ms = [math]::Round($sw.Elapsed.TotalMilliseconds, 2)
        status = $status
    }
}

function Get-LatencyStats {
    param([double[]]$Values)
    if ($null -eq $Values -or $Values.Count -eq 0) {
        return [pscustomobject]@{ avg = 0; p50 = 0; p95 = 0; max = 0 }
    }
    $sorted = $Values | Sort-Object
    $count = $sorted.Count
    $idx50 = [int][math]::Floor(($count - 1) * 0.50)
    $idx95 = [int][math]::Floor(($count - 1) * 0.95)
    return [pscustomobject]@{
        avg = [math]::Round((($Values | Measure-Object -Average).Average), 2)
        p50 = [math]::Round($sorted[$idx50], 2)
        p95 = [math]::Round($sorted[$idx95], 2)
        max = [math]::Round(($Values | Measure-Object -Maximum).Maximum, 2)
    }
}

if ([string]::IsNullOrWhiteSpace($Token)) {
    $Token = Login-GetToken -BaseUrl $ApiBase -User $Username -Pass $Password
}

$headers = @{ Authorization = "Bearer $Token" }

Write-Host "== Phase 3 Performance & Scalability Benchmark =="
Write-Host "API: $ApiBase"
Write-Host "Warmup: $Warmup"
Write-Host "Iterations: $Iterations"

$targets = @(
    @{ name = "health_live"; method = "GET"; url = "$ApiBase/api/health/live"; headers = $null; body = $null },
    @{ name = "system_health_full"; method = "GET"; url = "$ApiBase/api/system/health/full?persist=false&window_minutes=15"; headers = $headers; body = $null },
    @{ name = "vehicle_history"; method = "GET"; url = "$ApiBase/api/vehicle/history?limit=20"; headers = $headers; body = $null },
    @{ name = "vehicle_access_alerts"; method = "GET"; url = "$ApiBase/api/vehicle/access/alerts?limit=20"; headers = $headers; body = $null }
)

if ($IncludeCameraAsyncTest.IsPresent) {
    $targets += @{ name = "vehicle_async_recognize"; method = "POST"; url = "$ApiBase/api/vehicle/recognize/camera/$CameraIdForAsync/async"; headers = $headers; body = "{}" }
}

$allResults = @()
foreach ($target in $targets) {
    for ($i = 1; $i -le $Warmup; $i++) {
        $null = Invoke-TimedRequest -Method $target.method -Url $target.url -Headers $target.headers -Body $target.body
    }

    $latencies = @()
    $statusCodes = @()
    for ($i = 1; $i -le $Iterations; $i++) {
        $res = Invoke-TimedRequest -Method $target.method -Url $target.url -Headers $target.headers -Body $target.body
        $latencies += [double]$res.ms
        $statusCodes += [int]$res.status
    }

    $stats = Get-LatencyStats -Values $latencies
    $successCount = ($statusCodes | Where-Object { $_ -eq 200 } | Measure-Object).Count

    $allResults += [pscustomobject]@{
        endpoint = $target.name
        method = $target.method
        success_count = $successCount
        total_count = $Iterations
        success_rate = [math]::Round(($successCount / [math]::Max($Iterations, 1)) * 100, 2)
        avg_ms = $stats.avg
        p50_ms = $stats.p50
        p95_ms = $stats.p95
        max_ms = $stats.max
    }
}

$report = [pscustomobject]@{
    phase = "phase3_performance_scalability"
    timestamp = (Get-Date).ToString("o")
    api_base = $ApiBase
    iterations = $Iterations
    warmup = $Warmup
    results = $allResults
}

$null = New-Item -ItemType Directory -Force -Path "logs"
$reportPath = "logs\\phase3_perf_report_{0}.json" -f (Get-Date -Format "yyyyMMdd_HHmmss")
$report | ConvertTo-Json -Depth 7 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ""
Write-Host "Performance summary:"
$allResults | Format-Table endpoint, success_rate, avg_ms, p50_ms, p95_ms, max_ms -AutoSize
Write-Host ""
Write-Host "Report saved: $reportPath"
