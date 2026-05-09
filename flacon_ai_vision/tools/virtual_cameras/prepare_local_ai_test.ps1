param(
    [string]$PythonPath = "",
    [string]$ApiBase = "http://127.0.0.1:5003",
    [string]$ApiUsername = "admin",
    [string]$ApiPassword = "admin123",
    [int]$SampleCount = 4,
    [double]$SampleIntervalSec = 1.2,
    [switch]$SkipApiValidation
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$pythonCandidates = @()

if ($PythonPath) {
    $pythonCandidates += $PythonPath
}
$pythonCandidates += @(
    (Join-Path $repoRoot "venv_ai\Scripts\python.exe"),
    (Join-Path $repoRoot ".venv\Scripts\python.exe"),
    (Join-Path $repoRoot "venv\Scripts\python.exe"),
    "python"
)

$resolvedPython = $null
foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq "python") {
        try {
            $null = & $candidate --version 2>$null
            if ($LASTEXITCODE -eq 0) {
                $resolvedPython = $candidate
                break
            }
        } catch {
        }
    } elseif (Test-Path -LiteralPath $candidate) {
        $resolvedPython = $candidate
        break
    }
}

if (-not $resolvedPython) {
    throw "No suitable Python interpreter found. Provide -PythonPath or create venv_ai/.venv."
}

$scriptPath = Join-Path $scriptDir "prepare_local_ai_test.py"
$arguments = @(
    $scriptPath,
    "--api-base", $ApiBase,
    "--api-username", $ApiUsername,
    "--api-password", $ApiPassword,
    "--sample-count", "$SampleCount",
    "--sample-interval-sec", "$SampleIntervalSec"
)
if ($SkipApiValidation) {
    $arguments += "--skip-api-validation"
}

Write-Host "Using Python: $resolvedPython" -ForegroundColor Green
& $resolvedPython @arguments
