# 🚀 Démarrage Rapide - Falcon AI Vision

## ⚡ Démarrer les serveurs

### Option 1: PowerShell (Recommandé ✅)
```powershell
.\START_FINAL.ps1
```
- ✅ Démarre automatiquement backend (port 5003) + frontend (port 3000)
- ✅ Ouvre le navigateur sur `http://localhost:3000`
- ✅ Vous verrez le formulaire de login automatiquement

### Option 2: Python
```python
python start_all.py
```

---

## 📱 Accès à l'application

| Ressource | URL |
|-----------|-----|
| **Application** | http://localhost:3000 |
| **API Backend** | http://localhost:5003/api |
| **Documentation API** | http://localhost:5003/docs |

---

## 🔐 Credentials par défaut

| Paramètre | Valeur |
|-----------|--------|
| **Username** | `admin` |
| **Password** | `admin123` |

---

## ✨ Résolution des problèmes

### ❌ Problem: `/login.html` appears instead of home page
**✅ Résolu:** Le fichier `login.html` statique a été archivé.

React Router gère maintenant automatiquement:
- `http://localhost:3000` → Page de login (si non authentifié)
- `http://localhost:3000` → Dashboard (si authentifié)

### ❌ Problem: "API is not responding"
**✅ Solution:**
1. Vérifiez que le backend est en cours d'exécution (port 5003)
2. Vérifiez les logs du backend dans le terminal

### ❌ Problem: "Connection refused" sur port 3000/5003
**✅ Solution:**
Attendez 3-5 secondes que les serveurs se lancent complètement

---

## 📁 Structure clé

```
eye-of-falcon/
├── START_FINAL.ps1      ← Point d'entrée
├── start_all.py         ← Alternative Python
├── vms/
│   ├── backend/         ← API FastAPI (port 5003)
│   ├── frontend/        ← App Vite React (port 3000)
│   └── facial_recognition/
└── archive/             ← Fichiers obsolètes
```

---

## 🧪 Tests rapides

Après le démarrage:
1. **Page de login** → `http://localhost:3000`
2. **Connectez-vous** → admin / admin123
3. **Dashboard** → Vous verrez le tableau de bord principal
4. **API Test** → `http://localhost:5003/docs`

---

## 🛠️ Maintenance

### Archiver d'anciens fichiers (déjà fait)
- ✅ `login.html` statique → archivé
- ✅ Scripts de démarrage obsolètes → dossier `archive/`

### Nettoyer les ports
```bash
# Trouver les processus sur les ports
netstat -ano | findstr ":3000\|:5003"

# Tuer un processus (Windows)
taskkill /PID <PID> /F
```

---

## 📝 Notes

- Les modifications frontend rechargent automatiquement (HMR Vite)
- Les modifications backend rechargent avec `--reload` (uvicorn)
- Logs disponibles dans les fenêtres de terminal correspondantes

**Besoin d'aide?** Consultez les fichiers de documentation dans le dossier racine.
