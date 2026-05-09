from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional

from .camera_lease_store import SqliteCameraLeaseStore, build_default_owner_id
from .frame_task_queue import BoundedTaskQueue, FrameTask, InferenceResultTask
from .multi_camera_ingestion_service import CameraIngestionConfig, MultiCameraIngestionService
from .partitioned_frame_queue import PartitionedFrameQueueWriter
from .runtime_tuning import (
    resolve_effective_inference_batch_size,
    resolve_effective_inference_heartbeat_interval_sec,
    resolve_effective_inference_lease_ttl_sec,
    resolve_inference_local_queue_maxsize,
    stable_bucket_for_camera,
)
from .dead_letter_store import InMemoryDeadLetterStore, SqliteDeadLetterStore
from .scaling_runtime import (
    InMemoryMeasuredPersistenceService,
    MeasuredPersistenceAdapter,
    RuntimeThresholds,
    SimulatedFrameReader,
    SimulatedInferenceService,
)
from .sqlite_task_queue import SqliteTaskQueue
from .vehicle_event_persistence_service import (
    SqlAlchemyVehicleEventPersistenceService,
    VehicleEventPersistenceService,
)
from .vehicle_event_writer_worker import VehicleEventWriterWorker
from .vehicle_inference_service import VehicleInferenceService
from .vehicle_inference_worker import VehicleInferenceWorker

DistributedNodeRole = Literal["ingestion", "inference", "writer", "full"]


@dataclass(slots=True)
class DistributedPipelineConfig:
    role: DistributedNodeRole = "full"
    queue_backend: str = "sqlite"
    queue_sqlite_path: str = "data/scaling_runtime_queue.db"
    queue_namespace: str = "distributed"
    queue_purge_on_start: bool = False
    frame_queue_maxsize: int = 2048
    result_queue_maxsize: int = 2048
    camera_count: int = 20
    camera_partition_count: int = 1
    camera_partition_index: int = 0
    camera_ownership_backend: str = "auto"  # auto | sqlite | none
    camera_ownership_sqlite_path: Optional[str] = None
    camera_ownership_namespace: Optional[str] = None
    camera_ownership_owner_id: Optional[str] = None
    camera_ownership_lease_ttl_sec: float = 8.0
    camera_ownership_heartbeat_interval_sec: float = 2.0
    inference_partition_count: int = 1
    inference_partition_index: int = 0
    inference_sticky_by_camera: bool = True
    inference_local_queue_maxsize: int = 0  # 0 => auto
    inference_ownership_backend: str = "auto"  # auto | sqlite | none
    inference_ownership_sqlite_path: Optional[str] = None
    inference_ownership_namespace: Optional[str] = None
    inference_ownership_owner_id: Optional[str] = None
    inference_ownership_lease_ttl_sec: float = 8.0
    inference_ownership_heartbeat_interval_sec: float = 2.0
    sample_interval_ms: int = 200
    inference_workers: int = 8
    inference_batch_size: int = 4
    inference_batch_max_wait_ms: float = 0.0
    writer_workers: int = 6
    inference_mode: str = "simulated"  # simulated | real
    persist_target: str = "memory"  # memory | db
    frame_reader_latency_ms_min: float = 2.0
    frame_reader_latency_ms_max: float = 8.0
    inference_latency_ms_min: float = 40.0
    inference_latency_ms_max: float = 120.0
    inference_success_ratio: float = 1.0
    persistence_latency_ms_min: float = 3.0
    persistence_latency_ms_max: float = 18.0
    persistence_success_ratio: float = 1.0
    dead_letter_backend: str = "none"  # none | memory | sqlite
    dead_letter_sqlite_path: str = "data/scaling_dead_letters.db"
    dead_letter_namespace: str = "distributed"
    resilience_supervisor_enabled: bool = True
    resilience_supervisor_interval_sec: float = 2.0
    resilience_restart_cooldown_sec: float = 1.0
    resilience_max_restarts_per_component: int = 100


class DistributedPipelineNode:
    """
    Role-based runtime node for distributed scaling architecture.

    Each node can run one role (ingestion / inference / writer) or all roles.
    Queues can be in-memory (single process) or SQLite (multi-process sharing).
    """

    def __init__(
        self,
        *,
        config: Optional[DistributedPipelineConfig] = None,
        frame_reader: Optional[Any] = None,
        persistence_service: Optional[VehicleEventPersistenceService] = None,
        frame_queue: Optional[Any] = None,
        result_queue: Optional[Any] = None,
    ):
        self.config = config or DistributedPipelineConfig()
        self.role = str(self.config.role).strip().lower()
        if self.role not in {"ingestion", "inference", "writer", "full"}:
            raise ValueError(f"Unsupported role: {self.config.role}")
        self.config.camera_partition_count = max(1, int(self.config.camera_partition_count))
        self.config.camera_partition_index = max(
            0,
            min(
                int(self.config.camera_partition_index),
                self.config.camera_partition_count - 1,
            ),
        )
        self.config.inference_partition_count = max(1, int(self.config.inference_partition_count))
        self.config.inference_partition_index = max(
            0,
            min(
                int(self.config.inference_partition_index),
                self.config.inference_partition_count - 1,
            ),
        )

        if not self.config.camera_ownership_owner_id:
            self.config.camera_ownership_owner_id = build_default_owner_id(self.role)
        if self.role == "inference" and not self.config.inference_ownership_owner_id:
            self.config.inference_ownership_owner_id = build_default_owner_id("inference")
        self._runtime_tuning = self._build_runtime_tuning()
        self.frame_queue, self.result_queue, self.queue_transport = self._build_queues(
            frame_queue=frame_queue,
            result_queue=result_queue,
        )
        self.camera_lease_store: Optional[SqliteCameraLeaseStore] = self._build_camera_lease_store()
        self.inference_lease_store: Optional[SqliteCameraLeaseStore] = self._build_inference_lease_store()

        self.ingestion_service: Optional[MultiCameraIngestionService] = None
        self.inference_worker: Optional[VehicleInferenceWorker] = None
        self.event_writer_worker: Optional[VehicleEventWriterWorker] = None
        self._real_inference_service: Optional[VehicleInferenceService] = None
        self.measured_persistence: Optional[Any] = None
        self.dead_letter_store: Optional[Any] = self._build_dead_letter_store()
        self._build_components(frame_reader=frame_reader, persistence_service=persistence_service)
        self._resilience_lock = threading.RLock()
        self._supervisor_stop = threading.Event()
        self._supervisor_thread: Optional[threading.Thread] = None
        self._component_last_restart_epoch: dict[str, float] = {
            "ingestion": 0.0,
            "inference": 0.0,
            "writer": 0.0,
        }
        self._resilience_metrics: dict[str, Any] = {
            "enabled": bool(self.config.resilience_supervisor_enabled),
            "interval_sec": max(0.2, float(self.config.resilience_supervisor_interval_sec)),
            "restart_cooldown_sec": max(0.0, float(self.config.resilience_restart_cooldown_sec)),
            "max_restarts_per_component": max(1, int(self.config.resilience_max_restarts_per_component)),
            "last_supervisor_pass_at": None,
            "restarts": {
                "ingestion": 0,
                "inference": 0,
                "writer": 0,
            },
            "incidents": [],
        }

    def start(self) -> None:
        if self.inference_worker is not None:
            self.inference_worker.start()
        if self.event_writer_worker is not None:
            self.event_writer_worker.start()
        if self.ingestion_service is not None:
            self.ingestion_service.start()
        self._start_supervisor_if_enabled()

    def stop(self) -> None:
        self._stop_supervisor()
        if self.ingestion_service is not None:
            self.ingestion_service.stop()
        self.frame_queue.close()
        if self.inference_worker is not None:
            self.inference_worker.stop()
        self.result_queue.close()
        if self.event_writer_worker is not None:
            self.event_writer_worker.stop()
        if self._real_inference_service is not None:
            self._real_inference_service.close_all()

    def snapshot(self) -> dict[str, Any]:
        payload = {
            "role": self.role,
            "config": asdict(self.config),
            "queue_transport": dict(self.queue_transport),
            "frame_queue": self.frame_queue.snapshot(),
            "result_queue": self.result_queue.snapshot(),
        }
        if self.ingestion_service is not None:
            payload["ingestion"] = self.ingestion_service.snapshot_metrics()
        if self.camera_lease_store is not None:
            payload["camera_ownership"] = self.camera_lease_store.snapshot(limit=max(20, int(self.config.camera_count)))
        if self.inference_lease_store is not None:
            payload["inference_ownership"] = self.inference_lease_store.snapshot(
                limit=max(1, int(self.config.inference_partition_count))
            )
        if self.inference_worker is not None:
            payload["inference_worker"] = self.inference_worker.snapshot_metrics()
        if self.event_writer_worker is not None:
            payload["event_writer_worker"] = self.event_writer_worker.snapshot_metrics()
        if self.measured_persistence is not None and hasattr(self.measured_persistence, "metrics"):
            payload["measured_persistence"] = self.measured_persistence.metrics()
        if self.dead_letter_store is not None and hasattr(self.dead_letter_store, "snapshot"):
            payload["dead_letters"] = self.dead_letter_store.snapshot(limit=20)
        payload["runtime_tuning"] = dict(self._runtime_tuning)
        payload["resilience"] = self._snapshot_resilience()
        return payload

    def evaluate(self, thresholds: RuntimeThresholds) -> dict[str, Any]:
        snapshot = self.snapshot()
        persistence = snapshot.get("measured_persistence", {}) or {}
        latency = persistence.get("latency_ms", {}) or {}
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
            "event_persist_success_gte_threshold": persist_success_pct
            >= float(thresholds.event_persist_success_min_pct),
        }
        verdict = "GO" if all(criteria.values()) else "NO-GO"
        return {
            "verdict": verdict,
            "criteria": criteria,
            "values": {
                "p95_end_to_end_ms": round(end_to_end_p95, 3),
                "queue_depth_high_watermark": queue_depth,
                "queue_overflow_total": int(queue_overflow_total),
                "event_persist_success_pct": round(persist_success_pct, 3),
            },
            "thresholds": {
                "p95_end_to_end_ms_max": float(thresholds.p95_end_to_end_ms_max),
                "queue_depth_max": int(thresholds.queue_depth_max),
                "queue_overflow_max": int(thresholds.queue_overflow_max),
                "event_persist_success_min_pct": float(thresholds.event_persist_success_min_pct),
            },
        }

    def _start_supervisor_if_enabled(self) -> None:
        if not bool(self._resilience_metrics.get("enabled", False)):
            return
        with self._resilience_lock:
            if self._supervisor_thread is not None and self._supervisor_thread.is_alive():
                return
            self._supervisor_stop.clear()
            self._supervisor_thread = threading.Thread(
                target=self._supervisor_loop,
                name=f"distributed-resilience-{self.role}",
                daemon=True,
            )
            self._supervisor_thread.start()

    def _stop_supervisor(self) -> None:
        with self._resilience_lock:
            self._supervisor_stop.set()
            thread = self._supervisor_thread
            self._supervisor_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def _snapshot_resilience(self) -> dict[str, Any]:
        with self._resilience_lock:
            restarts = dict(self._resilience_metrics.get("restarts", {}) or {})
            incidents = list(self._resilience_metrics.get("incidents", []) or [])
            return {
                "enabled": bool(self._resilience_metrics.get("enabled", False)),
                "supervisor_running": bool(self._supervisor_thread is not None and self._supervisor_thread.is_alive()),
                "interval_sec": float(self._resilience_metrics.get("interval_sec", 0.0) or 0.0),
                "restart_cooldown_sec": float(
                    self._resilience_metrics.get("restart_cooldown_sec", 0.0) or 0.0
                ),
                "max_restarts_per_component": int(
                    self._resilience_metrics.get("max_restarts_per_component", 0) or 0
                ),
                "last_supervisor_pass_at": self._resilience_metrics.get("last_supervisor_pass_at"),
                "restarts": restarts,
                "restarts_total": int(sum(int(v or 0) for v in restarts.values())),
                "incidents_total": len(incidents),
                "incidents": incidents[-20:],
            }

    def _supervisor_loop(self) -> None:
        interval_sec = max(0.2, float(self._resilience_metrics.get("interval_sec", 2.0) or 2.0))
        while not self._supervisor_stop.is_set():
            try:
                self._run_supervisor_pass()
            except Exception as exc:
                self._record_resilience_incident(
                    component="supervisor",
                    code="supervisor_pass_failed",
                    message=str(exc),
                )
            self._supervisor_stop.wait(interval_sec)

    def _run_supervisor_pass(self) -> None:
        now = time.time()
        with self._resilience_lock:
            self._resilience_metrics["last_supervisor_pass_at"] = time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.gmtime(now)
            )

        if self.ingestion_service is not None:
            can_restart, reason = self._can_restart_component("ingestion", now)
            if can_restart:
                healed = self.ingestion_service.ensure_camera_threads()
                restarted = int(healed.get("restarted", 0) or 0)
                if restarted > 0:
                    self._record_component_restart(
                        component="ingestion",
                        restarted=restarted,
                        details={"cameras": list(healed.get("restarted_cameras", []) or [])},
                    )
            elif reason == "max_restarts_exceeded":
                self._record_resilience_incident(
                    component="ingestion",
                    code="restart_blocked_max_restarts",
                    message="Ingestion self-heal blocked: max restarts reached.",
                )

        if self.inference_worker is not None:
            metrics = self.inference_worker.snapshot_metrics()
            expected = int(metrics.get("expected_workers", metrics.get("workers", 0)) or 0)
            alive = int(metrics.get("alive_workers", 0) or 0)
            dispatcher_required = bool(
                metrics.get("sticky_by_camera")
                or bool((metrics.get("ownership", {}) or {}).get("enabled", False))
            )
            dispatcher_running = bool(metrics.get("dispatcher_running", not dispatcher_required))
            if expected > 0 and (alive < expected or not dispatcher_running):
                can_restart, reason = self._can_restart_component("inference", now)
                if can_restart:
                    healed = self.inference_worker.ensure_worker_threads()
                    restarted = int(healed.get("restarted", 0) or 0)
                    if restarted > 0:
                        self._record_component_restart(
                            component="inference",
                            restarted=restarted,
                            details={
                                "alive_workers": int(healed.get("alive_workers", 0) or 0),
                                "expected_workers": int(healed.get("expected_workers", expected) or expected),
                                "dispatcher_running": dispatcher_running,
                            },
                        )
                elif reason == "max_restarts_exceeded":
                    self._record_resilience_incident(
                        component="inference",
                        code="restart_blocked_max_restarts",
                        message="Inference self-heal blocked: max restarts reached.",
                    )

        if self.event_writer_worker is not None:
            metrics = self.event_writer_worker.snapshot_metrics()
            expected = int(metrics.get("expected_workers", metrics.get("workers", 0)) or 0)
            alive = int(metrics.get("alive_workers", 0) or 0)
            if expected > 0 and alive < expected:
                can_restart, reason = self._can_restart_component("writer", now)
                if can_restart:
                    healed = self.event_writer_worker.ensure_worker_threads()
                    restarted = int(healed.get("restarted", 0) or 0)
                    if restarted > 0:
                        self._record_component_restart(
                            component="writer",
                            restarted=restarted,
                            details={
                                "alive_workers": int(healed.get("alive_workers", 0) or 0),
                                "expected_workers": int(healed.get("expected_workers", expected) or expected),
                            },
                        )
                elif reason == "max_restarts_exceeded":
                    self._record_resilience_incident(
                        component="writer",
                        code="restart_blocked_max_restarts",
                        message="Writer self-heal blocked: max restarts reached.",
                    )

    def _can_restart_component(self, component: str, now_epoch: float) -> tuple[bool, str]:
        component_key = str(component or "").strip().lower()
        if component_key not in {"ingestion", "inference", "writer"}:
            return False, "unknown_component"
        with self._resilience_lock:
            restarts = self._resilience_metrics.get("restarts", {}) or {}
            current = int(restarts.get(component_key, 0) or 0)
            max_restarts = int(self._resilience_metrics.get("max_restarts_per_component", 0) or 0)
            if current >= max_restarts:
                return False, "max_restarts_exceeded"
            last_restart = float(self._component_last_restart_epoch.get(component_key, 0.0) or 0.0)
            cooldown = float(self._resilience_metrics.get("restart_cooldown_sec", 0.0) or 0.0)
            if last_restart > 0 and cooldown > 0 and (now_epoch - last_restart) < cooldown:
                return False, "restart_cooldown"
            return True, "ok"

    def _record_component_restart(self, *, component: str, restarted: int, details: Optional[dict[str, Any]] = None) -> None:
        component_key = str(component or "").strip().lower()
        if restarted <= 0 or component_key not in {"ingestion", "inference", "writer"}:
            return
        now_epoch = time.time()
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now_epoch))
        with self._resilience_lock:
            restarts = self._resilience_metrics.get("restarts", {}) or {}
            restarts[component_key] = int(restarts.get(component_key, 0) or 0) + int(restarted)
            self._resilience_metrics["restarts"] = restarts
            self._component_last_restart_epoch[component_key] = now_epoch
            incidents = self._resilience_metrics.get("incidents", []) or []
            incidents.append(
                {
                    "timestamp": timestamp,
                    "component": component_key,
                    "code": "self_heal_restart",
                    "restarted": int(restarted),
                    "details": details or {},
                }
            )
            self._resilience_metrics["incidents"] = incidents[-100:]

    def _record_resilience_incident(self, *, component: str, code: str, message: str) -> None:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time()))
        with self._resilience_lock:
            incidents = self._resilience_metrics.get("incidents", []) or []
            incidents.append(
                {
                    "timestamp": timestamp,
                    "component": str(component),
                    "code": str(code),
                    "message": str(message),
                }
            )
            self._resilience_metrics["incidents"] = incidents[-100:]

    def _build_components(
        self,
        *,
        frame_reader: Optional[Any],
        persistence_service: Optional[VehicleEventPersistenceService],
    ) -> None:
        if self.role in {"ingestion", "full"}:
            reader = frame_reader or SimulatedFrameReader(
                latency_ms_min=float(self.config.frame_reader_latency_ms_min),
                latency_ms_max=float(self.config.frame_reader_latency_ms_max),
            )
            self.ingestion_service = MultiCameraIngestionService(
                frame_queue=self.frame_queue,
                frame_reader=reader,
                idle_sleep_sec=0.001,
                camera_lease_store=self.camera_lease_store,
                ownership_heartbeat_interval_sec=float(self.config.camera_ownership_heartbeat_interval_sec),
            )
            for cam_id in range(1, max(1, int(self.config.camera_count)) + 1):
                if not self._camera_belongs_to_partition(cam_id):
                    continue
                self.ingestion_service.register_camera(
                    CameraIngestionConfig(
                        camera_id=cam_id,
                        source=f"sim://camera/{cam_id}",
                        enabled=True,
                        sample_interval_ms=int(self.config.sample_interval_ms),
                        metadata={
                            "direction": "IN",
                            "camera_partition_index": int(self.config.camera_partition_index),
                            "camera_partition_count": int(self.config.camera_partition_count),
                            "inference_partition_index": int(self._inference_partition_for_camera(cam_id)),
                            "inference_partition_count": int(self.config.inference_partition_count),
                        },
                    )
                )

        if self.role in {"inference", "full"}:
            mode = str(self.config.inference_mode or "simulated").strip().lower()
            sticky_inference = bool(self.config.inference_sticky_by_camera)
            if mode == "real":
                self._real_inference_service = VehicleInferenceService(
                    persist=False,
                    save_snapshot=False,
                    reuse_thread_local_pipeline=sticky_inference,
                    rebind_db_per_call=sticky_inference,
                )
                inference_fn = self._real_inference_service.infer
                inference_batch_fn = self._real_inference_service.infer_batch
            else:
                sim_infer = SimulatedInferenceService(
                    latency_ms_min=float(self.config.inference_latency_ms_min),
                    latency_ms_max=float(self.config.inference_latency_ms_max),
                    success_ratio=float(self.config.inference_success_ratio),
                )
                inference_fn = sim_infer.infer
                inference_batch_fn = sim_infer.infer_batch

            self.inference_worker = VehicleInferenceWorker(
                input_queue=self.frame_queue,
                output_queue=self.result_queue,
                inference_fn=inference_fn,
                inference_batch_fn=inference_batch_fn,
                dead_letter_store=self.dead_letter_store,
                workers=max(1, int(self.config.inference_workers)),
                poll_timeout_sec=0.1,
                batch_size=int(self._runtime_tuning.get("effective_inference_batch_size", 1) or 1),
                batch_max_wait_ms=max(0.0, float(self.config.inference_batch_max_wait_ms)),
                sticky_by_camera=sticky_inference,
                local_queue_maxsize=int(self._runtime_tuning.get("inference_local_queue_maxsize", 16) or 16),
                sticky_hash_salt=str(self._runtime_tuning.get("sticky_hash_salt", "")),
                ownership_lease_store=self.inference_lease_store,
                ownership_resource_id=self._inference_partition_resource_id(),
                ownership_heartbeat_interval_sec=float(
                    self._runtime_tuning.get("effective_inference_ownership_heartbeat_interval_sec", 2.0) or 2.0
                ),
            )

        if self.role in {"writer", "full"}:
            if persistence_service is not None:
                persistence = MeasuredPersistenceAdapter(persistence_service)
                self.measured_persistence = persistence
            elif str(self.config.persist_target).strip().lower() == "db":
                persistence = MeasuredPersistenceAdapter(SqlAlchemyVehicleEventPersistenceService())
                self.measured_persistence = persistence
            else:
                persistence = InMemoryMeasuredPersistenceService(
                    latency_ms_min=float(self.config.persistence_latency_ms_min),
                    latency_ms_max=float(self.config.persistence_latency_ms_max),
                    success_ratio=float(self.config.persistence_success_ratio),
                )
                self.measured_persistence = persistence

            self.event_writer_worker = VehicleEventWriterWorker(
                input_queue=self.result_queue,
                persistence_service=persistence,
                dead_letter_store=self.dead_letter_store,
                workers=max(1, int(self.config.writer_workers)),
                poll_timeout_sec=0.1,
                max_retries=1,
                retry_backoff_sec=0.01,
            )

    def _build_queues(
        self,
        *,
        frame_queue: Optional[Any],
        result_queue: Optional[Any],
    ) -> tuple[Any, Any, dict[str, Any]]:
        if frame_queue is not None and result_queue is not None:
            return frame_queue, result_queue, {"backend": "external"}

        backend = str(self.config.queue_backend or "memory").strip().lower()
        if backend == "sqlite":
            sqlite_path = str(self.config.queue_sqlite_path or "data/scaling_runtime_queue.db")
            namespace = str(self.config.queue_namespace or "distributed").strip() or "distributed"
            purge = bool(self.config.queue_purge_on_start)
            frame_partition_count = max(1, int(self.config.inference_partition_count))
            frame_partitioned = self.role in {"ingestion", "inference"} and frame_partition_count > 1
            if self.role == "ingestion" and frame_partitioned:
                frame_topics = [f"{namespace}_frame_p{index}" for index in range(frame_partition_count)]
                frame_queues = [
                    SqliteTaskQueue[FrameTask](
                        db_path=sqlite_path,
                        topic=topic,
                        maxsize=max(1, int(self.config.frame_queue_maxsize)),
                        purge_on_start=purge,
                    )
                    for topic in frame_topics
                ]
                fq: Any = PartitionedFrameQueueWriter(
                    queues=frame_queues,
                    partition_count=frame_partition_count,
                    hash_salt=str(self._runtime_tuning.get("sticky_hash_salt", "")),
                )
            elif self.role == "inference" and frame_partitioned:
                frame_topic = f"{namespace}_frame_p{int(self.config.inference_partition_index)}"
                fq = SqliteTaskQueue[FrameTask](
                    db_path=sqlite_path,
                    topic=frame_topic,
                    maxsize=max(1, int(self.config.frame_queue_maxsize)),
                    purge_on_start=purge,
                )
            else:
                fq = SqliteTaskQueue[FrameTask](
                    db_path=sqlite_path,
                    topic=f"{namespace}_frame",
                    maxsize=max(1, int(self.config.frame_queue_maxsize)),
                    purge_on_start=purge,
                )
            rq = SqliteTaskQueue[InferenceResultTask](
                db_path=sqlite_path,
                topic=f"{namespace}_result",
                maxsize=max(1, int(self.config.result_queue_maxsize)),
                purge_on_start=purge,
            )
            meta = {
                "backend": "sqlite",
                "sqlite_path": sqlite_path,
                "namespace": namespace,
                "purge_on_start": purge,
                "frame_partitioned": bool(frame_partitioned),
                "inference_partition_count": int(frame_partition_count),
                "inference_partition_index": int(self.config.inference_partition_index),
                "sticky_hash_salt": str(self._runtime_tuning.get("sticky_hash_salt", "")),
            }
            return fq, rq, meta

        fq = BoundedTaskQueue[FrameTask](maxsize=max(1, int(self.config.frame_queue_maxsize)))
        rq = BoundedTaskQueue[InferenceResultTask](maxsize=max(1, int(self.config.result_queue_maxsize)))
        return fq, rq, {"backend": "memory"}

    def _build_dead_letter_store(self) -> Optional[Any]:
        backend = str(self.config.dead_letter_backend or "none").strip().lower()
        if backend == "sqlite":
            return SqliteDeadLetterStore(
                db_path=str(self.config.dead_letter_sqlite_path or "data/scaling_dead_letters.db"),
                namespace=str(self.config.dead_letter_namespace or self.config.queue_namespace or "distributed"),
            )
        if backend == "memory":
            return InMemoryDeadLetterStore()
        return None

    def _build_camera_lease_store(self) -> Optional[SqliteCameraLeaseStore]:
        if self.role not in {"ingestion", "full"}:
            return None

        backend = str(self.config.camera_ownership_backend or "auto").strip().lower()
        if backend == "auto":
            backend = "sqlite" if str(self.config.queue_backend or "").strip().lower() == "sqlite" else "none"
        if backend == "none":
            return None
        if backend != "sqlite":
            raise ValueError(f"Unsupported camera ownership backend: {self.config.camera_ownership_backend}")

        db_path = str(
            self.config.camera_ownership_sqlite_path
            or self.config.queue_sqlite_path
            or "data/scaling_runtime_queue.db"
        )
        namespace = str(
            self.config.camera_ownership_namespace
            or self.config.queue_namespace
            or "distributed"
        ).strip() or "distributed"
        owner_id = str(
            self.config.camera_ownership_owner_id
            or build_default_owner_id(self.role)
        )
        self.config.camera_ownership_owner_id = owner_id
        return SqliteCameraLeaseStore(
            db_path=db_path,
            namespace=namespace,
            owner_id=owner_id,
            owner_role=self.role,
            lease_ttl_sec=float(self.config.camera_ownership_lease_ttl_sec),
        )

    def _build_inference_lease_store(self) -> Optional[SqliteCameraLeaseStore]:
        if self.role != "inference":
            return None

        backend = str(self.config.inference_ownership_backend or "auto").strip().lower()
        if backend == "auto":
            backend = "sqlite" if str(self.config.queue_backend or "").strip().lower() == "sqlite" else "none"
        if backend == "none":
            return None
        if backend != "sqlite":
            raise ValueError(f"Unsupported inference ownership backend: {self.config.inference_ownership_backend}")

        db_path = str(
            self.config.inference_ownership_sqlite_path
            or self.config.queue_sqlite_path
            or "data/scaling_runtime_queue.db"
        )
        namespace = str(
            self.config.inference_ownership_namespace
            or f"{self.config.queue_namespace or 'distributed'}:inference_partition"
        ).strip() or "distributed:inference_partition"
        owner_id = str(
            self.config.inference_ownership_owner_id
            or build_default_owner_id("inference")
        )
        self.config.inference_ownership_owner_id = owner_id
        return SqliteCameraLeaseStore(
            db_path=db_path,
            namespace=namespace,
            owner_id=owner_id,
            owner_role="inference",
            lease_ttl_sec=float(
                self._runtime_tuning.get("effective_inference_ownership_lease_ttl_sec", self.config.inference_ownership_lease_ttl_sec)
            ),
        )

    def _camera_belongs_to_partition(self, camera_id: int) -> bool:
        partition_count = max(1, int(self.config.camera_partition_count))
        partition_index = max(0, int(self.config.camera_partition_index))
        return ((int(camera_id) - 1) % partition_count) == partition_index

    def _inference_partition_for_camera(self, camera_id: int) -> int:
        return stable_bucket_for_camera(
            int(camera_id),
            max(1, int(self.config.inference_partition_count)),
            salt=str(self._runtime_tuning.get("sticky_hash_salt", "")),
        )

    def _inference_partition_resource_id(self) -> int:
        return int(self.config.inference_partition_index) + 1

    def _build_runtime_tuning(self) -> dict[str, Any]:
        sticky_hash_salt = f"{self.config.queue_namespace or 'distributed'}:inference"
        effective_batch_size = resolve_effective_inference_batch_size(
            configured_batch_size=int(self.config.inference_batch_size),
            camera_count=int(self.config.camera_count),
            inference_partition_count=int(self.config.inference_partition_count),
            inference_workers=max(1, int(self.config.inference_workers)),
            sticky_by_camera=bool(self.config.inference_sticky_by_camera),
        )
        effective_heartbeat_interval_sec = resolve_effective_inference_heartbeat_interval_sec(
            configured_heartbeat_interval_sec=float(self.config.inference_ownership_heartbeat_interval_sec),
            sample_interval_ms=int(self.config.sample_interval_ms),
            camera_count=int(self.config.camera_count),
            inference_partition_count=int(self.config.inference_partition_count),
            inference_workers=max(1, int(self.config.inference_workers)),
        )
        effective_lease_ttl_sec = resolve_effective_inference_lease_ttl_sec(
            configured_lease_ttl_sec=float(self.config.inference_ownership_lease_ttl_sec),
            effective_heartbeat_interval_sec=effective_heartbeat_interval_sec,
            camera_count=int(self.config.camera_count),
            inference_partition_count=int(self.config.inference_partition_count),
            inference_workers=max(1, int(self.config.inference_workers)),
            effective_batch_size=effective_batch_size,
        )
        inference_local_queue_maxsize = resolve_inference_local_queue_maxsize(
            configured_local_queue_maxsize=int(self.config.inference_local_queue_maxsize),
            frame_queue_maxsize=int(self.config.frame_queue_maxsize),
            camera_count=int(self.config.camera_count),
            inference_partition_count=int(self.config.inference_partition_count),
            inference_workers=max(1, int(self.config.inference_workers)),
            effective_batch_size=effective_batch_size,
        )
        return {
            "sticky_hash_salt": sticky_hash_salt,
            "effective_inference_batch_size": int(effective_batch_size),
            "inference_local_queue_maxsize": int(inference_local_queue_maxsize),
            "effective_inference_ownership_heartbeat_interval_sec": float(effective_heartbeat_interval_sec),
            "effective_inference_ownership_lease_ttl_sec": float(effective_lease_ttl_sec),
        }


def run_node_for_duration(node: DistributedPipelineNode, *, duration_sec: int) -> None:
    node.start()
    try:
        time.sleep(max(1, int(duration_sec)))
    finally:
        node.stop()
