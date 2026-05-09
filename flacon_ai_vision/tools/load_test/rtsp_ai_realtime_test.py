"""Test de détection IA en temps réel à partir de flux RTSP.

Usage:
    python rtsp_ai_realtime_test.py --base-url rtsp://127.0.0.1:8554 --count 5 --duration 1800 --report-interval 300

Ce script :
- se connecte aux flux RTSP (cam1..camN)
- récupère les frames via OpenCV
- exécute la pipeline AI (motion + object detection) via FrameProcessor
- imprime des statistiques toutes les X secondes
- écrit un CSV de suivi

Il est conçu pour être lancé sur un ou plusieurs serveurs (cluster) en parallèle ;
chaque instance peut pointer vers un sous-ensemble de caméras.

Prérequis :
- python (venv activé si nécessaire)
- OpenCV (cv2)
- les dépendances du backend (yolo, torch, etc.)

"""

import argparse
import asyncio
import csv
import time
import sys
from datetime import datetime
from pathlib import Path

try:
    import cv2
except ImportError as e:
    raise SystemExit("OpenCV (cv2) est requis pour ce script. Installez-le avec `pip install opencv-python`.")

try:
    import numpy as np
except ImportError as e:
    raise SystemExit("numpy est requis pour ce script. Installez-le avec `pip install numpy`.")

# Assure l'import du backend (vms) en ajoutant le bon dossier au sys.path.
# Ce script est placé dans tools/load_test, donc on remonte vers falcon_ai_vision-platform/backend
ROOT = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(ROOT))

from vms.backend.services.frame_processor import FrameProcessor


class CameraStats:
    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url
        self.frames = 0
        self.motion_events = 0
        self.objects = 0
        self.errors = 0
        self.latencies = []
        self.last_report = time.time()

    def add_result(self, result: dict, latency_ms: float):
        self.frames += 1
        if result.get("motion", {}).get("detected"):
            self.motion_events += 1
        self.objects += len(result.get("objects") or [])
        self.latencies.append(latency_ms)

    def add_error(self):
        self.errors += 1

    def summary(self, interval_s: int):
        avg_latency = float(np.mean(self.latencies)) if self.latencies else 0.0
        fps = len(self.latencies) / interval_s if interval_s > 0 else 0
        return {
            "camera": self.name,
            "frames": self.frames,
            "motion_events": self.motion_events,
            "objects": self.objects,
            "errors": self.errors,
            "avg_latency_ms": round(avg_latency, 1),
            "fps": round(fps, 2)
        }


async def camera_loop(camera_id: int, url: str, duration_s: int, report_interval_s: int, output_csv_base: Path):
    name = f"cam{camera_id}"
    stats = CameraStats(name, url)
    fp = FrameProcessor(camera_id=camera_id, camera_name=name)

    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print(f"[ERROR] Impossible d'ouvrir {url}")
        return stats

    start = time.time()
    next_report = start + report_interval_s

    # Fichier CSV par caméra pour éviter des écritures concurrentes
    output_csv = output_csv_base.with_name(f"{output_csv_base.stem}_{name}.csv")
    with output_csv.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["timestamp", "camera", "frames", "motion_events", "objects", "errors", "avg_latency_ms", "fps"])

        while time.time() - start < duration_s:
            ret, frame = await asyncio.to_thread(cap.read)
            if not ret or frame is None:
                stats.add_error()
                await asyncio.sleep(0.5)
                continue

            t0 = time.time()
            try:
                result = await fp.process_frame_async(frame, db=None)
            except Exception:
                stats.add_error()
                await asyncio.sleep(0.1)
                continue

            latency_ms = (time.time() - t0) * 1000
            stats.add_result(result, latency_ms)

            # Report at interval
            if time.time() >= next_report:
                summary = stats.summary(report_interval_s)
                summary_row = [datetime.utcnow().isoformat(), summary["camera"], summary["frames"], summary["motion_events"], summary["objects"], summary["errors"], summary["avg_latency_ms"], summary["fps"]]
                writer.writerow(summary_row)
                writer.flush()

                print(f"[{datetime.utcnow().isoformat()}] {name} • frames={summary['frames']} fps={summary['fps']} avg_latency={summary['avg_latency_ms']}ms motions={summary['motion_events']} objects={summary['objects']} errors={summary['errors']}")

                stats = CameraStats(name, url)  # reset counters for next interval
                next_report += report_interval_s

    cap.release()
    return stats


async def main(args):
    # Build list of RTSP URLs
    urls = []
    if args.url_list:
        urls = [u.strip() for u in args.url_list.split(",") if u.strip()]
    else:
        # base + cam1..camN
        for i in range(1, args.count + 1):
            urls.append(f"{args.base_url}/cam{i}")

    out_csv_base = Path(args.output_csv)
    out_csv_base.parent.mkdir(parents=True, exist_ok=True)

    tasks = []
    for i, url in enumerate(urls, start=1):
        tasks.append(camera_loop(i, url, args.duration, args.report_interval, out_csv_base))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test IA détection temps réel sur flux RTSP")
    parser.add_argument("--base-url", type=str, default="rtsp://127.0.0.1:8554", help="Base RTSP URL (ajoute /camX)")
    parser.add_argument("--count", type=int, default=5, help="Nombre de flux camX à tester")
    parser.add_argument("--duration", type=int, default=1800, help="Durée totale du test en secondes")
    parser.add_argument("--report-interval", type=int, default=300, help="Intervalle de reporting en secondes")
    parser.add_argument("--output-csv", type=str, default="tools/load_test/rtsp_ai_realtime_results.csv", help="Fichier CSV de sortie")
    parser.add_argument("--url-list", type=str, default=None, help="Liste de URLs séparées par des virgules (remplace --base-url/--count)")
    args = parser.parse_args()

    asyncio.run(main(args))
