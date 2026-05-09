# Test E2E Capture Visage avec token frais
# Scripts\test_capture_e2e.ps1

$base = "http://127.0.0.1:5003"
$testImg = "test_visage.jpg"  # Image de test déjà créée

Write-Host "=== Test E2E Capture ===" -ForegroundColor Cyan

# 1. Login
Write-Host "1. Login..." -ForegroundColor Yellow
$login = Invoke-RestMethod -Uri "$base/api/auth/login" -Method Post `
  -Body (ConvertTo-Json @{ username='admin'; password='admin123' }) `
  -ContentType 'application/json' -ErrorAction Stop
$token = $login.access_token
Write-Host "   Token: $($token.Substring(0,20))..." -ForegroundColor Green

# 2. Test recognize-image (sans personnel)
Write-Host "2. Test recognize-image (brut)..." -ForegroundColor Yellow
try {
  $form = @{ file = Get-Item $testImg }
  $rec = Invoke-RestMethod -Uri "$base/api/facial/recognize-image?confidence=0.6" -Method Post `
    -Form $form `
    -Headers @{ Authorization = "Bearer $token" } `
    -ErrorAction Stop
  Write-Host "   Reponse: $($rec | ConvertTo-Json)" -ForegroundColor Green
  Write-Host "   Detections: $($rec.detections_count)" -ForegroundColor Green
} catch {
  Write-Host "   ERREUR: $_" -ForegroundColor Red
  if($_.Exception.Response){
    $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
    $error = $reader.ReadToEnd()
    Write-Host "   Détail: $error" -ForegroundColor Red
  }
}

# 3. Create personnel + upload + load-face
Write-Host "3. Create personnel..." -ForegroundColor Yellow
$person = Invoke-RestMethod -Uri "$base/api/personnel/" -Method Post `
  -Headers @{ Authorization = "Bearer $token" } `
  -Body (ConvertTo-Json @{ 
    full_name = "Test PowerShell"
    recruitment_id = "ps_$(Get-Date -UFormat %s)"
    category = "employee" 
  }) `
  -ContentType 'application/json' `
  -ErrorAction Stop
Write-Host "   Personnel ID: $($person.id)" -ForegroundColor Green

Write-Host "4. Upload photo..." -ForegroundColor Yellow
$upload = Invoke-RestMethod -Uri "$base/api/upload/person-photo" -Method Post `
  -Form $form `
  -Headers @{ Authorization = "Bearer $token" } `
  -ErrorAction Stop
Write-Host "   Path: $($upload.path)" -ForegroundColor Green

Write-Host "5. Load-face..." -ForegroundColor Yellow
try {
  $imgPath = [System.Uri]::EscapeDataString($upload.path)
  $lf = Invoke-RestMethod -Uri "$base/api/personnel/$($person.id)/load-face?image_path=$imgPath" -Method Post `
    -Headers @{ Authorization = "Bearer $token" } `
    -ErrorAction Stop
  Write-Host "   Resultat: $($lf | ConvertTo-Json)" -ForegroundColor Green
} catch {
  Write-Host "   ERREUR load-face: $_" -ForegroundColor Red
}

Write-Host "=== Test E2E Terminé ===" -ForegroundColor Cyan
