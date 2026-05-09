# Scaling Replay 20 Flux (avec 1 webcam physique)

Ce guide permet de tester la capacite reelle du runtime scaling sur 20 flux RTSP
en utilisant une seule webcam locale.

## 1) Prerequis

- `ffmpeg` installe et accessible dans le `PATH`
- `mediamtx` installe et lance localement (port RTSP par defaut `8554`)
- Environnement backend pret (DB accessible)
- Sur Windows, pour OpenCV webcam stable:
  - `OPENCV_VIDEOIO_PRIORITY_MSMF=0`

## 2) Enregistrer une video seed depuis la webcam

Exemple (120s):

```powershell
ffmpeg -f dshow -i video="Integrated Camera" -t 120 -r 25 -an -c:v libx264 -preset veryfast -pix_fmt yuv420p data\seed_webcam.mp4
```

Adapte `video="Integrated Camera"` selon le nom de ton peripherique.

## 3) Publier 20 flux RTSP depuis la meme video

Lancer 20 publishers `ffmpeg` vers `mediamtx` (offsets differents pour desynchroniser):

```powershell
$video = "data\seed_webcam.mp4"
for ($i = 1; $i -le 20; $i++) {
  $offset = $i % 15
  $url = "rtsp://127.0.0.1:8554/cam$i"
  Start-Process -WindowStyle Hidden -FilePath ffmpeg -ArgumentList @(
    "-hide_banner","-loglevel","warning",
    "-stream_loop","-1","-re",
    "-ss",$offset,
    "-i",$video,
    "-an",
    "-c:v","libx264","-preset","veryfast","-tune","zerolatency","-pix_fmt","yuv420p",
    "-f","rtsp",$url
  ) | Out-Null
}
```

## 4) Lancer le runtime replay 20 flux

```powershell
$env:ENABLE_SCALING_RUNTIME="True"
$env:OPENCV_VIDEOIO_PRIORITY_MSMF="0"
.\venv_ai\Scripts\python.exe scripts\run_scaling_runtime_replay.py `
  --camera-count 20 `
  --duration-sec 1800 `
  --sample-interval-ms 200 `
  --rtsp-url-template "rtsp://127.0.0.1:8554/cam{camera_id}" `
  --queue-backend sqlite `
  --queue-sqlite-path data\scaling_runtime_queue.db `
  --queue-namespace replay20 `
  --persist-target db `
  --inference-workers 8 `
  --inference-batch-size 4 `
  --inference-batch-max-wait-ms 20 `
  --writer-workers 6 `
  --enable-adaptive-rate `
  --p95-threshold-ms 3000 `
  --queue-depth-threshold 1200 `
  --persist-success-threshold-pct 99 `
  --output-json logs\scaling_replay_20_report.json
```

## 5) Critere Go / No-Go

- `evaluation.verdict == "GO"`
- `p95_end_to_end_ms < 3000`
- `queue_depth_high_watermark < 1200`
- `event_persist_success_pct >= 99`

## 6) Test de resilience recommande

Pendant le run:
- Arreter 2-3 publishers (`ffmpeg`) pendant 1-2 min puis relancer
- Verifier:
  - pas de crash runtime
  - reprise ingestion sur les flux revenus
  - succes persistance reste >= 99%

## 7) Panel de sante runtime (Sprint 5)

Le rapport JSON contient `final_snapshot.runtime_health_panel` avec:
- `summary`: CPU, memoire, queue depth/utilisation, drop rate, latence inference, p95 end-to-end, succes persistance
- `per_camera`: FPS lecture, skip rate, erreurs lecture, latence inference par camera
- `status`: `healthy | degraded | down`
- `risks`: liste des points de tension detectes

Les `progress_samples` incluent aussi:
- `health_status`
- `frame_queue_util_pct`
- `cpu_percent`
- `inference_avg_latency_ms`
- `persist_success_pct`

## 8) Fondation distribuee (Sprint 6)

Le runtime supporte deux backends de transport:
- `memory` (defaut): queue locale en RAM
- `sqlite`: queue partagee via fichier SQLite (base pour separation inter-process)

Options CLI disponibles dans les scripts runtime:
- `--queue-backend memory|sqlite`
- `--queue-sqlite-path <path>`
- `--queue-namespace <name>`

Le snapshot expose `final_snapshot.queue_transport` pour tracer le mode actif.

## 9) Orchestration role-based (Sprint 7)

Nouveau script:
- `scripts/run_scaling_runtime_distributed.py`

Roles disponibles:
- `--role ingestion`
- `--role inference`
- `--role writer`
- `--role full`

Exemple "1 process par role" (3 terminaux) sur transport SQLite partage:

Terminal 1 (ingestion):
```powershell
.\venv_ai\Scripts\python.exe scripts\run_scaling_runtime_distributed.py `
  --role ingestion `
  --queue-backend sqlite `
  --queue-sqlite-path data\scaling_runtime_queue.db `
  --queue-namespace distributed20 `
  --camera-count 20 `
  --duration-sec 1800
```

Terminal 2 (inference):
```powershell
.\venv_ai\Scripts\python.exe scripts\run_scaling_runtime_distributed.py `
  --role inference `
  --queue-backend sqlite `
  --queue-sqlite-path data\scaling_runtime_queue.db `
  --queue-namespace distributed20 `
  --inference-workers 8 `
  --inference-batch-size 4 `
  --inference-batch-max-wait-ms 20 `
  --dead-letter-backend sqlite `
  --dead-letter-sqlite-path data\scaling_dead_letters.db `
  --dead-letter-namespace distributed20 `
  --duration-sec 1800
```

Terminal 3 (writer):
```powershell
.\venv_ai\Scripts\python.exe scripts\run_scaling_runtime_distributed.py `
  --role writer `
  --queue-backend sqlite `
  --queue-sqlite-path data\scaling_runtime_queue.db `
  --queue-namespace distributed20 `
  --writer-workers 6 `
  --persist-target db `
  --dead-letter-backend sqlite `
  --dead-letter-sqlite-path data\scaling_dead_letters.db `
  --dead-letter-namespace distributed20 `
  --duration-sec 1800
```

Ce mode valide la separation inter-process et prepare la migration vers broker externe (Redis/Kafka).

## 10) Dead-letter observability (Sprint 8)

Le runtime distribue expose un stockage dead-letter optionnel:
- `--dead-letter-backend none|memory|sqlite`
- `--dead-letter-sqlite-path <path>`
- `--dead-letter-namespace <name>`

Le rapport JSON inclut:
- `final_snapshot.dead_letters.total`
- `final_snapshot.dead_letters.by_category`
- `final_snapshot.inference_worker.dead_lettered`
- `final_snapshot.event_writer_worker.dead_lettered`

Run de validation rapide (full node):

```powershell
.\venv_ai\Scripts\python.exe scripts\run_scaling_runtime_distributed.py `
  --role full `
  --queue-backend sqlite `
  --queue-sqlite-path data\scaling_runtime_queue.db `
  --queue-namespace sprint8 `
  --camera-count 20 `
  --sample-interval-ms 200 `
  --duration-sec 300 `
  --inference-workers 8 `
  --inference-batch-size 4 `
  --inference-batch-max-wait-ms 20 `
  --writer-workers 6 `
  --checkpoint-minutes 15,30,60 `
  --checkpoint-json logs\scaling_distributed_sprint8_checkpoints.json `
  --persist-target db `
  --dead-letter-backend sqlite `
  --dead-letter-sqlite-path data\scaling_dead_letters.db `
  --dead-letter-namespace sprint8 `
  --output-json logs\scaling_distributed_sprint8.json
```

Critere DoD Sprint 8:
- aucun crash runtime pendant le test
- dead-letter visible dans `final_snapshot` quand active
- categories dead-letter coherentes avec les fautes injectees

## 11) Baseline stable + checkpoints auto (Sprint 9)

Baseline par defaut integree dans les scripts runtime:
- `sample_interval_ms = 200`
- `inference_workers = 8`
- `inference_batch_size = 4`
- `writer_workers = 6`

Pour les runs longs distribues, le script `run_scaling_runtime_distributed.py` supporte:
- `--checkpoint-minutes 15,30,60`
- `--checkpoint-json <path>`
- `--live-status-json <path>`

Le rapport final inclut:
- `checkpoints[]` (queue depth, p95, infer avg, drops, CPU/RAM)
- `post_run_summary` avec alertes SLA/queue/drops et recommandations de tuning
