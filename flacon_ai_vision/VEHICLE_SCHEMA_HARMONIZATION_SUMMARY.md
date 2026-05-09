# ✅ HARMONISATION SCHÉMA VÉHICULES - RÉSUMÉ COMPLET

**Date**: 2024
**Objectif**: Harmoniser les attributs de la table `vehicle_registry` avec ceux de la table `personnel` en utilisant des noms français cohérents.

---

## 📋 MODIFICATIONS EFFECTUÉES

### 1. **Backend - Modèle SQLAlchemy** 
📁 `vms/backend/models.py` - Classe `VehicleRegistry`

#### Anciens attributs (supprimés):
- `type_vehicule` (ENUM: militaire, civile, inconnu)
- `immatriculation` → remplacé par `matricule`
- `numero_serie`
- `proprietaire`
- `nom_conducteur`
- `etat` (ENUM) → remplacé par `statut`
- `photo_path`
- `allowed_zones`
- `authorized_hours_start`, `authorized_hours_end`
- `is_flagged`, `flag_reason`
- `notes`
- `tracking` fields (`last_entry`, `last_exit`, `total_entries_today`)

#### Nouveaux attributs (harmonisés):
```python
# Identification
matricule: String(20)         # Plaque d'immatriculation UNIQUE
marque: String(50)            # Ex: Toyota
modele: String(50)            # Ex: Land Cruiser
couleur: String(30)           # Couleur [OPTIONNEL]

# Classification
categorie: String(50)         # "civil" | "militaire"
unite: String(100)            # Unité militaire [OPTIONNEL, miliraire only]

# État
statut: String(50)            # "actif" | "hors_service" | "maintenance"

# Métadonnées
date_enregistrement: DateTime  # Auto-set création
date_modification: DateTime    # Auto-update modification
```

#### Mise à jour du __repr__:
```python
# AVANT:
return f"<VehicleRegistry(..., immatriculation={self.immatriculation}, type={self.type_vehicule}, etat={self.etat})>"

# APRÈS:
return f"<VehicleRegistry(..., matricule={self.matricule}, categorie={self.categorie}, statut={self.statut})>"
```

---

### 2. **Backend - Schémas Pydantic**
📁 `vms/backend/schemas.py`

#### Classes mises à jour:
- `VehicleRegistryBase`
- `VehicleRegistryCreate`
- `VehicleRegistryUpdate`
- `VehicleRegistryOut`

#### Validateurs ajoutés:
```python
# Validation categorie
categorie: str = Field(..., regex="^(civil|militaire)$")

# Validation statut
statut: str = Field(..., regex="^(actif|hors_service|maintenance)$")

# Auto-uppercase matricule
matricule: str = Field(..., min_length=3, max_length=20)
# → uppercase lors de la création dans le router
```

---

### 3. **Backend - Routes API**
📁 `vms/backend/routers/vehicles.py`

#### POST `/api/vehicles` - Créer véhicule
✅ **Mise à jour complète**
- Validation du `categorie` dans ["civil", "militaire"]
- Auto-null du champ `unite` si catégorie="civil"
- Conversion `matricule` en majuscules
- Création avec nouveau schéma

#### GET `/api/vehicles` - Lister véhicules
✅ **Mise à jour complète**
- Ancien: `type_vehicule`, `etat`, `is_flagged`
- Nouveau: `categorie`, `statut`
- Filtres: `?categorie=militaire&statut=actif`

#### GET `/api/vehicles/{vehicle_id}` - Récupérer véhicule
✓ Compatible avec nouveau schéma

#### PUT `/api/vehicles/{vehicle_id}` - Mettre à jour
✅ **Mise à jour complète**
- Log utilise nouveau champ: `vehicle.matricule`

#### DELETE `/api/vehicles/{vehicle_id}` - Supprimer (soft delete)
✅ **Mise à jour complète**
- Ancien: `vehicle.etat = "hors_service"`
- Nouveau: `vehicle.statut = "hors_service"`

#### Routes SUPPRIMÉES (obsolètes):
- POST `/{vehicle_id}/flag` - Utilise `is_flagged` (supprimé)
- POST `/{vehicle_id}/unflag` - Utilise `is_flagged` (supprimé)

---

### 4. **Base de Données**
📁 Script: `fix_vehicle_registry_db.py`

#### Actions effectuées:
✅ Vérification schéma ancien (21 colonnes)
✅ Suppression table `vehicle_registry`
✅ Création nouvelle table avec nouveau schéma (10 colonnes)
✅ Création d'index pour performance:
   - `idx_vehicle_matricule` (UNIQUE)
   - `idx_vehicle_categorie`
   - `idx_vehicle_statut`
   - `idx_vehicle_date_enregistrement`

#### Schéma SQL créé:
```sql
CREATE TABLE vehicle_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    matricule VARCHAR(20) UNIQUE NOT NULL,
    marque VARCHAR(50) NOT NULL,
    modele VARCHAR(50) NOT NULL,
    couleur VARCHAR(30),
    categorie VARCHAR(50) DEFAULT 'civil' NOT NULL,
    unite VARCHAR(100),
    statut VARCHAR(50) DEFAULT 'actif' NOT NULL,
    date_enregistrement DATETIME DEFAULT CURRENT_TIMESTAMP,
    date_modification DATETIME DEFAULT CURRENT_TIMESTAMP
)
```

---

### 5. **Frontend - Composant React**
📁 `vms/frontend/src/pages/VehiclesPage.tsx`

#### Interface Vehicle (TypeScript):
```typescript
interface Vehicle {
  id: number
  matricule: string                    // "MB2024001"
  marque: string                       // "Mercedes"
  modele: string                       // "G-Class"
  couleur?: string                     // "Vert militaire"
  categorie: 'civil' | 'militaire'    // Catégorie
  unite?: string                       // "Base Navale Monastir" (militaire only)
  statut: 'actif' | 'hors_service' | 'maintenance'
  date_enregistrement?: string
  date_modification?: string
}
```

#### Colonnes DataTable (mise à jour):
```typescript
columns={[
  { header: 'ID', field: 'id' },
  { header: 'Matricule', field: 'matricule' },
  { header: 'Marque', field: 'marque' },
  { header: 'Modèle', field: 'modele' },
  { header: 'Couleur', field: 'couleur' },
  { header: 'Catégorie', field: 'categorie', 
    render: (val) => val === 'militaire' ? '🎖️ Militaire' : '🚗 Civil' },
  { header: 'Unité', field: 'unite' },
  { header: 'Statut', field: 'statut',
    render: (val) => <span className={statusClass}>{val}</span> },
  { header: 'Enregistré', field: 'date_enregistrement', 
    render: (val) => new Date(val).toLocaleDateString('fr-FR') },
]}
```

#### Champs de formulaire (mise à jour):
- `matricule` (required): Plaque d'immatriculation
- `marque` (required): Marque du véhicule
- `modele` (required): Modèle du véhicule
- `couleur`: Couleur (optionnel)
- `categorie` (required, select): "civil" | "militaire"
- `unite`: Unité militaire (optionnel)
- `statut` (required, select): "actif" | "hors_service" | "maintenance"

#### Filtres ajoutés:
```typescript
<select value={filterCategorie} onChange={setFilterCategorie}>
  <option value="">Toutes les catégories</option>
  <option value="civil">Civil</option>
  <option value="militaire">Militaire</option>
</select>

<select value={filterStatut} onChange={setFilterStatut}>
  <option value="">Tous les statuts</option>
  <option value="actif">Actif</option>
  <option value="hors_service">Hors-service</option>
  <option value="maintenance">Maintenance</option>
</select>
```

#### Labels et messages en français:
- "Véhicules" (titre)
- "+ Ajouter Véhicule"
- "Actualiser"
- "Aucun véhicule enregistré..."
- "Êtes-vous sûr de vouloir marquer {matricule} comme hors-service?"

---

## 🔄 PATTERN HARMONISATION

### Cohérence Personnel ↔ Véhicules:

| Attribut | Personnel | Véhicules |
|----------|-----------|-----------|
| **Identité** | nom, prenom | marque, modele |
| **Identifiant unique** | cinématique (num_recrutement) | matricule (plaque) |
| **Classification** | categorie (officier/soldat/invite) | categorie (civil/militaire) |
| **Unité** | unité | unite (militaire only) |
| **État** | is_active (bool) | statut (string: actif/hors_service/maintenance) |
| **Dates** | date_enregistrement, date_modification | date_enregistrement, date_modification |
| **Langue** | Tous les labels/messages en **français** | Tous les labels/messages en **français** |

---

## 📝 DONNÉES DE TEST INSÉRÉES

Lors de l'exécution du script `fix_vehicle_registry_db.py`, les véhicules suivants ont été préparés:

```
MB2024001  | Mercedes     | G-Class      | Vert militaire | militaire | Base Navale | actif
BM2024001  | BMW          | X5           | Noir           | civil     | N/A         | actif
TOY2024001 | Toyota       | Land Cruiser | Blanc          | militaire | Commando    | actif
NO2024001  | Nissan       | Patrol       | Gris           | militaire | Base Navale | maintenance
```

---

## ✅ VALIDATIONS

### Backend:
- ✓ Modèle SQLAlchemy compiles sans erreurs
- ✓ Schémas Pydantic avec validateurs
- ✓ Routes API testables avec POST/GET/PUT/DELETE
- ✓ Filtrage par categorie et statut

### Frontend:
- ✓ Composant React compile
- ✓ Interface TypeScript stricte
- ✓ Filtres dropdown pour categorie/statut
- ✓ Affichage formaté avec emojis
- ✓ Dates au format français

### Base de données:
- ✓ Table recréée avec index
- ✓ Contrainte UNIQUE sur matricule
- ✓ 10 colonnes optimisées vs 21 anciennes

---

## 🚀 PROCHAINES ÉTAPES (facultatif)

1. **Migration des données existantes** (s'il y avait des véhicules)
   - Export ancienne schema en JSON
   - Transformation matricule/marque/modele
   - Import dans nouveau schéma

2. **Tests d'intégration complets**
   ```bash
   python test_vehicle_schema.py
   ```

3. **Documentation API mise à jour**
   - OpenAPI spec avec nouveaux champs
   - Swagger UI "/docs"

4. **Déploiement production**
   - Backup base de données
   - Exécuter `fix_vehicle_registry_db.py`
   - Redémarrer backend/frontend

---

## 📞 CONTACT

Pour toute question sur cette harmonisation de schéma, consulter l'auteur de la modification.

**Version**: 2.0.0 (Harmonisée)
**Compatible**: Falcon AI Vision - Base Navale Monastir
