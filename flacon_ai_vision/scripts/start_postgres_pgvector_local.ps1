param(
  [string]$DbHost = "127.0.0.1",
  [int]$DbPort = 5434,
  [string]$DbUser = "falcon",
  [string]$DbPassword = "eye_of_falcon_pwd",
  [string]$DbName = "eye_of_falcon",
  [switch]$EnsurePgvector,
  [switch]$RunMigrations
)

$ErrorActionPreference = "Stop"

function Test-TcpPort {
  param(
    [Parameter(Mandatory = $true)][string]$Hostname,
    [Parameter(Mandatory = $true)][int]$Port,
    [int]$TimeoutMs = 2000
  )

  $client = New-Object System.Net.Sockets.TcpClient
  try {
    $task = $client.ConnectAsync($Hostname, $Port)
    $completed = $task.Wait($TimeoutMs)
    if (-not $completed) { return $false }
    return $client.Connected
  } catch {
    return $false
  } finally {
    $client.Dispose()
  }
}

function Get-PythonExe {
  $candidates = @(
    ".\venv_ai\Scripts\python.exe",
    ".\venv\Scripts\python.exe",
    ".\.venv\Scripts\python.exe",
    "python"
  )
  foreach ($candidate in $candidates) {
    try {
      if ($candidate -eq "python") { return $candidate }
      if (Test-Path $candidate) { return $candidate }
    } catch { }
  }
  return "python"
}

function Get-PsqlExe {
  $cmd = Get-Command psql -ErrorAction SilentlyContinue
  if ($cmd -and $cmd.Source) {
    return $cmd.Source
  }

  $candidates = @()
  if (Test-Path "C:\Program Files\PostgreSQL") {
    $versions = Get-ChildItem "C:\Program Files\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
      Sort-Object Name -Descending
    foreach ($v in $versions) {
      $candidates += Join-Path $v.FullName "bin\psql.exe"
    }
  }
  if (Test-Path "C:\Program Files (x86)\PostgreSQL") {
    $versions = Get-ChildItem "C:\Program Files (x86)\PostgreSQL" -Directory -ErrorAction SilentlyContinue |
      Sort-Object Name -Descending
    foreach ($v in $versions) {
      $candidates += Join-Path $v.FullName "bin\psql.exe"
    }
  }

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }
  return $null
}

Write-Host "Checking local PostgreSQL + pgvector service..." -ForegroundColor Cyan
if (-not (Test-TcpPort -Hostname $DbHost -Port $DbPort)) {
  throw "PostgreSQL is not reachable on ${DbHost}:${DbPort}. Start local PostgreSQL first."
}

$databaseUrl = "postgresql+psycopg://${DbUser}:${DbPassword}@${DbHost}:${DbPort}/${DbName}"
Write-Host "PostgreSQL reachable on ${DbHost}:${DbPort}" -ForegroundColor Green
Write-Host "DATABASE_URL=$databaseUrl" -ForegroundColor Gray

if ($EnsurePgvector) {
  $psqlExe = Get-PsqlExe
  if ([string]::IsNullOrWhiteSpace($psqlExe)) {
    Write-Host "psql not found in PATH. Skipping automatic CREATE EXTENSION vector." -ForegroundColor Yellow
    Write-Host "Run manually: CREATE EXTENSION IF NOT EXISTS vector;" -ForegroundColor Yellow
  } else {
    Write-Host "Ensuring pgvector extension..." -ForegroundColor Cyan
    $env:PGPASSWORD = $DbPassword
    & $psqlExe -h $DbHost -p $DbPort -U $DbUser -d $DbName -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS vector;"
    if ($LASTEXITCODE -ne 0) {
      Write-Host "pgvector extension is not available on this PostgreSQL installation yet. Continuing with non-pgvector mode." -ForegroundColor Yellow
    }
  }
}

if ($RunMigrations) {
  $python = Get-PythonExe
  Write-Host "Running backend migration checks..." -ForegroundColor Cyan
  $env:DATABASE_URL = $databaseUrl
  $env:FACE_PGVECTOR_ENABLED = "true"

  & $python -m vms.backend.scripts.migrate_postgres_runtime
  if ($LASTEXITCODE -ne 0) { throw "migrate_postgres_runtime failed" }

  & $python -m vms.backend.scripts.backfill_face_embeddings --batch-size 500
  if ($LASTEXITCODE -ne 0) { throw "backfill_face_embeddings failed" }
}

Write-Host "Local PostgreSQL validation complete." -ForegroundColor Green
