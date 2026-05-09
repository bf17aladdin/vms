#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Start Falcon AI Vision backend + frontend

.DESCRIPTION
  Picks a Python interpreter that has required backend modules
  (fastapi, uvicorn, slowapi, email_validator), then starts:
  - backend on http://127.0.0.1:5003
  - frontend on http://localhost:3000
#>

$ErrorActionPreference = "Stop"
$BaseDir = [string]$PSScriptRoot
$ParentDir = Split-Path -Path $BaseDir -Parent
$PlatformDir = $null
function Resolve-FirstExistingPath {
  param(
    [Parameter(Mandatory = $true)][string[]]$Candidates
  )
  foreach ($path in $Candidates) {
    if (Test-Path $path) {
      return $path
    }
  }
  return $null
}

function Resolve-AppDirectory {
  param(
    [Parameter(Mandatory = $true)][string[]]$Candidates,
    [Parameter(Mandatory = $true)][string[]]$Markers
  )

  $seen = New-Object 'System.Collections.Generic.HashSet[string]'

  function Test-Candidate {
    param([string]$CandidatePath)
    if ([string]::IsNullOrWhiteSpace($CandidatePath)) {
      return $null
    }
    try {
      $resolved = [string](Resolve-Path -LiteralPath $CandidatePath -ErrorAction Stop).Path
    } catch {
      return $null
    }
    if (-not $seen.Add($resolved)) {
      return $null
    }
    foreach ($marker in $Markers) {
      if (Test-Path (Join-Path -Path $resolved -ChildPath $marker)) {
        return $resolved
      }
    }
    return $null
  }

  foreach ($candidate in $Candidates) {
    $direct = Test-Candidate -CandidatePath $candidate
    if ($direct) {
      return $direct
    }
  }

  foreach ($candidate in $Candidates) {
    if (-not (Test-Path -LiteralPath $candidate)) {
      continue
    }
    try {
      $children = Get-ChildItem -LiteralPath $candidate -Directory -ErrorAction SilentlyContinue
    } catch {
      continue
    }
    foreach ($child in $children) {
      $nested = Test-Candidate -CandidatePath $child.FullName
      if ($nested) {
        return $nested
      }
    }
  }

  return $null
}

$platformCandidates = @(
  (Join-Path -Path $BaseDir -ChildPath "falcon-ai-vision-platform"),
  (Join-Path -Path $BaseDir -ChildPath "flacon_ai_vision-platform"),
  (Join-Path -Path $BaseDir -ChildPath "eye-of-falcon-platform"),
  (Join-Path -Path $BaseDir -ChildPath "flacon_ai_vision"),
  $BaseDir,
  $ParentDir
)

$PlatformDir = Resolve-AppDirectory -Candidates $platformCandidates -Markers @(
  "backend\vms\backend\main.py",
  "frontend\package.json"
)
if (-not $PlatformDir) {
  $PlatformDir = $BaseDir
}

$BackendDir = Resolve-AppDirectory -Candidates @(
  (Join-Path -Path $BaseDir -ChildPath "backend"),
  (Join-Path -Path $PlatformDir -ChildPath "backend"),
  (Join-Path -Path $BaseDir -ChildPath "flacon_ai_vision\backend"),
  (Join-Path -Path $BaseDir -ChildPath "eye-of-falcon-platform\backend"),
  (Join-Path -Path $BaseDir -ChildPath "falcon-ai-vision-platform\backend"),
  (Join-Path -Path $BaseDir -ChildPath "flacon_ai_vision-platform\backend"),
  (Join-Path -Path $ParentDir -ChildPath "backend")
) -Markers @(
  "vms\backend\main.py",
  "vms\backend\__init__.py"
)
$FrontendDir = Resolve-AppDirectory -Candidates @(
  (Join-Path -Path $BaseDir -ChildPath "frontend"),
  (Join-Path -Path $BaseDir -ChildPath "flacon_ai_vision\frontend"),
  (Join-Path -Path $PlatformDir -ChildPath "frontend"),
  (Join-Path -Path $BaseDir -ChildPath "eye-of-falcon-platform\frontend"),
  (Join-Path -Path $BaseDir -ChildPath "falcon-ai-vision-platform\frontend"),
  (Join-Path -Path $BaseDir -ChildPath "flacon_ai_vision-platform\frontend"),
  (Join-Path -Path $ParentDir -ChildPath "frontend")
) -Markers @(
  "package.json",
  "vite.config.ts",
  "vite.config.js"
)

if (-not $BackendDir) {
  Write-Host "Backend directory not found. Check project layout." -ForegroundColor Red
  exit 1
}
if (-not $FrontendDir) {
  Write-Host "Frontend directory not found. Check project layout." -ForegroundColor Red
  exit 1
}
$RequiredPythonMajor = 3
$RequiredPythonMinor = 11

# Load .env into current process so backend subprocess inherits runtime config
# (DATABASE_URL, FACE_PGVECTOR_ENABLED, etc.).
$EnvCandidates = @(
  (Join-Path $PlatformDir ".env"),
  (Join-Path $BaseDir ".env")
)
$EnvPath = $EnvCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($EnvPath) {
  Get-Content $EnvPath | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $eq = $line.IndexOf("=")
    if ($eq -le 0) { return }
    $key = $line.Substring(0, $eq).Trim()
    $value = $line.Substring($eq + 1).Trim()
    if ($value.StartsWith('"') -and $value.EndsWith('"') -and $value.Length -ge 2) {
      $value = $value.Substring(1, $value.Length - 2)
    } elseif ($value.StartsWith("'") -and $value.EndsWith("'") -and $value.Length -ge 2) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
  }
}

# Force the current local development topology for this launcher.
[System.Environment]::SetEnvironmentVariable("APP_ENV", "development", "Process")
[System.Environment]::SetEnvironmentVariable("ENVIRONMENT", "development", "Process")
[System.Environment]::SetEnvironmentVariable("SERVE_FRONTEND_FROM_BACKEND", "false", "Process")
if ([string]::IsNullOrWhiteSpace($env:RELOAD)) {
  # Default reload off: Uvicorn reload can be noisy/unstable on some Windows setups.
  [System.Environment]::SetEnvironmentVariable("RELOAD", "false", "Process")
}

function Wait-HttpReady {
  param(
    [Parameter(Mandatory = $true)][string]$Url,
    [int]$TimeoutSeconds = 20
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    try {
      # -UseBasicParsing exists in Windows PowerShell 5.1 but was removed in PowerShell 6+.
      if ((Get-Command Invoke-WebRequest).Parameters.ContainsKey("UseBasicParsing")) {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
      } else {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec 3
      }
      if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        return $true
      }
    } catch {
      Start-Sleep -Milliseconds 750
    }
  }
  return $false
}

function Test-BackendPython {
  param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [string[]]$PrefixArgs = @()
  )

  if (($Exe -match "[\\/]") -and -not (Test-Path $Exe)) {
    return $false
  }

  try {
    & $Exe @PrefixArgs -c "import importlib.util,sys;mods=('fastapi','uvicorn','slowapi','email_validator','argon2','socketio');vok=(sys.version_info[:2]==($RequiredPythonMajor,$RequiredPythonMinor));mok=all(importlib.util.find_spec(m) for m in mods);sys.exit(0 if (vok and mok) else 1)" *> $null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Get-ListeningPid {
  param(
    [Parameter(Mandatory = $true)][int]$Port
  )

  # Prefer Get-NetTCPConnection when available/allowed, but fall back to netstat
  # because CIM access can be denied for non-admin shells on some machines.
  try {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    if ($conn -and $conn.OwningProcess) {
      return [int]$conn.OwningProcess
    }
  } catch {
  }

  try {
    $regex = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    $lines = netstat -ano | ForEach-Object { $_.ToString() }
    foreach ($line in $lines) {
      if ($line -match $regex) {
        return [int]$Matches[1]
      }
    }
  } catch {
  }

  return $null
}

function Stop-ProcessTree {
  param(
    [Parameter(Mandatory = $true)][int]$ProcessId
  )

  if (-not $ProcessId) {
    return $false
  }

  try {
    & taskkill /PID $ProcessId /T /F *> $null
    if ($LASTEXITCODE -eq 0) {
      return $true
    }
  } catch {
  }

  try {
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    return $true
  } catch {
  }

  return $false
}

function Wait-PortFree {
  param(
    [Parameter(Mandatory = $true)][int]$Port,
    [int]$TimeoutSeconds = 10
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $pidInUse = Get-ListeningPid -Port $Port
    if (-not $pidInUse) {
      return $true
    }
    Start-Sleep -Milliseconds 400
  }
  return $false
}

function Start-BackendProcess {
  param(
    [Parameter(Mandatory = $true)][hashtable]$PythonCandidate,
    [bool]$UseReload = $false,
    [string]$StdoutPath = $null,
    [string]$StderrPath = $null
  )

  $backendArgs = @()
  if ($PythonCandidate.PrefixArgs) {
    $backendArgs += $PythonCandidate.PrefixArgs
  }
  $backendArgs += @("-m", "uvicorn", "vms.backend.main:app", "--port", "5003", "--host", "127.0.0.1")
  if ($UseReload) {
    $backendArgs += "--reload"
  }

  $startParams = @{
    FilePath         = $PythonCandidate.Exe
    ArgumentList     = $backendArgs
    WorkingDirectory = $BackendDir
    PassThru         = $true
  }
  if (-not [string]::IsNullOrWhiteSpace($StdoutPath)) {
    $startParams.RedirectStandardOutput = $StdoutPath
  }
  if (-not [string]::IsNullOrWhiteSpace($StderrPath)) {
    $startParams.RedirectStandardError = $StderrPath
  }

  return Start-Process @startParams
}

$override = $env:BACKEND_PYTHON
$candidates = @()
if (-not [string]::IsNullOrWhiteSpace($override)) {
  $candidates += @{ Exe = $override; PrefixArgs = @(); Label = "BACKEND_PYTHON=$override" }
}

$candidates += @(
  @{ Exe = (Join-Path $BaseDir "venv_ai\Scripts\python.exe"); PrefixArgs = @(); Label = "venv_ai\Scripts\python.exe" },
  @{ Exe = (Join-Path $BaseDir "venv\Scripts\python.exe"); PrefixArgs = @(); Label = "venv\Scripts\python.exe" },
  @{ Exe = (Join-Path $BaseDir ".venv\Scripts\python.exe"); PrefixArgs = @(); Label = ".venv\Scripts\python.exe" },
  @{ Exe = "py"; PrefixArgs = @("-3.11"); Label = "py -3.11" },
  @{ Exe = "python"; PrefixArgs = @(); Label = "python" }
)

$selected = $null
foreach ($candidate in $candidates) {
  if (Test-BackendPython -Exe $candidate.Exe -PrefixArgs $candidate.PrefixArgs) {
    $selected = $candidate
    break
  }
}

if ($null -eq $selected) {
  Write-Host "No usable Python 3.11 found for backend." -ForegroundColor Red
  Write-Host "Install missing modules in Python 3.11: fastapi, uvicorn, slowapi, email-validator, argon2-cffi, python-socketio." -ForegroundColor Yellow
  exit 1
}

Write-Host "Backend Python: $($selected.Label)" -ForegroundColor Green

$existingPid = Get-ListeningPid -Port 5003
if ($existingPid) {
  $owningProcessId = $existingPid
  $owningProcess = $null
  try {
    if ($owningProcessId) {
      $owningProcess = Get-Process -Id $owningProcessId -ErrorAction SilentlyContinue
    }
  } catch {
  }
  $procName = if ($owningProcess) { $owningProcess.ProcessName } else { "unknown" }

  Write-Host "Port 5003 is already in use by PID $owningProcessId ($procName). Stop it, then retry." -ForegroundColor Red
  if ($owningProcessId) {
    Write-Host "Tip: Stop-Process -Id $owningProcessId -Force" -ForegroundColor DarkYellow
  }
  exit 1
}

$existingFrontendPid = Get-ListeningPid -Port 3000
if ($existingFrontendPid) {
  $owningProcessId = $existingFrontendPid
  $owningProcess = $null
  try {
    if ($owningProcessId) {
      $owningProcess = Get-Process -Id $owningProcessId -ErrorAction SilentlyContinue
    }
  } catch {
  }
  $procName = if ($owningProcess) { $owningProcess.ProcessName } else { "unknown" }

  Write-Host "Port 3000 is already in use by PID $owningProcessId ($procName). Stop it, then retry." -ForegroundColor Red
  if ($owningProcessId) {
    Write-Host "Tip: Stop-Process -Id $owningProcessId -Force" -ForegroundColor DarkYellow
  }
  exit 1
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue) -and -not (Get-Command npm -ErrorAction SilentlyContinue)) {
  Write-Host "npm was not found in PATH. Install Node.js before running START_FINAL." -ForegroundColor Red
  exit 1
}

$backendReloadRequested = $env:RELOAD -and $env:RELOAD.ToLower() -eq "true"
$backendReloadActive = $backendReloadRequested

function Show-LogTail {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [int]$TailLines = 200
  )

  if (-not (Test-Path $Path)) {
    Write-Host "(log not found) $Path" -ForegroundColor DarkYellow
    return
  }

  Write-Host ""
  Write-Host "--- $Path (tail $TailLines) ---" -ForegroundColor DarkCyan
  try {
    Get-Content -Path $Path -Tail $TailLines | ForEach-Object { Write-Host $_ }
  } catch {
    Write-Host "Failed to read log: $Path" -ForegroundColor Red
  }
}

$backendLogLabel = if ($backendReloadActive) { "reload" } else { "noreload" }
$backendStdoutPath = Join-Path $BaseDir ("tmp_start_final_backend_{0}_stdout.log" -f $backendLogLabel)
$backendStderrPath = Join-Path $BaseDir ("tmp_start_final_backend_{0}_stderr.log" -f $backendLogLabel)
try {
  Remove-Item -ErrorAction SilentlyContinue $backendStdoutPath, $backendStderrPath
} catch {
}

Write-Host "[1/2] Starting Backend on 127.0.0.1:5003..." -ForegroundColor Yellow
$backendProc = Start-BackendProcess -PythonCandidate $selected -UseReload:$backendReloadActive -StdoutPath $backendStdoutPath -StderrPath $backendStderrPath
Write-Host "Backend logs:" -ForegroundColor Gray
Write-Host "  stdout: $backendStdoutPath" -ForegroundColor Gray
Write-Host "  stderr: $backendStderrPath" -ForegroundColor Gray

if (-not (Wait-HttpReady -Url "http://127.0.0.1:5003/health" -TimeoutSeconds 20)) {
  if ($backendReloadRequested) {
    Write-Host "Backend reload startup failed. Retrying once without --reload..." -ForegroundColor Yellow
    try {
      Stop-ProcessTree -ProcessId $backendProc.Id | Out-Null
    } catch {
      try {
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
      } catch {
      }
    }
    if (-not (Wait-PortFree -Port 5003 -TimeoutSeconds 10)) {
      $stillPid = Get-ListeningPid -Port 5003
      Write-Host "Port 5003 is still in use by PID $stillPid. Close it, then retry." -ForegroundColor Red
      exit 1
    }
    Start-Sleep -Seconds 1
    [System.Environment]::SetEnvironmentVariable("RELOAD", "false", "Process")
    $backendReloadActive = $false
    $backendLogLabel = "noreload"
    $backendStdoutPath = Join-Path $BaseDir ("tmp_start_final_backend_{0}_stdout.log" -f $backendLogLabel)
    $backendStderrPath = Join-Path $BaseDir ("tmp_start_final_backend_{0}_stderr.log" -f $backendLogLabel)
    try {
      Remove-Item -ErrorAction SilentlyContinue $backendStdoutPath, $backendStderrPath
    } catch {
    }
    $backendProc = Start-BackendProcess -PythonCandidate $selected -UseReload:$false -StdoutPath $backendStdoutPath -StderrPath $backendStderrPath
    Write-Host "Backend logs:" -ForegroundColor Gray
    Write-Host "  stdout: $backendStdoutPath" -ForegroundColor Gray
    Write-Host "  stderr: $backendStderrPath" -ForegroundColor Gray
  }

  if (-not (Wait-HttpReady -Url "http://127.0.0.1:5003/health" -TimeoutSeconds 20)) {
    Write-Host "Backend did not become ready on http://127.0.0.1:5003/health" -ForegroundColor Red
    if ($backendReloadRequested) {
      $reloadStdout = Join-Path $BaseDir "tmp_start_final_backend_reload_stdout.log"
      $reloadStderr = Join-Path $BaseDir "tmp_start_final_backend_reload_stderr.log"
      if ($reloadStderr -ne $backendStderrPath -and (Test-Path $reloadStderr)) { Show-LogTail -Path $reloadStderr -TailLines 200 }
      if ($reloadStdout -ne $backendStdoutPath -and (Test-Path $reloadStdout)) { Show-LogTail -Path $reloadStdout -TailLines 200 }
    }
    if (Test-Path $backendStderrPath) { Show-LogTail -Path $backendStderrPath -TailLines 200 }
    if (Test-Path $backendStdoutPath) { Show-LogTail -Path $backendStdoutPath -TailLines 200 }
    try {
      Stop-ProcessTree -ProcessId $backendProc.Id | Out-Null
    } catch {
      try {
        Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
      } catch {
      }
    }
    exit 1
  }
}

Write-Host "[2/2] Starting Frontend on localhost:3000..." -ForegroundColor Yellow
$frontendProc = Start-Process `
  -FilePath "cmd" `
  -ArgumentList "/k", "cd /d `"$FrontendDir`" && set VITE_FORCE_LOGIN_ON_START=true && npm run dev" `
  -WindowStyle Normal `
  -PassThru

Write-Host ""
Write-Host "Backend:  http://127.0.0.1:5003 (API/websocket only)" -ForegroundColor Cyan
Write-Host "API Docs: http://127.0.0.1:5003/docs" -ForegroundColor Cyan
Write-Host "Frontend: http://localhost:3000/login" -ForegroundColor Cyan
Write-Host "Mode:     dev (SERVE_FRONTEND_FROM_BACKEND=false)" -ForegroundColor Cyan
Write-Host "Reload:   $($backendReloadActive.ToString().ToLower())" -ForegroundColor Cyan
Write-Host "Backend PID:  $($backendProc.Id)" -ForegroundColor Gray
Write-Host "Frontend PID: $($frontendProc.Id)" -ForegroundColor Gray
Write-Host ""

Start-Process "http://localhost:3000/login"
