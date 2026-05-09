# Falcon AI Vision - Load Test (RTSP + IA)

Ce dossier contient des outils pour simuler des flux RTSP (ffmpeg + mediamtx) et évaluer la pipeline de détection IA (motion + objets) en temps réel.

## ✅ Prérequis
1. Backend en cours d'exécution (par défaut `http://127.0.0.1:5010`).
2. `ffmpeg` accessible dans le PATH, ou passez `-FfmpegPath` à `start_rtsp_load_test.ps1`.
3. `mediamtx` disponible dans `tools/mediamtx_v1.16.2/mediamtx.exe` (ou utilisez `-MediamtxPath`).
4. Les limites de caméras doivent être configurées (admin tier ou `setup_config.json`).

---

## ▶️ Lancer des flux RTSP (ffmpeg)

### Démarrer les flux RTSP
```powershell
powershell -ExecutionPolicy Bypass -File falcon_ai_vision-platform/tools/load_test/start_rtsp_load_test.ps1 -Streams 10
```

### Arrêter les flux
```powershell
powershell -ExecutionPolicy Bypass -File falcon_ai_vision-platform/tools/load_test/stop_rtsp_load_test.ps1
```

### Options utiles
- **Without mediamtx** (si vous avez déjà un serveur RTSP) :
  ```powershell
  ...\start_rtsp_load_test.ps1 -Streams 10 -SkipMediamtx
  ```
- **Changer la résolution / fps** :
  ```powershell
  ...\start_rtsp_load_test.ps1 -Streams 10 -Resolution "1920x1080" -Fps 30
  ```
- **Logs** :
  Les logs de chaque flux sont écrits dans `tools/load_test/logs/`.

---

## 🧠 Test IA temps réel (motion + object detection)

### Exécution (30 min, reporting toutes les 5 min)
```powershell
python .\tools\load_test\rtsp_ai_realtime_test.py --count 5 --duration 1800 --report-interval 300
```

### Résultats
Le script crée un CSV par caméra dans `tools/load_test/` :
- `rtsp_ai_realtime_results_cam1.csv`
- `rtsp_ai_realtime_results_cam2.csv`

Ces fichiers contiennent, à chaque intervalle : fps, latence, nombre d'objets détectés, etc.

---

## 📈 Test de montée en charge (auto)

Un script permet de faire plusieurs paliers de charge et de mesurer le nombre de flux effectivement lancés :

```powershell
powershell -ExecutionPolicy Bypass -File falcon_ai_vision-platform/tools/load_test/auto_rtsp_load_test.ps1 -MaxStreams 50 -Step 5 -HoldSeconds 300
```

Résultat : `tools/load_test/load_test_results.csv` qui indique pour chaque palier si la plateforme a tenu.

---

## 🧩 Autres utilitaires
- `create_load_test_cameras.ps1` / `delete_load_test_cameras.ps1` (gestion des caméras test dans le backend)

---

## ✅ Conseils “pro”
- Assurez-vous que `mediamtx` est en fonctionnement (ou utilisez un vrai serveur RTSP).
- Lancez d’abord `start_rtsp_load_test.ps1`, puis le script IA (`rtsp_ai_realtime_test.py`) en parallèle.
- Pour un vrai test cluster, exécutez le script IA sur plusieurs serveurs en parallèle et agrégez les CSV.
