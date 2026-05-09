$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonCandidates = @(
  (Join-Path $repoRoot "venv_ai\Scripts\python.exe"),
  (Join-Path $repoRoot ".venv\Scripts\python.exe"),
  (Join-Path $repoRoot "venv\Scripts\python.exe"),
  "python"
)

$pythonExe = $null
foreach ($candidate in $pythonCandidates) {
  if ($candidate -eq "python") {
    $pythonExe = $candidate
    break
  }
  if (Test-Path $candidate) {
    $pythonExe = $candidate
    break
  }
}

if (-not $pythonExe) {
  throw "Python executable not found."
}

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Join-Path $repoRoot "backend")
if ($previousPythonPath) {
  $env:PYTHONPATH = "$env:PYTHONPATH;$previousPythonPath"
}

Push-Location $repoRoot
try {
  & $pythonExe -m pytest -p no:cacheprovider backend/vms/backend/tests/integration -q @args
} finally {
  Pop-Location
  $env:PYTHONPATH = $previousPythonPath
}
