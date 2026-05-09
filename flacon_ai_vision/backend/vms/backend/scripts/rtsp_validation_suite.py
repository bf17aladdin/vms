#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from vms.backend.services.stream_service import StreamService


@dataclass
class ProbeResult:
    source: str
    total: int
    ok: int
    avg_latency_ms: float


def probe_stream(source: str, attempts: int, sleep_sec: float, camera_id: int) -> ProbeResult:
    latencies: list[float] = []
    ok = 0
    for _ in range(attempts):
        started = time.perf_counter()
        frame = StreamService.get_camera_frame(camera_id=camera_id, rtsp_url=source)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(elapsed_ms)
        if frame is not None:
            ok += 1
        time.sleep(max(0.0, sleep_sec))
    return ProbeResult(
        source=source,
        total=attempts,
        ok=ok,
        avg_latency_ms=round(statistics.mean(latencies), 2) if latencies else 0.0,
    )


def run_multi_mode(urls: list[str], attempts: int, sleep_sec: float) -> dict:
    rows = [probe_stream(src, attempts=attempts, sleep_sec=sleep_sec, camera_id=i + 1) for i, src in enumerate(urls)]
    return {
        "mode": "multi",
        "streams": [
            {
                "source": row.source,
                "ok_frames": row.ok,
                "total_frames": row.total,
                "success_rate": round((row.ok / row.total) if row.total else 0.0, 4),
                "avg_latency_ms": row.avg_latency_ms,
            }
            for row in rows
        ],
    }


def run_resilience_mode(url: str, attempts: int, sleep_sec: float) -> dict:
    failures = 0
    max_consecutive_failures = 0
    recovered = 0
    previous_ok: Optional[bool] = None
    latencies: list[float] = []
    consecutive_failures = 0

    for i in range(attempts):
        started = time.perf_counter()
        frame = StreamService.get_camera_frame(camera_id=1, rtsp_url=url)
        latency_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(latency_ms)
        ok = frame is not None

        if not ok:
            failures += 1
            consecutive_failures += 1
            max_consecutive_failures = max(max_consecutive_failures, consecutive_failures)
        else:
            consecutive_failures = 0
        if previous_ok is False and ok:
            recovered += 1
        previous_ok = ok
        time.sleep(max(0.0, sleep_sec))

    return {
        "mode": "resilience",
        "source": url,
        "attempts": attempts,
        "failures": failures,
        "recoveries": recovered,
        "max_consecutive_failures": max_consecutive_failures,
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
    }


def run_latency_mode(base_url: str, camera_id: int, token: str, attempts: int) -> dict:
    latencies: list[float] = []
    statuses: list[int] = []

    body = json.dumps({}).encode("utf-8")
    url = f"{base_url.rstrip('/')}/api/vehicle/recognize/camera/{camera_id}"
    for _ in range(attempts):
        req = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                statuses.append(int(resp.status))
        except urllib.error.HTTPError as exc:
            statuses.append(int(exc.code))
        except Exception:
            statuses.append(0)
        latencies.append((time.perf_counter() - started) * 1000.0)

    return {
        "mode": "latency",
        "camera_id": camera_id,
        "attempts": attempts,
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else 0.0,
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 2) if latencies else 0.0,
        "statuses": statuses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="RTSP and recognition validation suite")
    parser.add_argument("--mode", choices=["multi", "resilience", "latency"], required=True)
    parser.add_argument("--urls", nargs="*", default=[])
    parser.add_argument("--url", default="")
    parser.add_argument("--attempts", type=int, default=8)
    parser.add_argument("--sleep-sec", type=float, default=0.8)
    parser.add_argument("--base-url", default="http://127.0.0.1:5003")
    parser.add_argument("--camera-id", type=int, default=1)
    parser.add_argument("--token", default="")
    args = parser.parse_args()

    if args.mode == "multi":
        if not args.urls:
            raise SystemExit("--urls is required for mode=multi")
        payload = run_multi_mode(args.urls, attempts=args.attempts, sleep_sec=args.sleep_sec)
    elif args.mode == "resilience":
        if not args.url:
            raise SystemExit("--url is required for mode=resilience")
        payload = run_resilience_mode(args.url, attempts=args.attempts, sleep_sec=args.sleep_sec)
    else:
        if not args.token:
            raise SystemExit("--token is required for mode=latency")
        payload = run_latency_mode(
            base_url=args.base_url,
            camera_id=args.camera_id,
            token=args.token,
            attempts=args.attempts,
        )

    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
