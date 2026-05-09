# 🗺️ GUIDE INTÉGRATION GOOGLE MAPS

## 1️⃣ OBTENIR UNE CLÉ GOOGLE MAPS API

### Étape 1: Accéder à Google Cloud Platform
1. Va sur **[Google Cloud Console](https://console.cloud.google.com/)**
2. Clique sur **"Créer un projet"**
3. Donne un nom: `Falcon AI Vision`
4. Clique **"Créer"**

### Étape 2: Activer les APIs Google Maps
1. Dans le panneau de navigation → **APIs & Services** → **Bibliothèque**
2. Recherche et active ces APIs:
   - ✅ **Maps JavaScript API**
   - ✅ **Maps Marker API**
   - ✅ **Distance Matrix API** (optionnel, pour distances)
   - ✅ **Geocoding API** (optionnel, pour adresses → lat/lng)

3. Pour chaque API:
   - Clique sur l'API
   - Clique **"Activer"**

### Étape 3: Créer une clé API
1. **APIs & Services** → **Identifiants**
2. Clique **"Créer des identifiants"** → **Clé API**
3. Une clé est créée (elle ressemble à: `AIzaSy...`)
4. Copie cette clé (tu en auras besoin)

### Étape 4: Restreindre la clé API (Sécurité)
1. Clique sur la clé crée
2. Dans **"Restrictions des applications"**:
   - Sélectionne **"Applications HTTP (sites web)"**
3. Dans **"URIs HTTP referrer acceptés"**, ajoute:
   ```
   http://localhost:5173/*
   http://localhost:3000/*
   http://127.0.0.1:5173/*
   ```
4. Dans **"Restrictions des APIs"**:
   - Sélectionne **"Restreindre l'utilisation"**
   - Checkboxe les APIs que tu vas utiliser
5. Clique **"Enregistrer"**

---

## 2️⃣ CONFIGURER LA CLÉS DANS L'APPLICATION

### Créer un fichier `.env.local` (Frontend)

Depuis `vms/frontend/`, crée un fichier `.env.local`:
```bash
VITE_GOOGLE_MAPS_API_KEY=AIzaSy...
```

**⚠️ NE PAS pusher ce fichier sur Git!**

### Vérifier `.gitignore`

```
# vms/frontend/.gitignore
.env.local
.env*.local
```

---

## 3️⃣ INSTALLER LES DÉPENDANCES

### Package Google Maps pour React

```bash
cd vms/frontend

npm install @react-google-maps/api
npm install -D @types/google.maps
```

Cela installe:
- `@react-google-maps/api`: Wrapper React pour Google Maps
- `@types/google.maps`: Types TypeScript

---

## 4️⃣ INTÉGRATION DANS LE CODE

### Structure des données (Backend)

Les modèles doivent avoir des champs `latitude` et `longitude`:

#### **Camera** ✅
```python
class Camera(Base):
    __tablename__ = "cameras"
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
```

#### **Zone** ✅
```python
class Zone(Base):
    __tablename__ = "zones"
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    polygon_points = Column(JSON)  # [{lat, lng}, {lat, lng}, ...]
```

#### **Vehicle (Détection temps réel)** ✅
```python
class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(Integer, primary_key=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    last_seen = Column(DateTime)
```

#### **VehicleRegistry (Registre militaire)** ✅
```python
class VehicleRegistry(Base):
    __tablename__ = "vehicle_registry"
    id = Column(Integer, primary_key=True)
    immatriculation = Column(String(50))
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
```

---

## 5️⃣ COMPOSANT REACT GOOGLE MAPS

### Fichier: `GoogleMapsComponent.tsx`

```tsx
import React, { useEffect, useState } from 'react'
import { GoogleMap, LoadScript, Marker, InfoWindow, Polygon } from '@react-google-maps/api'

interface MapLocation {
  id: number
  name: string
  latitude: number
  longitude: number
  type: 'camera' | 'zone' | 'vehicle' | 'personnel'
  status?: string
  metadata?: any
}

interface GoogleMapsComponentProps {
  apiKey: string
  locations: MapLocation[]
  onMarkerClick?: (location: MapLocation) => void
  defaultCenter?: { lat: number; lng: number }
  defaultZoom?: number
}

export const GoogleMapsComponent: React.FC<GoogleMapsComponentProps> = ({
  apiKey,
  locations,
  onMarkerClick,
  defaultCenter = { lat: 33.9716, lng: -6.8498 }, // Casablanca coords
  defaultZoom = 12,
}) => {
  const [selectedLocation, setSelectedLocation] = useState<MapLocation | null>(null)
  const mapRef = React.useRef<google.maps.Map | null>(null)

  const getMarkerIcon = (type: string, status?: string) => {
    const baseUrl = 'https://maps.google.com/mapfiles/ms/icons/'
    
    switch (type) {
      case 'camera':
        return `${baseUrl}camera.png` // Purple
      case 'zone':
        return `${baseUrl}blue-dot.png` // Blue
      case 'vehicle':
        return status === 'flagged' ? `${baseUrl}red-dot.png` : `${baseUrl}yellow-dot.png`
      case 'personnel':
        return `${baseUrl}green-dot.png` // Green
      default:
        return `${baseUrl}red-dot.png`
    }
  }

  const containerStyle = {
    width: '100%',
    height: '100%',
  }

  return (
    <LoadScript googleMapsApiKey={apiKey}>
      <GoogleMap
        mapContainerStyle={containerStyle}
        center={defaultCenter}
        zoom={defaultZoom}
        onLoad={(map) => {
          mapRef.current = map
        }}
      >
        {/* Markers pour toutes les localisations */}
        {locations.map((location) => (
          <Marker
            key={`${location.type}-${location.id}`}
            position={{
              lat: location.latitude,
              lng: location.longitude,
            }}
            icon={getMarkerIcon(location.type, location.status)}
            onClick={() => {
              setSelectedLocation(location)
              onMarkerClick?.(location)
            }}
            title={location.name}
          />
        ))}

        {/* Info Window (popup) */}
        {selectedLocation && (
          <InfoWindow
            position={{
              lat: selectedLocation.latitude,
              lng: selectedLocation.longitude,
            }}
            onCloseClick={() => setSelectedLocation(null)}
          >
            <div className="p-3 max-w-xs">
              <h3 className="font-bold text-sm mb-1">{selectedLocation.name}</h3>
              <p className="text-xs text-gray-600 mb-2">
                Type: <span className="font-semibold">{selectedLocation.type}</span>
              </p>
              {selectedLocation.status && (
                <p className="text-xs text-gray-600 mb-2">
                  Status: <span className="font-semibold">{selectedLocation.status}</span>
                </p>
              )}
              <p className="text-xs text-gray-600">
                📍 {selectedLocation.latitude.toFixed(4)}, {selectedLocation.longitude.toFixed(4)}
              </p>
              {selectedLocation.metadata && (
                <div className="mt-2 text-xs text-gray-700 border-t pt-2">
                  {Object.entries(selectedLocation.metadata).map(([key, value]) => (
                    <div key={key}>
                      <strong>{key}:</strong> {String(value)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </InfoWindow>
        )}
      </GoogleMap>
    </LoadScript>
  )
}

export default GoogleMapsComponent
```

---

## 6️⃣ UTILISER LE COMPOSANT

### Dans `MapPage.tsx`

```tsx
import { GoogleMapsComponent } from './GoogleMapsComponent'
import { cameraService } from '../../services/modules'
import { apiClient } from '../../services/api'

export const MapPage: React.FC = () => {
  const [locations, setLocations] = useState<MapLocation[]>([])
  const apiKey = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || ''

  useEffect(() => {
    loadMapLocations()
  }, [])

  const loadMapLocations = async () => {
    try {
      // Charger caméras
      const cameras = await cameraService.getAll()
      const cameraLocations = cameras
        .filter((c) => c.latitude && c.longitude)
        .map((c) => ({
          id: c.id,
          name: c.name,
          latitude: c.latitude,
          longitude: c.longitude,
          type: 'camera' as const,
          status: c.connection_status,
          metadata: { location: c.location },
        }))

      // Charger zones
      const zones = await apiClient.get('/zones')
      // ... traiter zones

      // Charger véhicules
      const vehicles = await apiClient.get('/vehicle-registry/list')
      // ... traiter véhicules

      setLocations([...cameraLocations, ...zoneLocations, ...vehicleLocations])
    } catch (err) {
      console.error('Erreur chargement carte:', err)
    }
  }

  return (
    <div className="h-full">
      <GoogleMapsComponent
        apiKey={apiKey}
        locations={locations}
        onMarkerClick={(location) => console.log('Cliqué:', location)}
      />
    </div>
  )
}
```

---

## ✅ CHECKLIST

- [ ] Créer projet Google Cloud
- [ ] Activer Maps JavaScript API
- [ ] Créer clé API
- [ ] Restreindre clé API (localhost)
- [ ] Créer `.env.local` avec clé
- [ ] Installer `@react-google-maps/api`
- [ ] Créer `GoogleMapsComponent.tsx`
- [ ] Mettre à jour `MapPage.tsx`
- [ ] Tester la carte dans le navigateur
- [ ] Vérifier que les markers s'affichent

---

## 🔒 SÉCURITÉ

- ✅ Clé API restreinte à localhost
- ✅ `.env.local` dans `.gitignore`
- ✅ Validation côté backend
- ✅ Pas de clé exposée en public

---

## 🚀 PROCHAINES ÉTAPES

1. Heatmap des détections véhicules
2. Routing (itinéraires)
3. Géofencing (alertes zones)
4. Street View pour caméras
5. Export carte en PDFs

---

**Prêt à maîtriser la carte! 🗺️**
