# Falcon AI Vision

## AI Security Backend produit

**Falcon AI Vision est un backend de sécurité vidéo intelligent capable de détecter des visages et des véhicules, de prendre des décisions automatiques (`allow` / `deny`) et de déclencher des actions en temps réel.**

### Ce que le système fait réellement
- Détection de visages
- Détection de véhicules
- Reconnaissance des entités autorisées
- Gestion des inconnus via une file d'attente `unknown`
- Prise de décision automatique
- Déclenchement d'actions : logs, alertes, contrôle d'accès

### Fonctionnalités principales
- Détection et reconnaissance en temps réel
- Moteur de décision centralisé
- Action engine intégré pour exécuter les réponses de sécurité
- Pipelines Face / Vehicle testés pour assurer la qualité
- Backend API construit avec FastAPI

## Architecture produit
- Backend principal : `backend/vms/backend`
- Frontend marketing + dashboard : `frontend/website`
- SPA optionnelle : `frontend/src`
- Outils média et utilitaires : `tools/`

## Quick start local
1. Installer Python 3.11
2. Créer un environnement virtuel

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Configurer l'environnement
- Copier `.env.example` en `.env`
- Définir `SECRET_KEY`, `DATABASE_URL`, et autres variables de configuration

4. Lancer le backend

```powershell
.venv\Scripts\uvicorn.exe vms.backend.main:app --port 5003
```

5. Ouvrir l'interface
- Site produit : `http://127.0.0.1:5003/`
- API docs : `http://127.0.0.1:5003/docs`

## Mode frontend
Le backend peut servir :
- `FRONTEND_MODE=website` (par défaut)
- `FRONTEND_MODE=spa`

## Validation et tests
Tests d'intégration backend recommandés :
- `backend/vms/backend/tests/test_pipeline_decision_integration.py`

Commandes de validation :

```powershell
.\scripts\validate_backend.ps1
```

```bash
bash ./scripts/validate_backend.sh
```

### Exemples de validation rapide
- Vérifier `/health`
- Vérifier qu'un compte peut se créer et se connecter
- Vérifier création d'une caméra API
- Vérifier remontée d'un événement
- Vérifier réponse d'un endpoint IA

## Sécurité production
- Utiliser une `SECRET_KEY` forte
- Définir `ALLOWED_HOSTS`
- Activer `REQUIRE_HTTPS=true`
- Fixer des `CORS_ORIGINS` explicites
- Désactiver `debug` en production

## Organisation du produit
```
falcon_ai_vision/
├─ backend/vms/backend/        # Backend FastAPI + pipelines AI
├─ frontend/website/           # Marketing + dashboard
├─ frontend/src/               # SPA optionnelle
├─ frontend/legacy/            # Frontends archivés
├─ tools/                      # MediaMTX et utilitaires
├─ docs/                       # Documentation produit
├─ .env.example                # Modèle de configuration
```

## Documentation
Voir aussi :
- `docs/`
- `GETTING_STARTED.md`
- `QUICK_START.md`
- `TECHNICAL_MAINTENANCE_GUIDE.md`

## Positionnement produit
Falcon AI Vision se positionne comme un système de sécurité vidéo intelligent, combinant :
- computer vision
- reconnaissance biométrique et plaque
- moteur de décision automatique
- orchestration d'actions de sécurité en temps réel
