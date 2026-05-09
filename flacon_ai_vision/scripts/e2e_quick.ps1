$ErrorActionPreference = 'Stop'
$base = 'http://127.0.0.1:5003'

Write-Output 'LOGIN...'
$login = Invoke-RestMethod -Uri "$base/api/auth/login" -Method Post -Body (ConvertTo-Json @{username='admin'; password='admin123'}) -ContentType 'application/json'
$token = $login.access_token
Write-Output "TOKEN: $($token.Substring(0,20))..."

Write-Output 'CREATE PERSONNEL...'
$rid = "TMP_$(Get-Date -UFormat %s)"
$body = @{ full_name='CI Quick Test'; recruitment_id=$rid; category='employee' } | ConvertTo-Json
$resp = Invoke-WebRequest -Uri "$base/api/personnel/" -Method Post -Body $body -ContentType 'application/json' -Headers @{ Authorization = "Bearer $token" } -ErrorAction SilentlyContinue
if ($resp.StatusCode.Value__ -ge 400) { Write-Output "CREATE FAILED: $($resp.StatusCode.Value__)"; Write-Output $resp.Content; exit 1 }
$person = $resp.Content | ConvertFrom-Json
Write-Output "CREATED PERSON ID: $($person.id)"

Write-Output 'WRITE TEMP IMAGE...'
[System.IO.File]::WriteAllBytes('tmp_person.png',[System.Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII='))

Write-Output 'UPLOAD IMAGE via HttpClient...'
Add-Type -AssemblyName System.Net.Http
$bytes = [System.IO.File]::ReadAllBytes('tmp_person.png')
$content = New-Object System.Net.Http.ByteArrayContent (,$bytes)
$content.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse('image/png')
$multipart = New-Object System.Net.Http.MultipartFormDataContent
[void]$multipart.Add($content,'file','tmp_person.png')
$client = New-Object System.Net.Http.HttpClient
$client.DefaultRequestHeaders.Authorization = New-Object System.Net.Http.Headers.AuthenticationHeaderValue('Bearer',$token)
$response = $client.PostAsync("$base/api/upload/person-photo", $multipart).Result
$respStr = $response.Content.ReadAsStringAsync().Result
if ($response.StatusCode.Value__ -ge 400) { Write-Output "UPLOAD FAILED: $($response.StatusCode.Value__)"; Write-Output $respStr; exit 1 }
$up = $respStr | ConvertFrom-Json
Write-Output "UPLOAD PATH: $($up.path)"

Write-Output 'CALL load-face (query param)...'
$uri = "$base/api/personnel/$($person.id)/load-face?image_path=$( [System.Uri]::EscapeDataString($up.path) )"
$lf = Invoke-RestMethod -Uri $uri -Method Post -Headers @{ Authorization = "Bearer $token" }
Write-Output 'LOAD-FACE RESPONSE:'
$lf | ConvertTo-Json -Depth 5
