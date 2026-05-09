# PHASE 5: DÉPLOIEMENT EN PRODUCTION - FALCON AI VISION

## 📋 Vue d'ensemble de Phase 5

**Objectif**: Préparer Falcon AI Vision pour déploiement en production avec:
- ✅ Containerisation Docker (multi-stage, optimisée)
- ✅ Orchestration multi-services (docker-compose)
- ✅ Limitation de débit (rate limiting avec slowapi)
- ✅ Monitoring & métriques (Prometheus)
- ✅ Configuration centralisée (.env)
- ✅ Sécurité renforcée (secrets, CORS, authentification)

**État**: Phase 5 est **100% complète** - infrastructure créée et intégrée

---

## 🚀 DÉMARRAGE RAPIDE (5 minutes)

### 1. Validation de l'environnement
```bash
# Vérifier les prérequis
python deploy_phase5.py

# Résultats attendus:
# ✅ File Structure - PASS
# ✅ Dependencies - PASS
# ✅ Docker - PASS
# ✅ Configuration - PASS
# Score: 9/9 checks passed
# 🎉 READY FOR PRODUCTION DEPLOYMENT!
```

### 2. Configuration de l'environnement
```bash
# .env sera généré automatiquement par deploy_phase5.py
# Ou créer manuellement:
cp .env.example .env

# IMPORTANT: Éditer .env avec vos valeurs réelles
# - DB_HOST, DB_PORT, DB_USER, DB_PASSWORD
# - JWT_SECRET_KEY (généré aléatoirement, mais DOIT être changé)
# - Autres variables sensibles
```

### 3. Lancer les services
```bash
# Démarrer tous les services
docker-compose up -d

# Attendre 30 secondes pour l'initialisation MySQL
sleep 30

# Vérifier l'état des services
docker-compose ps

# Affichage attendu:
# NAME            STATUS      PORTS
# falcon-ai-vision   Up (healthy) 0.0.0.0:5003->5003/tcp
# db              Up (healthy) 0.0.0.0:3306->3306/tcp
# prometheus      Up (healthy) 0.0.0.0:9090->9090/tcp
# grafana         Up           0.0.0.0:3000->3000/tcp
```

### 4. Tester les services
```bash
# Santé de l'application
curl http://localhost:5003/health

# Réponse attendue:
# {"status":"ok","timestamp":"2024-01-15T10:30:45.123456"}

# Métriques Prometheus
curl http://localhost:5003/metrics

# Smoke test complet
python phase5_smoke_test.py
```

---

## 📦 COMPOSANTS DÉPLOYÉS

### Architecture Docker

```
┌─────────────────────────────────────────┐
│         Docker Network                  │
│    (falcon-ai-vision-network)              │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────┐  ┌──────────────┐    │
│  │   app        │  │   db         │    │
│  │ (FastAPI)    │  │ (MySQL 8.0)  │    │
│  │ :5003        │  │ :3306        │    │
│  └──────────────┘  └──────────────┘    │
│                                         │
│  ┌──────────────┐  ┌──────────────┐    │
│  │ prometheus   │  │   grafana    │    │
│  │ :9090        │  │ :3000        │    │
│  └──────────────┘  └──────────────┘    │
│                                         │
└─────────────────────────────────────────┘
```

### Services

#### `app` (FastAPI)
- **Port**: 5003
- **Image**: `falcon-ai-vision:latest`
- **Santé**: GET /health (intervalle: 30s)
- **Volumes**: 
  - `./data:/app/data` (détections, faces, véhicules)
  - `./logs:/app/logs` (journaux)
- **Variables d'env**: De `.env`
- **Commande**: `uvicorn vms.backend.main:app --host 0.0.0.0 --port 5003`

#### `db` (MySQL 8.0)
- **Port**: 3306
- **Image**: `mysql:8.0`
- **Santé**: MySQL health check (intervalle: 10s)
- **Volumes**:
  - `db_data:/var/lib/mysql` (données persistantes)
- **Initialisation**: `scripts/init.sql`

#### `prometheus` (Monitoring)
- **Port**: 9090
- **Image**: `prom/prometheus:latest`
- **Volumes**:
  - `prometheus_data:/prometheus`
  - `./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml`
- **Scrape**: App metrics @ `http://app:8000/metrics` (15s)

#### `grafana` (Dashboard)
- **Port**: 3000
- **Image**: `grafana/grafana:latest`
- **Admin**: admin/admin
- **Datasource**: Prometheus @ `http://prometheus:9090`

---

## 🔐 SÉCURITÉ

### Checklist de sécurité pré-production

```
CONFIGURATION (.env):
☐ JWT_SECRET_KEY est fort (>=32 caractères, aléatoire)
☐ DB_PASSWORD est fort et différent du template
☐ ENVIRONMENT=production (pas "development")
☐ DEBUG=False
☐ CORS_ORIGINS ne contient que les domaines autorisés

CONTENEURS:
☐ Non-root user (appuser:1000) dans Dockerfile
☐ Pas de secrets en dur dans l'image
☐ Health checks configurés pour tous les services
☐ Restart policy: `unless-stopped`

RÉSEAU:
☐ Proxy reverse en frontal (nginx/Apache)
☐ SSL/TLS obligatoire (HTTPS)
☐ Certificats valides
☐ Règles pare-feu: 5003 (app), 9090 (Prometheus interne)

BASE DE DONNÉES:
☐ User distinct pour chaque environnement
☐ Backups automatiques configurés (cron)
☐ Initialisation via scripts/init.sql réussie

MONITORING:
☐ Alerts configurés dans Prometheus
☐ Logs centralisés
☐ Métriques en graphiques Grafana
☐ Rate limiting actif
```

---

## 📊 MONITORING & MÉTRIQUES

### Métriques exposées

**Counters** (totaux cumulatifs):
- `app_requests_total` - Requêtes HTTP totales [méthode, endpoint, status]
- `app_websocket_frames_total` - Frames WebSocket traitées [camera_id, type]
- `app_ai_detections_total` - Détections IA totales [model_type, classe]
- `app_errors_total` - Erreurs totales [error_type, endpoint]

**Histograms** (distributions):
- `app_request_duration_seconds` - Latence requêtes HTTP
- `app_ai_inference_duration_seconds` - Temps inférence IA
- `app_db_query_duration_seconds` - Temps requêtes DB

**Gauges** (valeurs instantanées):
- `app_websocket_connections_active` - Connexions WebSocket actives
- `app_db_connections_active` - Connexions DB actives
- `app_memory_bytes` - Mémoire utilisée par le processus
- `app_queue_size` - Taille des queues asyncio

### Accès

**Prometheus UI**: http://localhost:9090
**Grafana UI**: http://localhost:3000 (admin/admin)
**API directe**: curl http://localhost:5003/metrics

---

## ⏱️ RATE LIMITING

### Limites prédéfinies

| Type | Limite | Raison |
|------|--------|--------|
| `PUBLIC_READ` | 100/minute | Endpoints de lecture |
| `PUBLIC_WRITE` | 30/minute | Modification publique |
| `LOGIN` | 10/minute | Brute-force protection |
| `WEBSOCKET` | 1000/minute | Streaming haute freq |
| `INTERNAL_READ` | 1000/minute | APIs internes (read) |
| `INTERNAL_WRITE` | 500/minute | APIs internes (write) |
| `AI_INFERENCE` | 50/minute | Inférences IA |
| `HEALTH_CHECK` | 1000/minute | Health checks |

### Utilisation dans les routes

```python
from vms.backend.core.rate_limiting import limiter, RateLimits

@app.get("/api/cameras")
@limiter.limit(RateLimits.PUBLIC_READ)
async def get_cameras(request: Request):
    ...
```

---

## 🧪 TESTS & VALIDATION

### Smoke Test Automatisé

```bash
# Valide complètement le déploiement Docker
python phase5_smoke_test.py

# Vérifie:
# 1. Build Docker OK
# 2. docker-compose.yml valide
# 3. Services démarrent
# 4. Health checks passent
# 5. Endpoints répondent
# 6. DB inicialize
# 7. Prometheus actif
# 8. Rate limiting fonctionnel
# 9. Logs sans erreurs
# 10. Cleanup OK
```

---

## 📈 DÉPLOIEMENT

### Local (Dev)
```bash
docker-compose up -d
```

### VPS/Cloud
```bash
git clone <repo>
cd eye-of-falcon
cp .env.example .env
# Éditer .env

# Setup reverse proxy (nginx)
# Configurer SSL/TLS
docker-compose up -d
```

### Kubernetes (Enterprise)
1. Adapter docker-compose → k8s manifests
2. Créer ConfigMaps pour .env
3. Créer Secrets pour DB passwords, JWT keys
4. PersistentVolumes pour données

---

## ✅ VALIDATION FINALE

Phase 5 est **COMPLÈTE** quand:

```
✅ Files Structure              (9/9 fichiers présents)
✅ Configuration                (.env généré)
✅ Dependencies                 (slowapi + prometheus-client)
✅ Docker                       (image builds)
✅ Services                     (tous "healthy")
✅ API Endpoints                (/health, /api, /metrics)
✅ Rate Limiting                (429 au dépassement)
✅ Monitoring                   (Prometheus + Grafana)
✅ Security                     (secrets, non-root, CORS)
✅ Smoke Test                   (10/10 PASS)
✅ Documentation                (ce guide)
```

**Progression**: Phase 4 (AI) ✅ → Phase 5 (Deployment) ✅

---

**Généré**: 2024  
**Version**: Phase 5 v1.0  
**Status**: 🟢 PRODUCTION-READY

