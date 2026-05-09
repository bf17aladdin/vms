# 🚀 GUIDE DE DÉMARRAGE - STANDARDS MILITAIRES

## 1️⃣ VÉRIFIER QUE LE BACKEND EST LANCÉ

```bash
# Terminal 1 - Backend
cd c:\Users\boufm\Desktop\eye_of_falcon\eye-of-falcon\vms
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Vous devez voir: `✓ Uvicorn running on http://0.0.0.0:8000`

## 2️⃣ VÉRIFIER QUE LE FRONTEND EST LANCÉ

```bash
# Terminal 2 - Frontend
cd c:\Users\boufm\Desktop\eye_of_falcon\eye-of-falcon\vms\frontend
npm run dev
```

Vous devez voir: `Local: http://localhost:5173/`

## 3️⃣ ACCÉDER À L'APPLICATION

1. Ouvrez votre navigateur: **http://localhost:5173**
2. Login: `admin` / `admin123`
3. Vous êtes maintenant authentifié

## 4️⃣ UTILISER LES NOUVELLES PAGES

### 📋 Personnel Militaire

**Accès**: Menu latéral → **Personnel Militaire** (👥)

**Colonnes affichées**:
- ✅ Nom
- ✅ Prénom
- ✅ CIN (Identifiant Unique)
- ✅ N° Recrutement
- ✅ Grade (ex: Capitaine, Lieutenant)
- ✅ Catégorie (Officier, Sous-Officier, Soldat, etc.)
- ✅ Unité (ex: 1er Régiment)
- ✅ État (Actif, Inactif, Signalé)

**Fonctionnalités**:
1. **Recherche**: Tapez dans le champ de recherche (cherche dans nom, prénom, CIN, n° recrutement)
2. **Filtres avancés**:
   - Grade: Texte (ex "Capitaine")
   - Catégorie: Dropdown
   - Unité: Texte (ex "1er Régiment")
   - Checkboxes: Montrer inactifs, Montrer signalés
3. **Créer**: Cliquez **"➕ Ajouter Personnel"**
   - Remplissez: nom, prenom, cin, num_recrutement, grade, categorie, unité
   - Validations: CIN min 5 caractères
4. **Éditer**: Cliquez **Éditer** sur une ligne
5. **Supprimer**: Cliquez **Supprimer** (soft delete)
6. **Signaler**: Cliquez **Signaler** et entrez une raison
7. **Stats**: Cards en haut montrent: Total, Actifs, Signalés, Répartition par catégorie

### 🚗 Registre Véhicules

**Accès**: Menu latéral → **Registre Véhicules** (📋)

**Colonnes affichées**:
- ✅ Immatriculation (ex: MA123456)
- ✅ Marque / Modèle
- ✅ Type (Militaire, Civil, Inconnu)
- ✅ Propriétaire
- ✅ État (Actif, Maintenance, Hors Service)
- ✅ Entrées Aujourd'hui (nombre)
- ✅ Statut (✓ Normal ou 🚩 Signalé)

**Fonctionnalités**:
1. **Recherche**: Cherche dans immatriculation, marque, propriétaire, n° série
2. **Filtres avancés**:
   - Type: Dropdown (militaire/civile/inconnu)
   - État: Dropdown (actif/maintenance/hors_service)
   - Checkbox: Seulement signalés
3. **Créer**: Cliquez **"➕ Ajouter Véhicule"**
   - Champs obligatoires: immatriculation, marque_modele, type_vehicule, proprietaire, etat
   - Champs optionnels: numero_serie, couleur, nom_conducteur
   - Format: Immatriculation en majuscules (auto-converti)
4. **Éditer**: Cliquez **Éditer**
5. **Supprimer**: Cliquez **Supprimer** (suppression définitive)
6. **Signaler**: Cliquez **Signaler** (devient 🚩) avec raison
7. **Retirer Signalement**: Si déjà signalé, cliquez **Retirer Signalement**
8. **Stats**: Cards montrent: Total, Type breakdown (Militaire/Civil), État breakdown, Nombre signalés

---

## 5️⃣ TESTER AVEC L'API DIRECTEMENT

### Créer un personnel
```bash
curl -X POST http://localhost:8000/api/personnel \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "nom": "Dupont",
    "prenom": "Jean",
    "cin": "ST12345678901",
    "num_recrutement": "REC2024001",
    "grade": "Capitaine",
    "categorie": "officier",
    "unité": "1er Régiment"
  }'
```

### Lister personnel avec filtres
```bash
curl "http://localhost:8000/api/personnel?categorie=officier&is_active=true" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Créer un véhicule
```bash
curl -X POST http://localhost:8000/api/vehicle-registry/create \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "immatriculation": "MA123456",
    "marque_modele": "Toyota Land Cruiser",
    "type_vehicule": "militaire",
    "proprietaire": "Ministère Défense",
    "etat": "actif"
  }'
```

### Signaler un véhicule
```bash
curl -X POST http://localhost:8000/api/vehicle-registry/1/flag \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason": "Véhicule non autorisé"}'
```

---

## 6️⃣ EXÉCUTER LES TESTS E2E

```bash
# À la racine du projet
python test_military_standards.py
```

**Résultat attendu**:
```
============================================================
TEST COMPLET - STANDARDS MILITAIRES
============================================================

✓ PASS Login réussi
✓ PASS Création personnel
✓ PASS Récupération personnel
✓ PASS Filtre par catégorie (Officier)
✓ PASS Filtre par grade (Capitaine)
...
✓ PASS Stats véhicules

============================================================
TEST COMPLET TERMINÉ
============================================================
```

---

## 7️⃣ DONNÉES DE TEST

### Personnel Test
```
Nom: Dupont
Prénom: Jean
CIN: ST12345678901
N° Recrutement: REC2024001
Grade: Capitaine
Catégorie: Officier
Unité: 1er Régiment
```

### Véhicule Test
```
Immatriculation: MA123456
Marque: Toyota Land Cruiser
Type: Militaire
Propriétaire: Ministère Défense
État: Actif
```

---

## 8️⃣ DÉPANNAGE

### ❌ "Erreur 401: Unauthorized"
- Vérifiez que vous êtes loggé
- Vérifiez que le token est valide
- Reconnectez-vous

### ❌ "Erreur 422: Validation failed"
- CIN minimum 5 caractères
- Immatriculation doit être unique
- N° recrutement doit être unique
- Consultez le message d'erreur exact

### ❌ "Erreur 404: Not found"
- Les IDs personnne/véhicule n'existent pas
- Vérifiez l'ID exact

### ❌ "Erreur 500: Internal server error"
- Vérifiez que le backend est en cours d'exécution
- Consultez les logs du terminal backend
- Vérifiez la base de données MySQL

### ❌ Frontend n'affiche pas les données
- Ouvrez la Console (F12) et cherchez les erreurs
- Vérifiez que le backend répond (http://localhost:8000/api/personnel)
- Vérifiez que vous êtes authentifié

---

## 9️⃣ ENDPOINTS DISPONIBLES

### Personnel
```
GET    /api/personnel                         → Lister
POST   /api/personnel                         → Créer
GET    /api/personnel/{id}                    → Détails
PUT    /api/personnel/{id}                    → Modifier
DELETE /api/personnel/{id}                    → Supprimer
POST   /api/personnel/{id}/blacklist          → Signaler
POST   /api/personnel/{id}/unblacklist        → Retirer signalement
GET    /api/personnel/stats/summary           → Statistiques
```

### Véhicules
```
GET    /api/vehicle-registry/list             → Lister
GET    /api/vehicle-registry/search           → Rechercher
POST   /api/vehicle-registry/create           → Créer
GET    /api/vehicle-registry/{id}             → Détails
PUT    /api/vehicle-registry/{id}             → Modifier
DELETE /api/vehicle-registry/{id}             → Supprimer
POST   /api/vehicle-registry/{id}/flag        → Signaler
POST   /api/vehicle-registry/{id}/unflag      → Retirer signalement
GET    /api/vehicle-registry/stats/summary    → Statistiques
```

---

## 🔟 PROCHAINES ÉTAPES

- [ ] Intégrer WebSocket notifications pour entrées/sorties temps réel
- [ ] Ajouter rapports PDF
- [ ] Implémenter historique détaillé
- [ ] Ajouter photos/documents
- [ ] Synchroniser avec système empreintes biométriques
- [ ] Exportation Excel
- [ ] Dashboard militaire personnalisé

---

## 📚 FICHIERS MODIFIÉS/CRÉÉS

### Backend
- ✅ `vms/backend/models.py` - Enums + modèles enrichis
- ✅ `vms/backend/schemas.py` - Schémas Pydantic
- ✅ `vms/backend/routers/personnel.py` - API Personnel (280+ lignes)
- ✅ `vms/backend/routers/vehicle_registry.py` - API Véhicules (185 lignes)

### Frontend
- ✅ `vms/frontend/src/pages/PersonnelPage.tsx` - Page Personnel enrichie
- ✅ `vms/frontend/src/pages/VehicleRegistryPage.tsx` - Nouvelle page Véhicules
- ✅ `vms/frontend/src/App.tsx` - Routes mises à jour
- ✅ `vms/frontend/src/layouts/MainLayout.tsx` - Menu mis à jour

### Documentation & Tests
- ✅ `MILITARY_STANDARDS_IMPLEMENTATION.md` - Documentation complète
- ✅ `MILITARY_STANDARDS_QUICK_START.md` - Ce fichier
- ✅ `test_military_standards.py` - Tests E2E

---

## 💡 CONSEILS

1. **Toujours utiliser la recherche avant les filtres** pour localiser rapidement
2. **Vérifier les stats** pour voir la santé globale du système
3. **Signaler immédiatement** tout personnel/véhicule suspect
4. **Faire des backups** régulièrement de la base de données
5. **Monitorer les logs** pour détecter les anomalies

---

**Prêt à gérer votre effectif militaire? C'est parti! 🎖️**
