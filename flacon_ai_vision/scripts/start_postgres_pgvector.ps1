param(
  [string]$ContainerName = "falcon-ai-vision-pgvector",
  [int]$HostPort = 5433,
  [string]$DbUser = "falcon",
  [string]$DbPassword = "eye_of_falcon_pwd",
  [string]$DbName = "eye_of_falcon",
  [switch]$RunMigrations
)

$ErrorActionPreference = "Stop"

Write-Host "Starting PostgreSQL + pgvector container..." -ForegroundColor Cyan

$existing = docker ps -a --filter "name=^/$ContainerName$" --format "{{.ID}}"
if ($existing) {
  $running = docker ps --filter "name=^/$ContainerName$" --format "{{.ID}}"
  if (-not $running) {
    docker start $ContainerName | Out-Null
  }
} else {
  docker run -d `
    --name $ContainerName `
    -e "POSTGRES_USER=$DbUser" `
    -e "POSTGRES_PASSWORD=$DbPassword" `
    -e "POSTGRES_DB=$DbName" `
    -p "${HostPort}:5432" `
    pgvector/pgvector:pg16 | Out-Null
}

Write-Host "Waiting for PostgreSQL readiness..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  $check = docker exec $ContainerName pg_isready -U $DbUser -d $DbName 2>$null
  if ($LASTEXITCODE -eq 0) {
    $ready = $true
    break
  }
}

if (-not $ready) {
  throw "PostgreSQL container did not become ready in time."
}

$databaseUrl = "postgresql+psycopg://${DbUser}:${DbPassword}@127.0.0.1:${HostPort}/${DbName}"
Write-Host "PostgreSQL ready on 127.0.0.1:$HostPort" -ForegroundColor Green
Write-Host "DATABASE_URL=$databaseUrl" -ForegroundColor Gray

if ($RunMigrations) {
  Write-Host "Running backend DB migration checks..." -ForegroundColor Cyan
  $env:DATABASE_URL = $databaseUrl
  $env:FACE_PGVECTOR_ENABLED = "true"

  & .\venv_ai\Scripts\python.exe -m vms.backend.scripts.migrate_postgres_runtime
  if ($LASTEXITCODE -ne 0) { throw "migrate_postgres_runtime failed" }

  & .\venv_ai\Scripts\python.exe -m vms.backend.scripts.backfill_face_embeddings --batch-size 500
  if ($LASTEXITCODE -ne 0) { throw "backfill_face_embeddings failed" }
}

Write-Host "Done." -ForegroundColor Green
