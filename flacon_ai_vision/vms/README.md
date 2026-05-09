# Falcon AI Vision - Unified Server

## Architecture

Serveur Python unique combinant Backend API + Frontend Statique

```
vms/
├── backend/
│   ├── main.py              # Serveur FastAPI unifié
│   ├── __init__.py
│   ├── api/                 # Modules API (en construction)
│   │   ├── cameras.py
│   │   ├── users.py
│   │   └── events.py
│   ├── ai/                  # Modules IA (en construction)
│   │   ├── motion.py
│   │   ├── face.py
│   │   ├── plate.py
│   │   └── utils.py
│   └── core/                # Configuration (en construction)
│       ├── config.py
│       └── database.py
│
├── frontend/
│   ├── templates/           # Fichiers HTML
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   └── ...
│   └── static/              # CSS, JS, images
│       ├── *.css
│       ├── *.js
│       └── ...
│
├── storage/                 # Données persistantes
│   └── falcon_ai_vision.db
│
└── __init__.py
```

## Démarrage du Serveur

### Option 1: Script batch
```batch
start_unified.bat
```

### Option 2: Ligne de commande
```bash
cd /d "C:\Users\boufm\Desktop\eye of falcon"
.venv\Scripts\activate.bat
python -m uvicorn vms.backend.main:app --host 0.0.0.0 --port 8000
```

### Option 3: Python direct
```bash
python vms/backend/main.py
```

## Accès

- **Frontend (Login/Dashboard)**: http://127.0.0.1:8000/
- **API Backend**: http://127.0.0.1:8000/api/
- **API Documentation (Swagger)**: http://127.0.0.1:8000/docs
- **Health Check**: http://127.0.0.1:8000/health

## Endpoints API

### Auth
- `POST /api/login` - Login utilisateur
- `POST /api/register` - Créer compte

### Caméras
- `GET /api/cameras` - Lister caméras
- `POST /api/cameras` - Créer caméra

### Zones
- `GET /api/zones` - Lister zones
- `POST /api/zones` - Créer zone (supporte legacy: `zone_name`, `points`)

### Événements
- `GET /api/events` - Lister événements
- `POST /api/events` - Créer événement

## Avantages de cette Architecture

✅ **Déploiement simple** - Un seul serveur Python à lancer
✅ **Aucune dépendance serveur web** - FastAPI + StaticFiles inclus
✅ **CORS automatique** - Pas de conflits frontend/backend
✅ **Fichiers statiques optimisés** - Serveur HTTP intégré
✅ **Développement rapide** - Rechargement automatique (`--reload`)
✅ **Production ready** - Export simple avec `uvicorn`

## Structure Future

Les dossiers `api/`, `ai/`, `core/` sont prêts pour accueillir:
- Modules de routage séparés par domaine
- Services IA (détection mouvements, reconnaissance faciale, plaques)
- Configuration centralisée et gestion de base de données
