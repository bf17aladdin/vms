from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from .adaptive_rate_controller import AdaptiveRateController, AdaptiveRateControllerConfig
from .frame_task_queue import BoundedTaskQueue, FrameTask, InferenceResultTask
from .multi_camera_ingestion_service import CameraIngestionConfig, MultiCameraIngestionService
from .sqlite_task_queue import SqliteTaskQueue
from .vehicle_event_persistence_service import VehicleEventPersistenceService
from .vehicle_event_writer_worker import VehicleEventWriterWorker
from .vehicle_inference_worker import VehicleInferenceWorker

try:
    import psutil  # type: ignore

    _HAS_PSUTIL = True
except Exception:
    psutil = None
    _HAS_PSUTIL = False


def _parse_iso_to_epoch(value: str) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return None


def _pct(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    idx = int((len(sorted_values) - 1) * max(0.0, min(1.0, percentile)))
    return float(sorted_values[idx])


@dataclass(slots=True)
class RuntimeThresholds:
    p95_end_to_end_ms_max: float = 3000.0
    queue_depth_max: int = 400
    queue_overflow_max: int = 0
    event_persist_success_min_pct: float = 99.0
    preflight_ok_ratio_min: float = 0.9


@dataclass(slots=True)
class SimulationProfile:
    frame_reader_latency_ms_min: float = 2.0
    frame_reader_latency_ms_max: float = 8.0
    inference_latency_ms_min: float = 40.0
    inference_latency_ms_max: float = 120.0
    persistence_latency_ms_min: float = 3.0
    persistence_latency_ms_max: float = 18.0
    inference_success_ratio: float = 1.0
    persistence_success_ratio: float = 1.0


@dataclass(slots=True)
class RuntimeHealthThresholds:
    queue_util_warn: float = 0.75
    queue_util_critical: float = 0.95
    queue_drop_rate_warn_pct: float = 1.0
    persist_success_warn_pct: float = 99.0
    persist_success_critical_pct: float = 95.0
    cpu_warn_pct: float = 85.0
    cpu_critical_pct: float = 95.0


class InMemoryMeasuredPersistenceService(VehicleEventPersistenceService):
    """
    Simulation persistence service.

    It does not write to DB, but tracks latency and success rates to validate
    scaling behavior before real integration.
    """

    def __init__(
        self,
        *,
        latency_ms_min: float = 3.0,
        latency_ms_max: float = 18.0,
        success_ratio: float = 1.0,
    ):
        self.latency_ms_min = max(0.0, float(latency_ms_min))
        self.latency_ms_max = max(self.latency_ms_min, float(latency_ms_max))
        self.success_ratio = max(0.0, min(1.0, float(success_ratio)))
        self.persisted = 0
        self.failed = 0
        self._next_id = 1
        self.ingest_to_infer_ms: list[float] = []
        self.infer_to_persist_ms: list[float] = []
        self.end_to_end_ms: list[float] = []

    def persist(self, result: InferenceResultTask) -> Optional[int]:
        sleep_ms = random.uniform(self.latency_ms_min, self.latency_ms_max)
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

        if random.random() > self.success_ratio:
            self.failed += 1
            raise RuntimeError("simulated_persist_failure")

        now_epoch = datetime.now(timezone.utc).timestamp()
        captured_epoch = _parse_iso_to_epoch(result.captured_at)
        produced_epoch = _parse_iso_to_epoch(result.produced_at)
        if captured_epoch is not None and produced_epoch is not None and produced_epoch >= captured_epoch:
            self.ingest_to_infer_ms.append((produced_epoch - captured_epoch) * 1000.0)
        if produced_epoch is not None and now_epoch >= produced_epoch:
            self.infer_to_persist_ms.append((now_epoch - produced_epoch) * 1000.0)
        if captured_epoch is not None and now_epoch >= captured_epoch:
            self.end_to_end_ms.append((now_epoch - captured_epoch) * 1000.0)

        event_id = self._next_id
        self._next_id += 1
        self.persisted += 1
        return event_id

    def metrics(self) -> dict[str, Any]:
        total_attempts = self.persisted + self.failed
        success_pct = (100.0 * self.persisted / total_attempts) if total_attempts > 0 else 0.0
        return {
            "persisted": self.persisted,
            "failed": self.failed,
            "success_pct": round(success_pct, 3),
            "latency_ms": {
                "ingest_to_infer_avg": round(sum(self.ingest_to_infer_ms) / len(self.ingest_to_infer_ms), 3)
                if self.ingest_to_infer_ms
                else 0.0,
                "ingest_to_infer_p95": round(_pct(self.ingest_to_infer_ms, 0.95), 3),
                "infer_to_persist_avg": round(sum(self.infer_to_persist_ms) / len(self.infer_to_persist_ms), 3)
                if self.infer_to_persist_ms
                else 0.0,
                "infer_to_persist_p95": round(_pct(self.infer_to_persist_ms, 0.95), 3),
                "end_to_end_avg": round(sum(self.end_to_end_ms) / len(self.end_to_end_ms), 3)
                if self.end_to_end_ms
                else 0.0,
                "end_to_end_p95": round(_pct(self.end_to_end_ms, 0.95), 3),
            },
        }


class MeasuredPersistenceAdapter(VehicleEventPersistenceService):
    """
    Metrics wrapper around any persistence service (including real DB service).
    """

    def __init__(self, inner: VehicleEventPersistenceService):
        self.inner = inner
        self.persisted = 0
        self.failed = 0
        self.ingest_to_infer_ms: list[float] = []
        self.infer_to_persist_ms: list[float] = []
        self.end_to_end_ms: list[float] = []

    def persist(self, result: InferenceResultTask) -> Optional[int]:
        now_before = datetime.now(timezone.utc).timestamp()
        captured_epoch = _parse_iso_to_epoch(result.captured_at)
        produced_epoch = _parse_iso_to_epoch(result.produced_at)
        try:
            event_id = self.inner.persist(result)
        except Exception:
            self.failed += 1
            raise

        now_after = datetime.now(timezone.utc).timestamp()
        if captured_epoch is not None and produced_epoch is not None and produced_epoch >= captured_epoch:
            self.ingest_to_infer_ms.append((produced_epoch - captured_epoch) * 1000.0)
        if produced_epoch is not None and now_after >= produced_epoch:
            self.infer_to_persist_ms.append((now_after - produced_epoch) * 1000.0)
        if captured_epoch is not None and now_after >= captured_epoch:
            self.end_to_end_ms.append((now_after - captured_epoch) * 1000.0)

        self.persisted += 1 if event_id is not None else 0
        return event_id

    def metrics(self) -> dict[str, Any]:
        total_attempts = self.persisted + self.failed
        success_pct = (100.0 * self.persisted / total_attempts) if total_attempts > 0 else 0.0
        return {
            "persisted": self.persisted,
            "failed": self.failed,
            "success_pct": round(success_pct, 3),
            "latency_ms": {
                "ingest_to_infer_avg": round(sum(self.ingest_to_infer_ms) / len(self.ingest_to_infer_ms), 3)
                if self.ingest_to_infer_ms
                else 0.0,
                "ingest_to_infer_p95": round(_pct(self.ingest_to_infer_ms, 0.95), 3),
                "infer_to_persist_avg": round(sum(self.infer_to_persist_ms) / len(self.infer_to_persist_ms), 3)
                if self.infer_to_persist_ms
                else 0.0,
                "infer_to_persist_p95": round(_pct(self.infer_to_persist_ms, 0.95), 3),
                "end_to_end_avg": round(sum(self.end_to_end_ms) / len(self.end_to_end_ms), 3)
                if self.end_to_end_ms
                else 0.0,
                "end_to_end_p95": round(_pct(self.end_to_end_ms, 0.95), 3),
            },
        }


class SimulatedInferenceService:
    def __init__(
        self,
        *,
        latency_ms_min: float = 40.0,
        latency_ms_max: float = 120.0,
        success_ratio: float = 1.0,
    ):
        self.latency_ms_min = max(0.0, float(latency_ms_min))
        self.latency_ms_max = max(self.latency_ms_min, float(latency_ms_max))
        self.success_ratio = max(0.0, min(1.0, float(success_ratio)))

    def infer(self, task: FrameTask) -> dict[str, Any]:
        sleep_ms = random.uniform(self.latency_ms_min, self.latency_ms_max)
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

        return self._build_payload(task)

    def infer_batch(self, tasks: list[FrameTask]) -> list[dict[str, Any]]:
        if not tasks:
            return []

        # Simulate batching efficiency: one combined latency instead of one latency per frame.
        base_latency = random.uniform(self.latency_ms_min, self.latency_ms_max)
        factor = max(1.0, float(len(tasks)) * 0.6)
        sleep_ms = base_latency * factor
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

        return [self._build_payload(task) for task in tasks]

    def _build_payload(self, task: FrameTask) -> dict[str, Any]:
        success = random.random() <= self.success_ratio
        if not success:
            return {"success": False, "message": "simulated_inference_failure", "camera_id": task.camera_id}

        # Simulated payload close to real shape.
        return {
            "success": True,
            "status": "recognized",
            "vehicle_detected": True,
            "camera_id": task.camera_id,
            "zone_id": task.metadata.get("zone_id"),
            "site_id": task.metadata.get("site_id"),
            "plate_number": f"SIM-{task.camera_id:02d}-{task.sequence:06d}",
            "plate_display": f"SIM-{task.camera_id:02d}-{task.sequence:06d}",
            "plate_type": "civil",
            "confidence": 0.92,
            "plate_confidence": 0.89,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision_reason": "simulated_pipeline",
        }


class SimulatedFrameReader:
    def __init__(self, *, latency_ms_min: float = 2.0, latency_ms_max: float = 8.0):
        self.latency_ms_min = max(0.0, float(latency_ms_min))
        self.latency_ms_max = max(self.latency_ms_min, float(latency_ms_max))
        self._seq_per_camera: dict[int, int] = {}

    def __call__(self, camera_id: int, source: str):
        sleep_ms = random.uniform(self.latency_ms_min, self.latency_ms_max)
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)

        current = self._seq_per_camera.get(camera_id, 0) + 1
        self._seq_per_camera[camera_id] = current
        return {"camera_id": camera_id, "source": source, "frame_no": current}


class ScalingRuntime:
    """
    Standalone runtime for scaling validation.

    It initializes:
    - multi_camera_ingestion_service
    - vehicle_inference_worker
    - vehicle_event_writer_worker
    """

    def __init__(
        self,
        *,
        ingestion_service: MultiCameraIngestionService,
        inference_worker: VehicleInferenceWorker,
        event_writer_worker: VehicleEventWriterWorker,
        frame_queue: BoundedTaskQueue[FrameTask],
        result_queue: BoundedTaskQueue[InferenceResultTask],
        measured_persistence: Optional[InMemoryMeasuredPersistenceService] = None,
        adaptive_rate_controller: Optional[AdaptiveRateController] = None,
        queue_backend: str = "memory",
        queue_metadata: Optional[dict[str, Any]] = None,
    ):
        self.ingestion_service = ingestion_service
        self.inference_worker = inference_worker
        self.event_writer_worker = event_writer_worker
        self.frame_queue = frame_queue
        self.result_queue = result_queue
        self.measured_persistence = measured_persistence
        self.adaptive_rate_controller = adaptive_rate_controller
        self.queue_backend = str(queue_backend or "memory")
        self.queue_metadata = dict(queue_metadata or {})

    @classmethod
    def build_simulated(
        cls,
        *,
        camera_count: int = 20,
        sample_interval_ms: int = 200,
        frame_queue_maxsize: int = 2048,
        result_queue_maxsize: int = 2048,
        queue_backend: str = "memory",
        queue_sqlite_path: str = "data/scaling_runtime_queue.db",
        queue_namespace: str = "simulation",
        inference_workers: int = 8,
        writer_workers: int = 6,
        inference_batch_size: int = 4,
        inference_batch_max_wait_ms: float = 0.0,
        profile: Optional[SimulationProfile] = None,
        persistence_service: Optional[VehicleEventPersistenceService] = None,
        adaptive_rate_config: Optional[AdaptiveRateControllerConfig] = None,
    ) -> "ScalingRuntime":
        sim_profile = profile or SimulationProfile()

        backend = str(queue_backend or "memory").strip().lower()
        if backend == "sqlite":
            db_path = str(queue_sqlite_path or "data/scaling_runtime_queue.db")
            namespace = str(queue_namespace or "simulation").strip() or "simulation"
            frame_queue: BoundedTaskQueue[FrameTask] = SqliteTaskQueue(  # type: ignore[assignment]
                db_path=db_path,
                topic=f"{namespace}_frame",
                maxsize=frame_queue_maxsize,
                purge_on_start=True,
            )
            result_queue: BoundedTaskQueue[InferenceResultTask] = SqliteTaskQueue(  # type: ignore[assignment]
                db_path=db_path,
                topic=f"{namespace}_result",
                maxsize=result_queue_maxsize,
                purge_on_start=True,
            )
            queue_meta = {
                "backend": "sqlite",
                "sqlite_path": db_path,
                "namespace": namespace,
            }
        else:
            frame_queue = BoundedTaskQueue(maxsize=frame_queue_maxsize)
            result_queue = BoundedTaskQueue(maxsize=result_queue_maxsize)
            queue_meta = {"backend": "memory"}

        frame_reader = SimulatedFrameReader(
            latency_ms_min=sim_profile.frame_reader_latency_ms_min,
            latency_ms_max=sim_profile.frame_reader_latency_ms_max,
        )
        ingestion_service = MultiCameraIngestionService(
            frame_queue=frame_queue,
            frame_reader=frame_reader,
            idle_sleep_sec=0.001,
        )
        for cam_id in range(1, max(1, camera_count) + 1):
            ingestion_service.register_camera(
                CameraIngestionConfig(
                    camera_id=cam_id,
                    source=f"sim://camera/{cam_id}",
                    enabled=True,
                    sample_interval_ms=sample_interval_ms,
                    metadata={"direction": "IN"},
                )
            )

        inference_service = SimulatedInferenceService(
            latency_ms_min=sim_profile.inference_latency_ms_min,
            latency_ms_max=sim_profile.inference_latency_ms_max,
            success_ratio=sim_profile.inference_success_ratio,
        )
        inference_worker = VehicleInferenceWorker(
            input_queue=frame_queue,
            output_queue=result_queue,
            inference_fn=inference_service.infer,
            inference_batch_fn=inference_service.infer_batch,
            workers=inference_workers,
            poll_timeout_sec=0.1,
            batch_size=max(1, int(inference_batch_size)),
            batch_max_wait_ms=max(0.0, float(inference_batch_max_wait_ms)),
        )

        if persistence_service is None:
            persistence: Any = InMemoryMeasuredPersistenceService(
                latency_ms_min=sim_profile.persistence_latency_ms_min,
                latency_ms_max=sim_profile.persistence_latency_ms_max,
                success_ratio=sim_profile.persistence_success_ratio,
            )
            measured_persistence: Any = persistence
        else:
            persistence = MeasuredPersistenceAdapter(persistence_service)
            measured_persistence = persistence
        event_writer_worker = VehicleEventWriterWorker(
            input_queue=result_queue,
            persistence_service=persistence,
            workers=writer_workers,
            poll_timeout_sec=0.1,
            max_retries=1,
            retry_backoff_sec=0.01,
        )

        adaptive = None
        if adaptive_rate_config is not None and adaptive_rate_config.enabled:
            adaptive = AdaptiveRateController(
                ingestion_service=ingestion_service,
                frame_queue=frame_queue,
                config=adaptive_rate_config,
            )

        return cls(
            ingestion_service=ingestion_service,
            inference_worker=inference_worker,
            event_writer_worker=event_writer_worker,
            frame_queue=frame_queue,
            result_queue=result_queue,
            measured_persistence=measured_persistence,
            adaptive_rate_controller=adaptive,
            queue_backend=backend,
            queue_metadata=queue_meta,
        )

    def start(self) -> None:
        self.inference_worker.start()
        self.event_writer_worker.start()
        self.ingestion_service.start()
        if self.adaptive_rate_controller is not None:
            self.adaptive_rate_controller.start()

    def stop(self) -> None:
        if self.adaptive_rate_controller is not None:
            self.adaptive_rate_controller.stop()
        self.ingestion_service.stop()
        self.frame_queue.close()
        self.inference_worker.stop()
        self.result_queue.close()
        self.event_writer_worker.stop()

    def snapshot(self) -> dict[str, Any]:
        payload = {
            "ingestion": self.ingestion_service.snapshot_metrics(),
            "inference_worker": self.inference_worker.snapshot_metrics(),
            "event_writer_worker": self.event_writer_worker.snapshot_metrics(),
            "frame_queue": self.frame_queue.snapshot(),
            "result_queue": self.result_queue.snapshot(),
            "queue_transport": {
                "backend": self.queue_backend,
                **self.queue_metadata,
            },
        }
        if self.measured_persistence is not None:
            payload["measured_persistence"] = self.measured_persistence.metrics()
        if self.adaptive_rate_controller is not None:
            payload["adaptive_rate_controller"] = self.adaptive_rate_controller.snapshot()
        payload["runtime_health_panel"] = self._build_runtime_health_panel(payload)
        return payload

    def _build_runtime_health_panel(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        thresholds = RuntimeHealthThresholds()
        frame_queue = snapshot.get("frame_queue", {})
        result_queue = snapshot.get("result_queue", {})
        ingestion = snapshot.get("ingestion", {})
        ingestion_per_camera = ingestion.get("per_camera", {}) or {}
        inference = snapshot.get("inference_worker", {})
        inference_per_camera = inference.get("per_camera", {}) or {}
        persistence = snapshot.get("measured_persistence", {}) or {}
        persistence_latency = persistence.get("latency_ms", {}) or {}

        frame_size = int(frame_queue.get("size", 0))
        frame_maxsize = max(1, int(frame_queue.get("maxsize", 1)))
        frame_queue_util = float(frame_size / frame_maxsize)

        result_size = int(result_queue.get("size", 0))
        result_maxsize = max(1, int(result_queue.get("maxsize", 1)))
        result_queue_util = float(result_size / result_maxsize)

        queue_enqueued = max(1, int(frame_queue.get("enqueued", 0)))
        queue_drop_overflow = int(frame_queue.get("dropped_overflow", 0))
        queue_drop_replaced = int(frame_queue.get("dropped_replaced", 0))
        queue_drop_rate_pct = float((queue_drop_overflow / queue_enqueued) * 100.0)
        queue_replace_rate_pct = float((queue_drop_replaced / queue_enqueued) * 100.0)

        cpu_pct = self._safe_cpu_percent()
        memory_pct = self._safe_memory_percent()

        camera_ids = sorted(
            {
                int(cam_id)
                for cam_id in list(ingestion_per_camera.keys()) + list(inference_per_camera.keys())
            }
        )
        per_camera: dict[int, dict[str, Any]] = {}
        camera_up = 0
        camera_degraded = 0
        camera_down = 0
        for camera_id in camera_ids:
            ing = ingestion_per_camera.get(camera_id, {}) or {}
            inf = inference_per_camera.get(camera_id, {}) or {}
            frames_read = int(ing.get("frames_read", 0))
            frames_enqueued = int(ing.get("frames_enqueued", 0))
            frames_skipped = int(ing.get("frames_skipped_sampling", 0))
            sampling_skip_rate_pct = float((frames_skipped / frames_read) * 100.0) if frames_read > 0 else 0.0
            health_status = str(ing.get("health_status", "unknown")).lower()
            if health_status == "up":
                camera_up += 1
            elif health_status == "down":
                camera_down += 1
            else:
                camera_degraded += 1
            per_camera[camera_id] = {
                "health_status": health_status,
                "read_fps_30s": float(ing.get("read_fps_30s", 0.0) or 0.0),
                "frames_read": frames_read,
                "frames_enqueued": frames_enqueued,
                "sampling_skip_rate_pct": round(sampling_skip_rate_pct, 3),
                "read_errors": int(ing.get("read_errors", 0)),
                "consecutive_read_errors": int(ing.get("consecutive_read_errors", 0)),
                "reconnect_attempts": int(ing.get("reconnect_attempts", 0)),
                "inference_processed": int(inf.get("processed", 0)),
                "inference_failed": int(inf.get("failed", 0)),
                "inference_avg_latency_ms": float(inf.get("avg_latency_ms", 0.0) or 0.0),
                "inference_max_latency_ms": float(inf.get("max_latency_ms", 0.0) or 0.0),
            }

        persist_success_pct = float(persistence.get("success_pct", 0.0) or 0.0)
        end_to_end_p95_ms = float(persistence_latency.get("end_to_end_p95", 0.0) or 0.0)

        risks: list[str] = []
        if frame_queue_util >= thresholds.queue_util_warn:
            risks.append(
                f"frame_queue_util_high:{round(frame_queue_util * 100.0, 2)}pct"
            )
        if queue_drop_rate_pct >= thresholds.queue_drop_rate_warn_pct:
            risks.append(f"frame_queue_drop_rate_high:{round(queue_drop_rate_pct, 3)}pct")
        if persist_success_pct < thresholds.persist_success_warn_pct:
            risks.append(f"persist_success_low:{round(persist_success_pct, 3)}pct")
        if cpu_pct is not None and cpu_pct >= thresholds.cpu_warn_pct:
            risks.append(f"cpu_high:{round(cpu_pct, 2)}pct")
        if camera_down > 0:
            risks.append(f"camera_down:{camera_down}")
        if camera_degraded > 0:
            risks.append(f"camera_degraded:{camera_degraded}")

        status = "healthy"
        if (
            frame_queue_util >= thresholds.queue_util_critical
            or persist_success_pct < thresholds.persist_success_critical_pct
            or (cpu_pct is not None and cpu_pct >= thresholds.cpu_critical_pct)
            or camera_down > 0
        ):
            status = "down"
        elif risks:
            status = "degraded"

        return {
            "status": status,
            "summary": {
                "camera_total": len(camera_ids),
                "camera_up": camera_up,
                "camera_degraded": camera_degraded,
                "camera_down": camera_down,
                "frame_queue_depth": frame_size,
                "frame_queue_maxsize": frame_maxsize,
                "frame_queue_util_pct": round(frame_queue_util * 100.0, 3),
                "result_queue_depth": result_size,
                "result_queue_maxsize": result_maxsize,
                "result_queue_util_pct": round(result_queue_util * 100.0, 3),
                "queue_drop_rate_pct": round(queue_drop_rate_pct, 3),
                "queue_replace_rate_pct": round(queue_replace_rate_pct, 3),
                "cpu_percent": None if cpu_pct is None else round(cpu_pct, 3),
                "memory_percent": None if memory_pct is None else round(memory_pct, 3),
                "inference_avg_latency_ms": float(inference.get("avg_latency_ms", 0.0) or 0.0),
                "inference_max_latency_ms": float(inference.get("max_latency_ms", 0.0) or 0.0),
                "end_to_end_p95_ms": round(end_to_end_p95_ms, 3),
                "persist_success_pct": round(persist_success_pct, 3),
            },
            "risks": risks,
            "per_camera": per_camera,
            "thresholds": {
                "queue_util_warn_pct": round(thresholds.queue_util_warn * 100.0, 3),
                "queue_util_critical_pct": round(thresholds.queue_util_critical * 100.0, 3),
                "queue_drop_rate_warn_pct": thresholds.queue_drop_rate_warn_pct,
                "persist_success_warn_pct": thresholds.persist_success_warn_pct,
                "persist_success_critical_pct": thresholds.persist_success_critical_pct,
                "cpu_warn_pct": thresholds.cpu_warn_pct,
                "cpu_critical_pct": thresholds.cpu_critical_pct,
            },
        }

    @staticmethod
    def _safe_cpu_percent() -> Optional[float]:
        if not _HAS_PSUTIL:
            return None
        try:
            return float(psutil.cpu_percent(interval=None))
        except Exception:
            return None

    @staticmethod
    def _safe_memory_percent() -> Optional[float]:
        if not _HAS_PSUTIL:
            return None
        try:
            return float(psutil.virtual_memory().percent)
        except Exception:
            return None

    def evaluate(
        self,
        thresholds: RuntimeThresholds,
        *,
        preflight_ok_ratio: Optional[float] = None,
    ) -> dict[str, Any]:
        snapshot = self.snapshot()
        persistence = snapshot.get("measured_persistence", {})
        latency = persistence.get("latency_ms", {})
        end_to_end_p95 = float(latency.get("end_to_end_p95", 0.0))
        persist_success_pct = float(persistence.get("success_pct", 0.0))
        frame_queue = snapshot.get("frame_queue", {}) or {}
        result_queue = snapshot.get("result_queue", {}) or {}
        queue_depth = max(
            int(frame_queue.get("high_watermark", 0)),
            int(result_queue.get("high_watermark", 0)),
        )
        queue_overflow_total = int(frame_queue.get("dropped_overflow", 0)) + int(
            result_queue.get("dropped_overflow", 0)
        )

        criteria = {
            "p95_end_to_end_ms_lt_threshold": end_to_end_p95 < float(thresholds.p95_end_to_end_ms_max),
            "queue_depth_lt_threshold": queue_depth < int(thresholds.queue_depth_max),
            "queue_overflow_lte_threshold": queue_overflow_total <= int(thresholds.queue_overflow_max),
            "event_persist_success_gte_threshold": persist_success_pct >= float(
                thresholds.event_persist_success_min_pct
            ),
        }
        values = {
            "p95_end_to_end_ms": round(end_to_end_p95, 3),
            "queue_depth_high_watermark": queue_depth,
            "queue_overflow_total": int(queue_overflow_total),
            "event_persist_success_pct": round(persist_success_pct, 3),
        }
        threshold_payload = {
            "p95_end_to_end_ms_max": float(thresholds.p95_end_to_end_ms_max),
            "queue_depth_max": int(thresholds.queue_depth_max),
            "queue_overflow_max": int(thresholds.queue_overflow_max),
            "event_persist_success_min_pct": float(thresholds.event_persist_success_min_pct),
            "preflight_ok_ratio_min": float(thresholds.preflight_ok_ratio_min),
        }

        if preflight_ok_ratio is not None:
            ratio = max(0.0, min(1.0, float(preflight_ok_ratio)))
            criteria["preflight_ok_ratio_gte_threshold"] = ratio >= float(thresholds.preflight_ok_ratio_min)
            values["preflight_ok_ratio"] = round(ratio, 3)

        if all(criteria.values()):
            verdict = "GO"
        elif (
            "preflight_ok_ratio_gte_threshold" in criteria
            and not criteria["preflight_ok_ratio_gte_threshold"]
        ):
            verdict = "NO-GO_SOURCE_UNSTABLE"
        else:
            verdict = "NO-GO"

        return {
            "verdict": verdict,
            "criteria": criteria,
            "values": values,
            "thresholds": threshold_payload,
        }
