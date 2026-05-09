param(
  [int]$Count = 10,
  [int]$StartIndex = 1,
  [string]$ApiBase = "http://127.0.0.1:5010",
  [string]$RtspBase = "rtsp://127.0.0.1:8554",
  [string]$NamePrefix = "LoadTest",
  [string]$Token = "",
  [string]$Username = "",
  [string]$Password = "",
  [switch]$EnableAi,
  [switch]$ContinueOnError
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
$created = 0

for ($i = $StartIndex; $i -lt ($StartIndex + $Count); $i++) {
  $payload = @{
    name = "$NamePrefix-$i"
    rtsp_url = "$RtspBase/cam$i"
    ai_enabled = [bool]$EnableAi
    is_active = $true
  }

  try {
    Invoke-RestMethod -Method Post -Uri "$ApiBase/api/cameras" -Headers $headers -ContentType "application/json" -Body ($payload | ConvertTo-Json)
    Write-Output "Created camera $($payload.name) -> $($payload.rtsp_url)"
    $created++
  } catch {
    Write-Warning "Failed to create $($payload.name): $($_.Exception.Message)"
    if (-not $ContinueOnError) { break }
  }
}

Write-Output "Created $created camera(s)."
