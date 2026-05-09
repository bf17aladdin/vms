# test_rapide_visage.ps1
$base = "http://127.0.0.1:5003"

Write-Host "🎯 Test rapide avec VOTRE photo..." -ForegroundColor Cyan

# Demander le chemin de la photo
$photoPath = Read-Host "📸 Chemin de votre photo (ou laissez vide pour rechercher)"
if ([string]::IsNullOrEmpty($photoPath)) {
    # Chercher des photos dans le dossier Images
    $pictures = Get-ChildItem -Path "$env:USERPROFILE\Pictures" -Include *.jpg,*.jpeg,*.png -File | Select-Object -First 5
    if ($pictures) {
        Write-Host "📁 Photos trouvées :" -ForegroundColor Yellow
        $i = 1
        foreach ($pic in $pictures) {
            Write-Host "   $i. $($pic.Name)" -ForegroundColor White
            $i++
        }
        $choice = Read-Host "Choisissez un numéro (1-$($pictures.Count))"
        $photoPath = $pictures[$choice-1].FullName
    }
}

if (-not (Test-Path $photoPath)) {
    Write-Host "❌ Photo non trouvée. Création d'un test..." -ForegroundColor Red
    # Créer une image de test simple
    $photoPath = "test_visage.jpg"
    Add-Type -AssemblyName System.Drawing
    $bmp = New-Object Drawing.Bitmap(200,200)
    $g = [Drawing.Graphics]::FromImage($bmp)
    $g.Clear([Drawing.Color]::LightGray)
    # Dessiner un visage simple
    $g.FillEllipse([Drawing.Brushes]::Skin, 50, 50, 100, 100) # Visage
    $g.FillEllipse([Drawing.Brushes]::Blue, 75, 80, 20, 20)   # Yeux
    $g.FillEllipse([Drawing.Brushes]::Blue, 105, 80, 20, 20)
    $g.DrawArc([Drawing.Pens]::Red, 70, 100, 60, 30, 0, 180) # Bouche
    $g.Dispose()
    $bmp.Save($photoPath, [Drawing.Imaging.ImageFormat]::Jpeg)
    $bmp.Dispose()
}

Write-Host "📸 Utilisation de: $photoPath" -ForegroundColor Green

# Continuer avec le flux IA normal...
# [Ajoutez ici les étapes login, création personnel, upload, etc.]powershell -ExecutionPolicy Bypass -File webcam_face_test.ps1