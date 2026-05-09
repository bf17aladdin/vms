from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vms.backend.services.scaling.scaling_runtime import (
    RuntimeThresholds,
    ScalingRuntime,
    SimulationProfile,
)
from vms.backend.services.scaling.vehicle_event_persistence_service import (
    SqlAlchemyVehicleEventPersistenceService,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run isolated scaling runtime simulation (ingestion -> inference -> writer).",
    )
    parser.add_argument("--camera-count", type=int, default=20)
    parser.add_argument("--duration-sec", type=int, default=30)
    parser.add_argument("--sample-interval-ms", type=int, default=200)
    parser.add_argument("--frame-queue-maxsize", type=int, default=2048)
    parser.add_argument("--result-queue-maxsize", type=int, default=2048)
    parser.add_argument("--queue-backend", choices=["memory", "sqlite"], default="memory")
    parser.add_argument("--queue-sqlite-path", type=str, default="data/scaling_runtime_queue.db")
    parser.add_argument("--queue-namespace", type=str, default="simulation")
    parser.add_argument("--inference-workers", type=int, default=8)
    parser.add_argument("--inference-batch-size", type=int, default=4)
    parser.add_argument("--inference-batch-max-wait-ms", type=float, default=0.0)
    parser.add_argument("--writer-workers", type=int, default=6)

    parser.add_argument("--p95-threshold-ms", type=float, default=3000.0)
    parser.add_argument("--queue-depth-threshold", type=int, default=1200)
    parser.add_argument("--persist-success-threshold-pct", type=float, default=99.0)

    parser.add_argument("--frame-read-ms-min", type=float, default=2.0)
    parser.add_argument("--frame-read-ms-max", type=float, default=8.0)
    parser.add_argument("--inference-ms-min", type=float, default=40.0)
    parser.add_argument("--inference-ms-max", type=float, default=120.0)
    parser.add_argument("--persist-ms-min", type=float, default=3.0)
    parser.add_argument("--persist-ms-max", type=float, default=18.0)
    parser.add_argument("--inference-success-ratio", type=float, default=1.0)
    parser.add_argument("--persist-success-ratio", type=float, default=1.0)
    parser.add_argument("--persist-target", choices=["memory", "db"], default="memory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    profile = SimulationProfile(
        frame_reader_latency_ms_min=args.frame_read_ms_min,
        frame_reader_latency_ms_max=args.frame_read_ms_max,
        inference_latency_ms_min=args.inference_ms_min,
        inference_latency_ms_max=args.inference_ms_max,
        persistence_latency_ms_min=args.persist_ms_min,
        persistence_latency_ms_max=args.persist_ms_max,
        inference_success_ratio=args.inference_success_ratio,
        persistence_success_ratio=args.persist_success_ratio,
    )
    thresholds = RuntimeThresholds(
        p95_end_to_end_ms_max=args.p95_threshold_ms,
        queue_depth_max=args.queue_depth_threshold,
        event_persist_success_min_pct=args.persist_success_threshold_pct,
    )

    persistence_service = None
    if args.persist_target == "db":
        persistence_service = SqlAlchemyVehicleEventPersistenceService()

    runtime = ScalingRuntime.build_simulated(
        camera_count=args.camera_count,
        sample_interval_ms=args.sample_interval_ms,
        frame_queue_maxsize=args.frame_queue_maxsize,
        result_queue_maxsize=args.result_queue_maxsize,
        queue_backend=args.queue_backend,
        queue_sqlite_path=args.queue_sqlite_path,
        queue_namespace=args.queue_namespace,
        inference_workers=args.inference_workers,
        inference_batch_size=args.inference_batch_size,
        inference_batch_max_wait_ms=args.inference_batch_max_wait_ms,
        writer_workers=args.writer_workers,
        profile=profile,
        persistence_service=persistence_service,
    )

    started_at = datetime.now(timezone.utc).isoformat()
    runtime.start()
    progress_samples: list[dict] = []
    try:
        for sec in range(max(1, args.duration_sec)):
            time.sleep(1)
            snap = runtime.snapshot()
            panel = snap.get("runtime_health_panel", {}) or {}
            panel_summary = panel.get("summary", {}) or {}
            progress_samples.append(
                {
                    "t_sec": sec + 1,
                    "frame_queue_size": snap["frame_queue"]["size"],
                    "frame_queue_high_watermark": snap["frame_queue"]["high_watermark"],
                    "result_queue_size": snap["result_queue"]["size"],
                    "inference_processed": snap["inference_worker"]["processed"],
                    "writer_processed": snap["event_writer_worker"]["processed"],
                    "persisted": snap.get("measured_persistence", {}).get("persisted", 0),
                    "persist_failed": snap.get("measured_persistence", {}).get("failed", 0),
                    "health_status": panel.get("status", "unknown"),
                    "frame_queue_util_pct": panel_summary.get("frame_queue_util_pct"),
                    "cpu_percent": panel_summary.get("cpu_percent"),
                    "inference_avg_latency_ms": panel_summary.get("inference_avg_latency_ms"),
                    "persist_success_pct": panel_summary.get("persist_success_pct"),
                }
            )
    finally:
        runtime.stop()

    ended_at = datetime.now(timezone.utc).isoformat()
    final_snapshot = runtime.snapshot()
    evaluation = runtime.evaluate(thresholds)
    report = {
        "phase": "scaling_runtime_simulation",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_sec": args.duration_sec,
        "config": {
            "camera_count": args.camera_count,
            "sample_interval_ms": args.sample_interval_ms,
            "frame_queue_maxsize": args.frame_queue_maxsize,
            "result_queue_maxsize": args.result_queue_maxsize,
            "queue_backend": args.queue_backend,
            "queue_sqlite_path": args.queue_sqlite_path if args.queue_backend == "sqlite" else None,
            "queue_namespace": args.queue_namespace if args.queue_backend == "sqlite" else None,
            "inference_workers": args.inference_workers,
            "inference_batch_size": args.inference_batch_size,
            "inference_batch_max_wait_ms": args.inference_batch_max_wait_ms,
            "writer_workers": args.writer_workers,
            "persist_target": args.persist_target,
            "profile": asdict(profile),
        },
        "thresholds": asdict(thresholds),
        "evaluation": evaluation,
        "final_snapshot": final_snapshot,
        "progress_samples": progress_samples,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
