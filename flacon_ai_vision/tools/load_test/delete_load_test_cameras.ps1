param(
  [string]$NamePrefix = "LoadTest",
  [string]$ApiBase = "http://127.0.0.1:5010",
  [string]$Token = "",
  [string]$Username = "",
  [string]$Password = "",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $Token) {
  if (-not $Username -or -not $Password) {
    Write-Error "Provide -Token or -Username/-Password to login."
    exit 1
  }

  $loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
  $login = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/auth/login" -ContentType "application/json" -Body $loginBody
  $Token = $login.access_token
}

$headers = @{ Authorization = "Bearer $Token" }

$response = Invoke-RestMethod -Method Get -Uri "$ApiBase/api/cameras?skip=0&limit=500" -Headers $headers
$cameras = @()
if ($response.cameras) { $cameras = $response.cameras }

$targets = $cameras | Where-Object { $_.name -like "$NamePrefix*" }
if (-not $targets -or $targets.Count -eq 0) {
  Write-Output "No cameras found with prefix '$NamePrefix'."
  exit 0
}

Write-Output "Found $($targets.Count) camera(s) matching '$NamePrefix*'"

foreach ($cam in $targets) {
  $id = $cam.id
  if (-not $id) { continue }
  if ($DryRun) {
    Write-Output "[DryRun] Would delete camera $id - $($cam.name)"
    continue
  }
  try {
    Invoke-RestMethod -Method Delete -Uri "$ApiBase/api/cameras/$id" -Headers $headers
    Write-Output "Deleted camera $id - $($cam.name)"
  } catch {
    Write-Warning "Failed to delete camera $id - $($cam.name): $($_.Exception.Message)"
  }
}

Write-Output "Cleanup done."
