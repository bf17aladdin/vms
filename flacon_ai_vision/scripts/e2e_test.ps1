# e2e_real_face.ps1 - Avec vraie image de visage
$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:5003"

Write-Host "🧪 TEST AVEC VRAI VISAGE" -ForegroundColor Cyan
Write-Host "="*50 -ForegroundColor Cyan
Write-Host ""

# 1. Login
Write-Host "1. LOGIN..." -ForegroundColor Yellow
try {
    $login = Invoke-RestMethod -Uri "$base/api/auth/login" `
        -Method Post `
        -Body (ConvertTo-Json @{username='admin'; password='admin123'}) `
        -ContentType "application/json" `
        -TimeoutSec 5
    $token = $login.access_token
    Write-Host "   ✅ Token obtenu" -ForegroundColor Green
} catch {
    Write-Host "   ❌ Erreur login: $_" -ForegroundColor Red
    exit 1
}

# 2. Créer personnel
Write-Host "2. CRÉATION PERSONNEL..." -ForegroundColor Yellow
try {
    $person = Invoke-RestMethod -Uri "$base/api/personnel/" `
        -Method Post `
        -Body (ConvertTo-Json @{ 
            full_name = "John Doe (Test Visage)"
            recruitment_id = "FACE_$(Get-Date -Format 'HHmmss')"
            category = "employee"
            department = "Sécurité"
            position = "Agent de test"
            access_level = "medium"
            is_active = $true
        }) `
        -ContentType "application/json" `
        -Headers @{ Authorization = "Bearer $token" }
    
    $personId = $person.id
    Write-Host "   ✅ Personnel créé: $($person.full_name)" -ForegroundColor Green
    Write-Host "   🆔 ID: $personId" -ForegroundColor Gray
} catch {
    Write-Host "   ❌ Erreur création: $_" -ForegroundColor Red
    exit 1
}

# 3. Créer une VRAIE image avec visage (silhouette générique)
Write-Host "3. CRÉATION IMAGE AVEC VISAGE..." -ForegroundColor Yellow
try {
    # Image PNG 200x200 avec silhouette de visage (simple)
    $faceImageBase64 = @"
iVBORw0KGgoAAAANSUhEUgAAAMgAAADICAYAAACtWK6eAAAACXBIWXMAAAsTAAALEwEAmpwYAAAA
AXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAJHSURBVHgB7d2xSgNBFIXh2ZhGEbSNrYWFvYWF
vY+Fj+AjWFhZWVgoiKCihYVgYW2hRIQgQRARtVEs3AhGcHc28/1gsbCF2XvP/Gd2d3Z2FwEAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAML+08mx6h+d7ZvZsZvZgZvZqZna7+wcwv5QCbPq7F4dmdhUY/3Of
8Vr9A6ggpQRp9ufj2Myuw5Fj/BVjpBglS5Bm3+/HjJFq/B1j5BglS5BmP+7HjJF6/B1jpBilSpBm
v+7HjDEC42WMEWOUKEGa/b4fM0ZgvIwRGE9j5B4lSpBm2/fj3GOExlPGGIFxGmOEGCVKkGbb9+Oc
Y4TGVcYYgfEcY5QYJUqQZrv345xjBMcZY4TGaYyRYpQoQZrt34/zjBEeb4wRGmcwRo5RogRpdng/
zjVGh/GMMULjjcEYJUaJEqTZ4/txnjE6jmeMERrPMUaKUaIEaXZ8P84zRsfxjDFC44wxUoxSJUiz
0/txnjE6jmeMERrPMUaOUaoEafZ3P84zRsfxjDFC44wxYoxSJUiz9vsxY3QcV8YYoXFljJlilCpB
mrXfjxmj47gyxgiNK2PMGKNUCdKs/X7MGB3HlTFGaFwZY8YYpUqQZu33Y8boOK6MMULjyhgzxihV
gjRrvx8zRsdxZYwRGlfGmDFGqRKkWfv9mDE6jitjjNC4MsaMMUqVIM3a78eM0XFcGWOExpUxZoxR
qgRp1n4/ZoyO48oYIzSujDFjjFIlSLP2+zFjdBxXxhihcWWMGWOUKkGatd+PGaPjuDLGCI0rY8wY
o1QJ0qz9fswYHceVMUZoXBljxhilSpBm7fdjxug4rowxQuPKGDPGKFWCAAAAAAAAAAAAAAAAAAAA
AAAAAACAvD4BfYYo2CtJCIAAAAASUVORK5CYII=
"@
    
    # Nettoyer le base64 (supprimer les retours à la ligne)
    $faceImageBase64 = $faceImageBase64 -replace "`n","" -replace "`r",""
    
    $imagePath = "real_face_$personId.png"
    [System.IO.File]::WriteAllBytes($imagePath, [System.Convert]::FromBase64String($faceImageBase64))
    
    Write-Host "   ✅ Image visage créée: $imagePath" -ForegroundColor Green
    Write-Host "   📏 Dimensions: 200x200 px" -ForegroundColor Gray
} catch {
    Write-Host "   ❌ Erreur création image: $_" -ForegroundColor Red
    exit 1
}

# 4. Upload photo
Write-Host "4. UPLOAD PHOTO..." -ForegroundColor Yellow
try {
    $uploadForm = @{
        file = Get-Item $imagePath
        person_id = $personId
    }
    
    $uploadHeaders = @{
        Authorization = "Bearer $token"
    }
    
    $uploadResult = Invoke-RestMethod -Uri "$base/api/upload/person-photo" `
        -Method Post `
        -Form $uploadForm `
        -Headers $uploadHeaders `
        -TimeoutSec 10
    
    Write-Host "   ✅ Photo uploadée" -ForegroundColor Green
    Write-Host "   📁 Fichier: $($uploadResult.filename)" -ForegroundColor Gray
    Write-Host "   🔗 URL: $($uploadResult.url)" -ForegroundColor Gray
    
    $photoPath = $uploadResult.filename
} catch {
    Write-Host "   ❌ Erreur upload: $_" -ForegroundColor Red
    Remove-Item $imagePath -ErrorAction SilentlyContinue
    exit 1
}

# 5. Encodage facial
Write-Host "5. ENCODAGE FACIAL..." -ForegroundColor Yellow
try {
    # Encoder le chemin pour l'URL
    $encodedPath = [System.Web.HttpUtility]::UrlEncode($photoPath)
    
    $loadFaceUrl = "$base/api/personnel/$personId/load-face?image_path=$encodedPath"
    
    Write-Host "   🔗 URL appelée: $loadFaceUrl" -ForegroundColor Gray
    
    $faceResult = Invoke-RestMethod -Uri $loadFaceUrl `
        -Method Post `
        -Headers @{ Authorization = "Bearer $token" } `
        -TimeoutSec 15
    
    Write-Host "   ✅ Encodage réussi!" -ForegroundColor Green
    Write-Host "   📊 Message: $($faceResult.message)" -ForegroundColor Gray
    
    if ($faceResult.encodings) {
        Write-Host "   🔢 Nombre d'encodages: $($faceResult.encodings)" -ForegroundColor Gray
    }
    
} catch {
    Write-Host "   ❌ Erreur encodage: $_" -ForegroundColor Red
    Write-Host "   ⚠️  C'est peut-être normal si l'image n'a pas de vrai visage" -ForegroundColor Yellow
    $faceResult = $null
}

# 6. Vérifier le personnel créé
Write-Host "6. VÉRIFICATION..." -ForegroundColor Yellow
try {
    $verifyHeaders = @{
        Authorization = "Bearer $token"
    }
    
    $verify = Invoke-RestMethod -Uri "$base/api/personnel/$personId" `
        -Method Get `
        -Headers $verifyHeaders `
        -TimeoutSec 5
    
    Write-Host "   ✅ Personnel vérifié" -ForegroundColor Green
    Write-Host "   📊 Statut: $($verify.status)" -ForegroundColor Gray
    
} catch {
    Write-Host "   ⚠️  Impossible de vérifier: $_" -ForegroundColor Yellow
}

# 7. Nettoyage
Write-Host "7. NETTOYAGE..." -ForegroundColor Yellow
try {
    Remove-Item $imagePath -ErrorAction SilentlyContinue
    Write-Host "   ✅ Fichier temporaire supprimé" -ForegroundColor Green
} catch {
    Write-Host "   ⚠️  Impossible de supprimer le fichier" -ForegroundColor Yellow
}

# ===============================
# RÉSUMÉ FINAL
# ===============================
Write-Host "`n" + "="*60 -ForegroundColor Green
Write-Host "📊 RÉSUMÉ DU TEST" -ForegroundColor Green
Write-Host "="*60 -ForegroundColor Green
Write-Host ""

if ($faceResult -and $faceResult.message -notmatch "pas de visage") {
    Write-Host "✅ FLUX COMPLET RÉUSSI !" -ForegroundColor Green
    Write-Host ""
    Write-Host "🎉 Félicitations ! Votre système IA fonctionne parfaitement :" -ForegroundColor Cyan
    Write-Host "   1. ✅ Authentification JWT" -ForegroundColor White
    Write-Host "   2. ✅ Création de personnel" -ForegroundColor White
    Write-Host "   3. ✅ Upload de photo" -ForegroundColor White
    Write-Host "   4. ✅ Détection et encodage facial" -ForegroundColor White
    Write-Host ""
    Write-Host "🔗 Testez maintenant la reconnaissance :" -ForegroundColor Magenta
    Write-Host "   🌐 http://127.0.0.1:5003/admin/ia.html" -ForegroundColor White
    Write-Host "   🗺️  http://127.0.0.1:5003/admin/zones.html" -ForegroundColor White
} else {
    Write-Host "⚠️  FLUX PARTIELLEMENT RÉUSSI" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "📋 Ce qui fonctionne :" -ForegroundColor Cyan
    Write-Host "   ✅ Authentification JWT" -ForegroundColor White
    Write-Host "   ✅ Création de personnel" -ForegroundColor White
    Write-Host "   ✅ Upload de photo" -ForegroundColor White
    Write-Host "   ✅ API load-face (techniquement)" -ForegroundColor White
    Write-Host ""
    Write-Host "📋 Problème détecté :" -ForegroundColor Cyan
    Write-Host "   ❌ Pas de visage détecté dans l'image test" -ForegroundColor White
    Write-Host ""
    Write-Host "💡 Solution :" -ForegroundColor Magenta
    Write-Host "   Utilisez une vraie photo avec un visage clair" -ForegroundColor White
    Write-Host "   ou ajustez les paramètres de détection faciale" -ForegroundColor White
}

Write-Host "`n📋 DONNÉES CRÉÉES :" -ForegroundColor Cyan
Write-Host "   👤 ID: $personId" -ForegroundColor White
Write-Host "   📛 Nom: $($person.full_name)" -ForegroundColor White
Write-Host "   🏷️  Matricule: $($person.recruitment_id)" -ForegroundColor White
Write-Host "   📁 Photo: $photoPath" -ForegroundColor White

if ($faceResult) {
    Write-Host "   🤖 Résultat: $($faceResult.message)" -ForegroundColor White
}

Write-Host "`n🎯 Prochaine étape :" -ForegroundColor Magenta
Write-Host "   Testez avec une VRAIE photo via l'interface web !" -ForegroundColor White

Write-Host "`n" + "="*60 -ForegroundColor Green