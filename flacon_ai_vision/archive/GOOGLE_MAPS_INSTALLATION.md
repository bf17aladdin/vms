# 📦 INSTALLATION GOOGLE MAPS - GUIDE COMPLET

## 1️⃣ INSTALLER LES PACKAGES

```bash
# Aller au dossier frontend
cd vms/frontend

# Installer Google Maps API wrapper pour React
npm install @react-google-maps/api

# Installer les types TypeScript (déjà inclus dans le package au-dessus)
npm install -D @types/google.maps
```

## Packages installés:
- ✅ `@react-google-maps/api`: Wrapper React pour Google Maps
- ✅ `@types/google.maps`: Types TypeScript pour l'API Google Maps

---

## 2️⃣ CONFIGURER LA CLÉ API

### Créer le fichier `.env.local`

Depuis le dossier `vms/frontend/`, crée un fichier nommé `.env.local`:

```env
VITE_GOOGLE_MAPS_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Remplace** `AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` par ta clé API réelle obtenue de Google Cloud Platform.

### Identifier ta clé API

La clé ressemble à:
```
AIzaSy_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9
```

---

## 3️⃣ VÉRIFIER .gitignore

Assure-toi que `.env.local` est ignoré par Git pour éviter de pusher ta clé API:

```bash
# vms/frontend/.gitignore

# Fichier d'environnement (JAMAIS pusher!)
.env.local
.env*.local
.env.*.local
```

---

## 4️⃣ VÉRIFIER QUE TOUT FONCTIONNE

### Test 1: Variable d'environnement chargée

```tsx
// Dans n'importe quel composant React
const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY
console.log('API Key Config:', apiKey ? '✅ Loaded' : '❌ Missing')
```

### Test 2: Démarrer le projet

```bash
# Terminal depuis vms/frontend
npm run dev
```

Ouvre le navigateur: `http://localhost:5173`

Navigation → **🗺️ Map View** (dans le menu latéral)

### Test 3: Vérifier la console

Ouvre la console du navigateur (F12):
- ❌ Si tu vois: `Erreur: Clé Google Maps non configurée` → Vérifie ton `.env.local`
- ✅ Si tu vois une carte interactive → Tout fonctionne!

---

## 5️⃣ ERREURS COURANTES

### ❌ Erreur: "VITE_GOOGLE_MAPS_API_KEY is not defined"

**Cause**: La clé API n'est pas configurée

**Solution**:
1. Crée `.env.local` depuis `vms/frontend/`
2. Ajoute: `VITE_GOOGLE_MAPS_API_KEY=AIzaSy...`
3. Redémarre le serveur dev: `npm run dev`

---

### ❌ Erreur: "Maps JavaScript API is not loaded"

**Cause**: Clé API invalide ou API non activée

**Solution**:
1. Vérifie que tu as activé **Maps JavaScript API** dans Google Cloud
2. Copie-colle exactement ta clé (pas d'espaces)
3. Attends quelques minutes (l'activation peut prendre du temps)

---

### ❌ Erreur: "Quota exceeded" ou "Billing required"

**Cause**: Ton quota Google gratuit est dépassé

**Solution**:
1. Active la facturation dans Google Cloud Console
2. Ou réduis l'utilisation (ne pas recharger la carte trop souvent)

---

### ❌ Erreur: "Referer not allowed"

**Cause**: Ta clé API est restreinte mais le referer n'est pas dans la liste

**Solution**:
1. Va dans Google Cloud → APIs & Services → Identifiants
2. Sélectionne ta clé API
3. Ajoute dans "URIs HTTP referrer acceptés":
   ```
   http://localhost:5173/*
   https://tondomaine.com/*
   ```

---

## 6️⃣ FICHIERS MODIFIÉS/CRÉÉS

- ✅ `vms/frontend/.env.local` (NE PAS PUSHER)
- ✅ `vms/frontend/src/components/Map/GoogleMapsComponent.tsx` (nouveau)
- ✅ `vms/frontend/src/pages/map/MapPage.tsx` (mis à jour)

---

## 7️⃣ FONCTIONNALITÉS DISPONIBLES

### Composant GoogleMapsComponent

```tsx
<GoogleMapsComponent
  apiKey={apiKey}                    // Clé API Google
  locations={mapLocations}            // Array de MapLocation
  onMarkerClick={handleClick}         // Callback au clic
  defaultCenter={{lat: 33.97, lng: -6.85}}  // Centre initial
  defaultZoom={11}                    // Zoom initial
/>
```

### Types MapLocation

```tsx
interface MapLocation {
  id: number | string
  name: string
  latitude: number
  longitude: number
  type: 'camera' | 'zone' | 'vehicle' | 'vehicle_registry' | 'personnel'
  status?: string                    // 'online', 'offline', 'flagged', etc
  polygon_points?: Array<{lat, lng}> // Pour zones avec polygones
  zone_radius?: number               // Pour zones avec cercle
  metadata?: Record<string, any>     // Infos additionnelles
}
```

---

## 8️⃣ AFFICHAGE DE LA CARTE

### Éléments affichés

✅ **Caméras** - Marqueur violet
- Statut: Online/Offline
- Location détaillée

✅ **Zones** - Marqueur bleu + Polygone/Cercle
- Zone de couverture
- Rayon si défini

✅ **Véhicules Détectés** - Marqueur jaune
- État: actif, maintenance, hors_service
- Dernière détection

✅ **Registre Véhicules** - Marqueur orange
- Immatriculation
- État signalement

---

## 9️⃣ OPTIMISATIONS

### 1. Mettre en cache les données

```tsx
const [lastLoadTime, setLastLoadTime] = useState<number>(0)
const CACHE_DURATION = 30000 // 30 secondes

const shouldRefresh = Date.now() - lastLoadTime > CACHE_DURATION
```

### 2. Limiter les requêtes API

```tsx
// Pas de requête si les données existent déjà
if (mapLocations.length > 0) return

loadAllMapData()
```

### 3. Filtrer côté client plutôt qu'API

```tsx
// ✅ BON: Filtrer après chargement
const filtered = mapLocations.filter(l => l.type === 'camera')

// ❌ MAUVAIS: Recharger depuis l'API à chaque filtre
apiClient.get('/cameras?filter=...')
```

---

## 🔟 NEXT STEPS

- [ ] Configurer clé Google Maps
- [ ] Créer `.env.local`
- [ ] Installer packages: `npm install @react-google-maps/api`
- [ ] Démarrer front: `npm run dev`
- [ ] Tester la page `/map`
- [ ] Ajouter GPS aux caméras/zones/véhicules
- [ ] Personnaliser marqueurs (icônes custom)
- [ ] Ajouter cliquetage multi-marqueurs
- [ ] Implémenter heatmap
- [ ] Ajouter routing

---

## 🚀 DÉPLOIEMENT PRODUCTION

### Avant de déployer:

1. ✅ Clé API avec restrictions:
   - Domains: `tonsite.com`
   - APIs: Maps JavaScript API uniquement
   - HTTP referrer: `https://tonsite.com/*`

2. ✅ Variables d'env sécurisées:
   ```bash
   # .env.production
   VITE_GOOGLE_MAPS_API_KEY=AIzaSy...
   ```

3. ✅ Monitoring quota:
   - Google Cloud → Workload
   - Alerte si quota > 80%

---

## 📞 SUPPORT

- 📖 [Google Maps API Docs](https://developers.google.com/maps/documentation/javascript)
- 🐛 [React Google Maps GitHub](https://github.com/JustFly1984/react-google-maps)
- 💬 [Stack Overflow Tag: google-maps-api](https://stackoverflow.com/questions/tagged/google-maps-api)

---

**Prêt à afficher ta carte! 🗺️**
