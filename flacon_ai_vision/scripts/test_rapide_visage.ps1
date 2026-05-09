param(
    [string]$photoPath = ''
)

# test_rapide_visage.ps1
$base = "http://127.0.0.1:5003"

Write-Host "Test rapide avec VOTRE photo..." -ForegroundColor Cyan

# Si aucun chemin fourni, tenter de trouver automatiquement une photo dans Pictures
if ([string]::IsNullOrEmpty($photoPath)) {
    $pictures = Get-ChildItem -Path "$env:USERPROFILE\Pictures" -Include *.jpg,*.jpeg,*.png -File -ErrorAction SilentlyContinue | Select-Object -First 5
    if ($pictures -and $pictures.Count -gt 0) {
        Write-Host "Photos trouvées, utilisation automatique de la première:" -ForegroundColor Yellow
        $photoPath = $pictures[0].FullName
        Write-Host "   $photoPath" -ForegroundColor Green
    }
}

if ([string]::IsNullOrEmpty($photoPath) -or -not (Test-Path $photoPath)) {
    Write-Host "❌ Photo non trouvée. Création d'un test..." -ForegroundColor Red
    # Créer une image de test simple
    $photoPath = Join-Path -Path (Get-Location) -ChildPath "test_visage.jpg"
    Add-Type -AssemblyName System.Drawing
    $bmp = New-Object Drawing.Bitmap(200,200)
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.Clear([Drawing.Color]::LightGray)
    # Dessiner un visage simple
    $skinBrush = New-Object Drawing.SolidBrush([Drawing.Color]::FromArgb(240,200,170))
    $g.FillEllipse($skinBrush, 50, 50, 100, 100) # Visage
    $g.FillEllipse([Drawing.Brushes]::Blue, 75, 80, 20, 20)   # Yeux
    $g.FillEllipse([Drawing.Brushes]::Blue, 105, 80, 20, 20)
    $g.DrawArc([Drawing.Pens]::Red, 70, 100, 60, 30, 0, 180) # Bouche
    $g.Dispose()
    $bmp.Save($photoPath, [Drawing.Imaging.ImageFormat]::Jpeg)
    $bmp.Dispose()
    Write-Host ("Image test créée: " + $photoPath) -ForegroundColor Green
}

Write-Host ("Utilisation de: " + $photoPath) -ForegroundColor Green

# Ensuite : effectuer login -> create personnel -> upload -> load-face
try {
    $baseUri = $base.TrimEnd('/')
    Write-Host "Connexion au backend..." -ForegroundColor Yellow
    $login = Invoke-RestMethod -Uri ($baseUri + '/api/auth/login') -Method Post -Body (ConvertTo-Json @{ username = 'admin'; password = 'admin123' }) -ContentType 'application/json' -ErrorAction Stop
    $token = $login.access_token
    Write-Host "Token reçu." -ForegroundColor Green

    $headers = @{ Authorization = "Bearer $token" }

    Write-Host "Création d'un personnel de test..." -ForegroundColor Yellow
    $body = @{ full_name = 'Test PS User'; recruitment_id = "ps_$(Get-Date -UFormat %s)"; category = 'employee' } | ConvertTo-Json
    $personResp = Invoke-RestMethod -Uri "$baseUri/api/personnel/" -Method Post -Body $body -ContentType 'application/json' -Headers $headers -ErrorAction Stop
    Write-Host "Personnel créé id=$($personResp.id)" -ForegroundColor Green

    Write-Host "Téléversement de la photo..." -ForegroundColor Yellow
    $form = @{ file = Get-Item $photoPath }
    # Use Invoke-RestMethod for simple uploads if supported, otherwise fallback
    try {
        $upload = Invoke-RestMethod -Uri ($baseUri + '/api/upload/person-photo') -Method Post -Form $form -Headers $headers -ErrorAction Stop
    } catch {
        # Fallback using curl.exe to post multipart/form-data
        Write-Host "Invoke-RestMethod -Form non supporte, fallback vers curl.exe" -ForegroundColor Yellow
        $exe = 'curl.exe'
        $args = @(
            '-s',
            '-X', 'POST',
            ($baseUri + '/api/upload/person-photo'),
            '-H', ("Authorization: Bearer $token"),
            '-F', ("file=@$photoPath")
        )
        $out = & $exe @args
        if ($LASTEXITCODE -ne 0) { throw "curl upload failed" }
        $upload = $out | ConvertFrom-Json
    }

    Write-Host ("Upload OK : " + $upload.path) -ForegroundColor Green

    Write-Host "Appel load-face..." -ForegroundColor Yellow
    $uri = $baseUri + '/api/personnel/' + $personResp.id + '/load-face?image_path=' + [System.Uri]::EscapeDataString($upload.path)
    $lf = Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -ErrorAction Stop
    Write-Host ("Résultat load-face : " + ($lf | ConvertTo-Json)) -ForegroundColor Green
} catch {
    Write-Host ("Erreur pendant le test: " + $_) -ForegroundColor Red
}
