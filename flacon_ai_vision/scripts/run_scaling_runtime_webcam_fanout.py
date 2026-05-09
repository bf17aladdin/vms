from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import cv2  # type: ignore
except Exception as exc:  # pragma: no cover - runtime dependency
    raise RuntimeError("OpenCV is required for webcam fanout test") from exc

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


class SharedWebcamFanoutReader:
    """Single physical webcam source reused by multiple logical camera IDs."""

    def __init__(self, device_index: int = 0):
        self.device_index = int(device_index)
        self._lock = threading.Lock()
        self._capture = None
        self.read_attempts = 0
        self.read_success = 0
        self.read_failures = 0

        # Prefer DirectShow on Windows for stability.
        self._capture = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if self._capture is None or not self._capture.isOpened():
            self._capture = cv2.VideoCapture(self.device_index)

        if self._capture is None or not self._capture.isOpened():
            raise RuntimeError(f"Unable to open webcam index {self.device_index}")

        ok, frame = self._capture.read()
        if not ok or frame is None:
            self._capture.release()
            raise RuntimeError(f"Webcam preflight failed at index {self.device_index}")

    def __call__(self, camera_id: int, source: str):
        with self._lock:
            self.read_attempts += 1
            if self._capture is None or not self._capture.isOpened():
                self.read_failures += 1
                return None
            ok, frame = self._capture.read()
            if not ok or frame is None:
                self.read_failures += 1
                return None
            self.read_success += 1
            return frame.copy()

    def close(self) -> None:
        with self._lock:
            if self._capture is not None:
                try:
                    self._capture.release()
                except Exception:
                    pass
                self._capture = None

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "read_attempts": int(self.read_attempts),
                "read_success": int(self.read_success),
                "read_failures": int(self.read_failures),
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run scaling runtime with 1 physical webcam fan-out to N logical streams "
            "(fallback when RTSP replay stack is unavailable)."
        ),
    )
    parser.add_argument("--camera-count", type=int, default=20)
    parser.add_argument("--camera-start-id", type=int, default=1)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--duration-sec", type=int, default=120)
    parser.add_argument("--sample-interval-ms", type=int, default=200)
    parser.add_argument("--frame-queue-maxsize", type=int, default=4096)
    parser.add_argument("--result-queue-maxsize", type=int, default=4096)
    parser.add_argument("--queue-backend", choices=["memory", "sqlite"], default="memory")
    parser.add_argument("--queue-sqlite-path", type=str, default="data/scaling_runtime_queue.db")
    parser.add_argument("--queue-namespace", type=str, default="webcam_fanout")
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
    parser.add_argument("--output-json", type=str, default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    thresholds = RuntimeThresholds(
        p95_end_to_end_ms_max=args.p95_threshold_ms,
        queue_depth_max=args.queue_depth_threshold,
        event_persist_success_min_pct=args.persist_success_threshold_pct,
    )

    reader = SharedWebcamFanoutReader(device_index=args.device_index)

    backend = str(args.queue_backend or "memory").strip().lower()
    queue_meta: dict[str, Any]
    if backend == "sqlite":
        sqlite_path = str(args.queue_sqlite_path or "data/scaling_runtime_queue.db")
        namespace = str(args.queue_namespace or "webcam_fanout").strip() or "webcam_fanout"
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
        frame_reader=reader,
        idle_sleep_sec=0.001,
    )
    for idx in range(max(1, int(args.camera_count))):
        camera_id = int(args.camera_start_id) + idx
        metadata: dict[str, Any] = {"direction": str(args.direction).upper()}
        if args.zone_id is not None:
            metadata["zone_id"] = int(args.zone_id)
        if args.site_id is not None:
            metadata["site_id"] = int(args.site_id)

        ingestion.register_camera(
            CameraIngestionConfig(
                camera_id=camera_id,
                source=f"webcam://{args.device_index}",
                enabled=True,
                sample_interval_ms=int(args.sample_interval_ms),
                metadata=metadata,
            )
        )

    inference_service = VehicleInferenceService(persist=False, save_snapshot=False)
    inference_worker = VehicleInferenceWorker(
        input_queue=frame_queue,
        output_queue=result_queue,
        inference_fn=inference_service.infer,
        inference_batch_fn=inference_service.infer_batch,
        workers=int(args.inference_workers),
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
        workers=int(args.writer_workers),
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

    progress_samples: list[dict[str, Any]] = []
    progress_interval = max(1, int(args.progress_interval_sec))
    started_at = datetime.now(timezone.utc).isoformat()
    runtime.start()
    try:
        for sec in range(max(1, int(args.duration_sec))):
            time.sleep(1)
            if (sec + 1) % progress_interval == 0 or sec == 0:
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
        reader.close()

    ended_at = datetime.now(timezone.utc).isoformat()
    final_snapshot = runtime.snapshot()
    evaluation = runtime.evaluate(thresholds)

    report = {
        "phase": "scaling_runtime_webcam_fanout",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_sec": int(args.duration_sec),
        "config": {
            "camera_count": int(args.camera_count),
            "camera_start_id": int(args.camera_start_id),
            "device_index": int(args.device_index),
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
        "evaluation": evaluation,
        "final_snapshot": final_snapshot,
        "reader_metrics": reader.snapshot(),
        "progress_samples": progress_samples,
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
