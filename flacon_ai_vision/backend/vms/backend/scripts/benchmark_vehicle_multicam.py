from __future__ import annotations

import argparse
import statistics
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List

import requests


@dataclass
class CameraStats:
    camera_id: int
    total: int = 0
    ok: int = 0
    errors: int = 0
    latencies_ms: List[float] = field(default_factory=list)
    last_error: str = ""

    def record_ok(self, latency_ms: float) -> None:
        self.total += 1
        self.ok += 1
        self.latencies_ms.append(latency_ms)

    def record_error(self, latency_ms: float, message: str) -> None:
        self.total += 1
        self.errors += 1
        self.latencies_ms.append(latency_ms)
        self.last_error = message


def _parse_camera_ids(raw: str) -> List[int]:
    out: List[int] = []
    for chunk in raw.split(","):
        value = chunk.strip()
        if not value:
            continue
        out.append(int(value))
    if not out:
        raise ValueError("At least one camera id is required")
    return out


def _gpu_sample() -> str:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=4,
        )
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            return "GPU: no data"
        return "GPU: " + " | ".join(lines)
    except Exception:
        return "GPU: nvidia-smi not available"


def _camera_worker(
    camera_id: int,
    base_url: str,
    stop_event: threading.Event,
    stats: CameraStats,
    lock: threading.Lock,
    token: str | None,
    persist: bool,
    save_snapshot: bool,
) -> None:
    session = requests.Session()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    endpoint = f"{base_url}/vehicle/recognize/camera/{camera_id}"
    payload = {"persist": persist, "save_snapshot": save_snapshot}

    while not stop_event.is_set():
        started = time.perf_counter()
        try:
            response = session.post(endpoint, json=payload, headers=headers, timeout=8)
            latency_ms = (time.perf_counter() - started) * 1000.0
            if response.ok:
                with lock:
                    stats.record_ok(latency_ms)
            else:
                detail = ""
                try:
                    detail = str(response.json())
                except Exception:
                    detail = response.text[:180]
                with lock:
                    stats.record_error(latency_ms, f"HTTP {response.status_code}: {detail}")
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            with lock:
                stats.record_error(latency_ms, str(exc))


def _format_stats(stats: CameraStats) -> str:
    if not stats.latencies_ms:
        return f"camera={stats.camera_id} total=0 ok=0 err=0"

    latencies = stats.latencies_ms
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    return (
        f"camera={stats.camera_id} total={stats.total} ok={stats.ok} err={stats.errors} "
        f"avg_ms={statistics.mean(latencies):.1f} p95_ms={p95:.1f} max_ms={max(latencies):.1f}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark multi-camera vehicle recognition endpoint.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5003/api", help="Backend API base URL")
    parser.add_argument("--camera-ids", required=True, help="Comma-separated camera ids, e.g. 1,2,3")
    parser.add_argument("--duration", type=int, default=60, help="Benchmark duration in seconds")
    parser.add_argument("--token", default="", help="Bearer token")
    parser.add_argument("--persist", action="store_true", help="Persist events in DB during benchmark")
    parser.add_argument("--save-snapshot", action="store_true", help="Save snapshots during benchmark")
    parser.add_argument("--gpu-monitor", action="store_true", help="Print GPU usage every 5 seconds")
    args = parser.parse_args()

    camera_ids = _parse_camera_ids(args.camera_ids)
    stop_event = threading.Event()
    lock = threading.Lock()

    stats_map: Dict[int, CameraStats] = {camera_id: CameraStats(camera_id=camera_id) for camera_id in camera_ids}
    workers: List[threading.Thread] = []

    for camera_id in camera_ids:
        worker = threading.Thread(
            target=_camera_worker,
            kwargs={
                "camera_id": camera_id,
                "base_url": args.base_url.rstrip("/"),
                "stop_event": stop_event,
                "stats": stats_map[camera_id],
                "lock": lock,
                "token": args.token.strip() or None,
                "persist": bool(args.persist),
                "save_snapshot": bool(args.save_snapshot),
            },
            daemon=True,
        )
        workers.append(worker)
        worker.start()

    started = time.time()
    next_print = started + 5
    while time.time() - started < args.duration:
        time.sleep(0.5)
        if time.time() >= next_print:
            with lock:
                lines = [_format_stats(stats_map[cid]) for cid in camera_ids]
            print(f"[{int(time.time() - started)}s] " + " || ".join(lines))
            if args.gpu_monitor:
                print("  " + _gpu_sample())
            next_print += 5

    stop_event.set()
    for worker in workers:
        worker.join(timeout=2)

    print("\n=== Final Results ===")
    total_ok = 0
    total_err = 0
    total_req = 0
    total_latencies: List[float] = []

    with lock:
        for camera_id in camera_ids:
            stats = stats_map[camera_id]
            print(_format_stats(stats))
            if stats.last_error:
                print(f"  last_error={stats.last_error}")
            total_ok += stats.ok
            total_err += stats.errors
            total_req += stats.total
            total_latencies.extend(stats.latencies_ms)

    elapsed = max(1e-6, time.time() - started)
    print(
        f"global total={total_req} ok={total_ok} err={total_err} "
        f"throughput_rps={total_req / elapsed:.2f}"
    )
    if total_latencies:
        print(
            f"global avg_ms={statistics.mean(total_latencies):.1f} "
            f"max_ms={max(total_latencies):.1f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

