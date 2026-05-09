param(
    [string]$BackendBase = "http://127.0.0.1:5003",
    [string]$FrontendBase = "http://localhost:3000",
    [int]$TimeoutSec = 8,
    [switch]$RequireFrontend
)

$ErrorActionPreference = "Stop"

function Invoke-QuickGet {
    param([string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec $TimeoutSec -UseBasicParsing
        return @{
            ok = $true
            status = [int]$resp.StatusCode
            error = $null
        }
    } catch {
        $status = $null
        try { $status = [int]$_.Exception.Response.StatusCode.value__ } catch {}
        return @{
            ok = $false
            status = $status
            error = $_.Exception.Message
        }
    }
}

$results = New-Object System.Collections.Generic.List[object]
$failed = 0
$warned = 0

function Add-Result {
    param(
        [string]$Scope,
        [string]$Check,
        [bool]$Ok,
        [string]$Detail,
        [string]$Level = "ERROR"
    )

    if (-not $Ok) {
        if ($Level -eq "WARN") {
            $script:warned++
        } else {
            $script:failed++
        }
    }

    $results.Add([pscustomobject]@{
        scope  = $Scope
        check  = $Check
        status = if ($Ok) { "OK" } elseif ($Level -eq "WARN") { "WARN" } else { "FAIL" }
        detail = $Detail
    })
}

Write-Host "Live Module Verification"
Write-Host "Backend:  $BackendBase"
Write-Host "Frontend: $FrontendBase"

# 1) Backend live + OpenAPI
$health = Invoke-QuickGet "$BackendBase/health"
Add-Result -Scope "backend" -Check "health" -Ok $health.ok -Detail $(
    if ($health.ok) { "HTTP $($health.status)" } else { $health.error }
)

$openapi = $null
try {
    $openapi = Invoke-RestMethod -Uri "$BackendBase/openapi.json" -Method GET -TimeoutSec $TimeoutSec
    Add-Result -Scope "backend" -Check "openapi" -Ok $true -Detail "Loaded"
} catch {
    Add-Result -Scope "backend" -Check "openapi" -Ok $false -Detail $_.Exception.Message
}

if ($openapi -and $openapi.paths) {
    $paths = @{}
    foreach ($p in $openapi.paths.PSObject.Properties) {
        $paths[$p.Name] = $p.Value
    }

    $required = @(
        @{ module = "face";      path = "/api/face/recognize";                  methods = @("post") },
        @{ module = "vehicle";   path = "/api/vehicle/recognize/camera/{camera_id}"; methods = @("post") },
        @{ module = "security";  path = "/api/system/health/full";              methods = @("get") },
        @{ module = "admin";     path = "/api/admin/health";                    methods = @("get") },
        @{ module = "reporting"; path = "/api/reporting/health";                methods = @("get") }
    )

    foreach ($item in $required) {
        $routeFound = $paths.ContainsKey($item.path)
        Add-Result -Scope $item.module -Check "backend route $($item.path)" -Ok $routeFound -Detail $(
            if ($routeFound) { "Found" } else { "Missing in OpenAPI" }
        )

        if ($routeFound) {
            $methods = @($paths[$item.path].PSObject.Properties.Name | ForEach-Object { $_.ToLowerInvariant() })
            foreach ($m in $item.methods) {
                $hasMethod = $methods -contains $m
                Add-Result -Scope $item.module -Check "$($item.path) [$m]" -Ok $hasMethod -Detail $(
                    if ($hasMethod) { "Method present" } else { "Method missing" }
                )
            }
        }
    }
}

# 2) Frontend routes (if frontend is up)
$frontendRoot = Invoke-QuickGet "$FrontendBase/"
$frontendUp = $frontendRoot.ok
if (-not $frontendUp -and $RequireFrontend) {
    Add-Result -Scope "frontend" -Check "root" -Ok $false -Detail $frontendRoot.error
} elseif (-not $frontendUp) {
    Add-Result -Scope "frontend" -Check "root" -Ok $false -Detail "Skipped (frontend not reachable: $($frontendRoot.error))" -Level "WARN"
} else {
    Add-Result -Scope "frontend" -Check "root" -Ok $true -Detail "HTTP $($frontendRoot.status)"
    $routes = @(
        "/facial-recognition",
        "/vehicle-detection",
        "/security",
        "/admin",
        "/reporting"
    )
    foreach ($route in $routes) {
        $resp = Invoke-QuickGet "$FrontendBase$route"
        $ok = $resp.ok -and @("200", "304") -contains [string]$resp.status
        Add-Result -Scope "frontend" -Check "route $route" -Ok $ok -Detail $(
            if ($resp.ok) { "HTTP $($resp.status)" } else { $resp.error }
        )
    }
}

Write-Host ""
$results | Format-Table -AutoSize
Write-Host ""
Write-Host "Summary: FAIL=$failed WARN=$warned"

if ($failed -gt 0) {
    exit 1
}
exit 0
