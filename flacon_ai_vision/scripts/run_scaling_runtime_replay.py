from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vms.backend.services.scaling.frame_task_queue import (
    BoundedTaskQueue,
    FrameTask,
    InferenceResultTask,
)
from vms.backend.services.scaling.multi_camera_ingestion_service import (
    CameraIngestionConfig,
    MultiCameraIngestionService,
)
from vms.backend.services.scaling.scaling_runtime import (
    InMemoryMeasuredPersistenceService,
    MeasuredPersistenceAdapter,
    RuntimeThresholds,
    ScalingRuntime,
)
from vms.backend.services.scaling.adaptive_rate_controller import (
    AdaptiveRateController,
    AdaptiveRateControllerConfig,
)
from vms.backend.services.scaling.sqlite_task_queue import SqliteTaskQueue
from vms.backend.services.scaling.vehicle_event_persistence_service import (
    SqlAlchemyVehicleEventPersistenceService,
)
from vms.backend.services.scaling.vehicle_event_writer_worker import VehicleEventWriterWorker
from vms.backend.services.scaling.vehicle_inference_service import VehicleInferenceService
from vms.backend.services.scaling.vehicle_inference_worker import VehicleInferenceWorker
from vms.backend.services.stream_service import StreamService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run real scaling runtime against RTSP replay streams "
            "(ingestion -> inference -> async DB persistence)."
        ),
    )
    parser.add_argument("--camera-count", type=int, default=20)
    parser.add_argument("--camera-start-id", type=int, default=1)
    parser.add_argument(
        "--rtsp-url-template",
        type=str,
        default="rtsp://127.0.0.1:8554/cam{camera_id}",
        help="Template used to build stream URLs. Supports {camera_id}.",
    )
    parser.add_argument("--duration-sec", type=int, default=1800)
    parser.add_argument("--sample-interval-ms", type=int, default=200)
    parser.add_argument("--frame-queue-maxsize", type=int, default=4096)
    parser.add_argument("--result-queue-maxsize", type=int, default=4096)
    parser.add_argument("--queue-backend", choices=["memory", "sqlite"], default="memory")
    parser.add_argument("--queue-sqlite-path", type=str, default="data/scaling_runtime_queue.db")
    parser.add_argument("--queue-namespace", type=str, default="replay")
    parser.add_argument("--inference-workers", type=int, default=8)
    parser.add_argument("--inference-batch-size", type=int, default=4)
    parser.add_argument("--inference-batch-max-wait-ms", type=float, default=0.0)
    parser.add_argument("--writer-workers", type=int, default=6)
    parser.add_argument("--direction", type=str, default="IN")
    parser.add_argument("--zone-id", type=int, default=None)
    parser.add_argument("--site-id", type=int, default=None)
    parser.add_argument("--persist-target", choices=["db", "memory"], default="db")

    parser.add_argument("--p95-threshold-ms", type=float, default=3000.0)
    parser.add_argument("--queue-depth-threshold", type=int, default=1200)
    parser.add_argument("--persist-success-threshold-pct", type=float, default=99.0)
    parser.add_argument(
        "--preflight-ok-ratio-min",
        type=float,
        default=0.90,
        help="Minimum ratio of healthy sources required for GO (0.0-1.0).",
    )
    parser.add_argument("--progress-interval-sec", type=int, default=5)
    parser.add_argument("--enable-adaptive-rate", action="store_true")
    parser.add_argument("--adaptive-poll-interval-sec", type=float, default=2.0)
    parser.add_argument("--adaptive-min-sample-interval-ms", type=int, default=120)
    parser.add_argument("--adaptive-max-sample-interval-ms", type=int, default=500)
    parser.add_argument("--adaptive-adjust-step-ms", type=int, default=40)
    parser.add_argument("--adaptive-queue-high-ratio", type=float, default=0.35)
    parser.add_argument("--adaptive-queue-low-ratio", type=float, default=0.05)
    parser.add_argument("--adaptive-cpu-high-pct", type=float, default=85.0)
    parser.add_argument("--adaptive-cpu-low-pct", type=float, default=55.0)
    parser.add_argument("--disable-preflight", action="store_true")
    parser.add_argument("--output-json", type=str, default="")
    return parser.parse_args()


def _build_camera_sources(
    *,
    camera_count: int,
    camera_start_id: int,
    rtsp_url_template: str,
) -> list[tuple[int, str]]:
    items: list[tuple[int, str]] = []
    for idx in range(max(1, int(camera_count))):
        camera_id = int(camera_start_id) + idx
        source = rtsp_url_template.format(camera_id=camera_id)
        items.append((camera_id, source))
    return items


def _preflight_sources(sources: list[tuple[int, str]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    ok_count = 0

    for camera_id, source in sources:
        frame = StreamService.get_camera_frame(camera_id=camera_id, rtsp_url=source)
        ok = frame is not None
        if ok:
            ok_count += 1
        checks.append(
            {
                "camera_id": camera_id,
                "source": source,
                "ok": ok,
            }
        )

    return {
        "ok_count": ok_count,
        "total_count": len(sources),
        "checks": checks,
    }


def _build_runtime(
    args: argparse.Namespace,
    sources: list[tuple[int, str]],
) -> tuple[ScalingRuntime, VehicleInferenceService, AdaptiveRateControllerConfig | None]:
    backend = str(args.queue_backend or "memory").strip().lower()
    queue_meta: dict[str, Any]
    if backend == "sqlite":
        sqlite_path = str(args.queue_sqlite_path or "data/scaling_runtime_queue.db")
        namespace = str(args.queue_namespace or "replay").strip() or "replay"
        frame_queue: BoundedTaskQueue[FrameTask] = SqliteTaskQueue(  # type: ignore[assignment]
            db_path=sqlite_path,
            topic=f"{namespace}_frame",
            maxsize=args.frame_queue_maxsize,
            purge_on_start=True,
        )
        result_queue: BoundedTaskQueue[InferenceResultTask] = SqliteTaskQueue(  # type: ignore[assignment]
            db_path=sqlite_path,
            topic=f"{namespace}_result",
            maxsize=args.result_queue_maxsize,
            purge_on_start=True,
        )
        queue_meta = {
            "backend": "sqlite",
            "sqlite_path": sqlite_path,
            "namespace": namespace,
        }
    else:
        frame_queue = BoundedTaskQueue(maxsize=args.frame_queue_maxsize)
        result_queue = BoundedTaskQueue(maxsize=args.result_queue_maxsize)
        queue_meta = {"backend": "memory"}

    ingestion = MultiCameraIngestionService(
        frame_queue=frame_queue,
        idle_sleep_sec=0.001,
    )

    for camera_id, source in sources:
        metadata: dict[str, Any] = {"direction": str(args.direction).upper()}
        if args.zone_id is not None:
            metadata["zone_id"] = int(args.zone_id)
        if args.site_id is not None:
            metadata["site_id"] = int(args.site_id)

        ingestion.register_camera(
            CameraIngestionConfig(
                camera_id=camera_id,
                source=source,
                enabled=True,
                sample_interval_ms=args.sample_interval_ms,
                metadata=metadata,
            )
        )

    inference_service = VehicleInferenceService(persist=False, save_snapshot=False)
    inference_worker = VehicleInferenceWorker(
        input_queue=frame_queue,
        output_queue=result_queue,
        inference_fn=inference_service.infer,
        inference_batch_fn=inference_service.infer_batch,
        workers=args.inference_workers,
        poll_timeout_sec=0.1,
        batch_size=max(1, int(args.inference_batch_size)),
        batch_max_wait_ms=max(0.0, float(args.inference_batch_max_wait_ms)),
    )

    if args.persist_target == "db":
        persistence = MeasuredPersistenceAdapter(SqlAlchemyVehicleEventPersistenceService())
    else:
        persistence = InMemoryMeasuredPersistenceService(
            latency_ms_min=3.0,
            latency_ms_max=18.0,
            success_ratio=1.0,
        )

    event_writer_worker = VehicleEventWriterWorker(
        input_queue=result_queue,
        persistence_service=persistence,
        workers=args.writer_workers,
        poll_timeout_sec=0.1,
        max_retries=1,
        retry_backoff_sec=0.01,
    )

    adaptive_config: AdaptiveRateControllerConfig | None = None
    adaptive_controller = None
    if args.enable_adaptive_rate:
        adaptive_config = AdaptiveRateControllerConfig(
            enabled=True,
            poll_interval_sec=float(args.adaptive_poll_interval_sec),
            min_sample_interval_ms=max(10, int(args.adaptive_min_sample_interval_ms)),
            max_sample_interval_ms=max(
                int(args.adaptive_min_sample_interval_ms),
                int(args.adaptive_max_sample_interval_ms),
            ),
            adjust_step_ms=max(1, int(args.adaptive_adjust_step_ms)),
            queue_high_ratio=max(0.0, min(1.0, float(args.adaptive_queue_high_ratio))),
            queue_low_ratio=max(0.0, min(1.0, float(args.adaptive_queue_low_ratio))),
            cpu_high_pct=max(1.0, min(100.0, float(args.adaptive_cpu_high_pct))),
            cpu_low_pct=max(1.0, min(100.0, float(args.adaptive_cpu_low_pct))),
        )
        adaptive_controller = AdaptiveRateController(
            ingestion_service=ingestion,
            frame_queue=frame_queue,
            config=adaptive_config,
        )

    runtime = ScalingRuntime(
        ingestion_service=ingestion,
        inference_worker=inference_worker,
        event_writer_worker=event_writer_worker,
        frame_queue=frame_queue,
        result_queue=result_queue,
        measured_persistence=persistence,
        adaptive_rate_controller=adaptive_controller,
        queue_backend=queue_meta["backend"],
        queue_metadata=queue_meta,
    )
    return runtime, inference_service, adaptive_config


def main() -> None:
    args = parse_args()
    thresholds = RuntimeThresholds(
        p95_end_to_end_ms_max=args.p95_threshold_ms,
        queue_depth_max=args.queue_depth_threshold,
        event_persist_success_min_pct=args.persist_success_threshold_pct,
        preflight_ok_ratio_min=args.preflight_ok_ratio_min,
    )

    sources = _build_camera_sources(
        camera_count=args.camera_count,
        camera_start_id=args.camera_start_id,
        rtsp_url_template=args.rtsp_url_template,
    )
    preflight = None
    preflight_ok_ratio = None
    if not args.disable_preflight:
        preflight = _preflight_sources(sources)
        total = int(preflight.get("total_count", 0))
        if total > 0:
            ok_count = int(preflight.get("ok_count", 0))
            preflight_ok_ratio = float(ok_count / total)
            preflight["ok_ratio"] = round(preflight_ok_ratio, 3)

    runtime, inference_service, adaptive_config = _build_runtime(args, sources)

    started_at = datetime.now(timezone.utc).isoformat()
    progress_samples: list[dict[str, Any]] = []
    progress_interval_sec = max(1, int(args.progress_interval_sec))

    runtime.start()
    try:
        for sec in range(max(1, int(args.duration_sec))):
            time.sleep(1)
            if (sec + 1) % progress_interval_sec == 0 or sec == 0:
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
        inference_service.close_all()

    ended_at = datetime.now(timezone.utc).isoformat()
    final_snapshot = runtime.snapshot()
    evaluation = runtime.evaluate(thresholds, preflight_ok_ratio=preflight_ok_ratio)

    report = {
        "phase": "scaling_runtime_replay",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_sec": int(args.duration_sec),
        "config": {
            "camera_count": int(args.camera_count),
            "camera_start_id": int(args.camera_start_id),
            "rtsp_url_template": str(args.rtsp_url_template),
            "sample_interval_ms": int(args.sample_interval_ms),
            "frame_queue_maxsize": int(args.frame_queue_maxsize),
            "result_queue_maxsize": int(args.result_queue_maxsize),
            "queue_backend": str(args.queue_backend),
            "queue_sqlite_path": str(args.queue_sqlite_path) if str(args.queue_backend) == "sqlite" else None,
            "queue_namespace": str(args.queue_namespace) if str(args.queue_backend) == "sqlite" else None,
            "inference_workers": int(args.inference_workers),
            "inference_batch_size": int(args.inference_batch_size),
            "inference_batch_max_wait_ms": float(args.inference_batch_max_wait_ms),
            "writer_workers": int(args.writer_workers),
            "direction": str(args.direction).upper(),
            "zone_id": args.zone_id,
            "site_id": args.site_id,
            "persist_target": str(args.persist_target),
            "adaptive_rate": asdict(adaptive_config)
            if adaptive_config is not None
            else {"enabled": False},
        },
        "thresholds": asdict(thresholds),
        "preflight": preflight,
        "evaluation": evaluation,
        "final_snapshot": final_snapshot,
        "progress_samples": progress_samples,
        "camera_sources": [{"camera_id": cam, "source": src} for cam, src in sources],
    }

    payload = json.dumps(report, indent=2)
    print(payload)

    output_json = str(args.output_json or "").strip()
    if output_json:
        path = Path(output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
