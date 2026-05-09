from __future__ import annotations

from collections import deque
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from vms.backend.services.stream_service import StreamService

from .frame_task_queue import BoundedTaskQueue, FrameTask, utc_now_iso


@dataclass(slots=True)
class CameraIngestionConfig:
    camera_id: int
    source: str
    enabled: bool = True
    sample_interval_ms: int = 500
    retry_backoff_ms: int = 150
    retry_backoff_max_ms: int = 5000
    retry_backoff_factor: float = 2.0
    degraded_error_threshold: int = 3
    down_error_threshold: int = 10
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _CameraIngestionMetrics:
    frames_read: int = 0
    frames_enqueued: int = 0
    frames_skipped_sampling: int = 0
    read_errors: int = 0
    read_none_errors: int = 0
    read_exception_errors: int = 0
    consecutive_read_errors: int = 0
    reconnect_attempts: int = 0
    reconnect_recoveries: int = 0
    current_backoff_ms: int = 0
    health_status: str = "starting"
    health_reason: Optional[str] = None
    health_changed_at: Optional[str] = None
    last_frame_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_error_at: Optional[str] = None
    last_error: Optional[str] = None
    last_sequence: int = 0
    recent_success_monotonic: deque[float] = field(default_factory=lambda: deque(maxlen=512))
    ownership_status: str = "disabled"
    ownership_owner_id: Optional[str] = None
    ownership_owner_role: Optional[str] = None
    ownership_claimed_at: Optional[str] = None
    ownership_last_heartbeat_at: Optional[str] = None
    ownership_expires_at: Optional[str] = None
    ownership_acquired_total: int = 0
    ownership_renewed_total: int = 0
    ownership_denied_total: int = 0
    ownership_released_total: int = 0


class MultiCameraIngestionService:
    """
    Continuous RTSP ingestion service.

    This service runs independently from API request threads and pushes sampled
    frame tasks to a bounded queue for downstream async inference workers.
    """

    def __init__(
        self,
        *,
        frame_queue: BoundedTaskQueue[FrameTask],
        frame_reader: Optional[Callable[[int, str], Any]] = None,
        idle_sleep_sec: float = 0.01,
        camera_lease_store: Optional[Any] = None,
        ownership_heartbeat_interval_sec: float = 2.0,
    ):
        self.frame_queue = frame_queue
        self.frame_reader = frame_reader or self._default_frame_reader
        self.idle_sleep_sec = max(0.001, float(idle_sleep_sec))
        self.camera_lease_store = camera_lease_store
        self.ownership_heartbeat_interval_sec = max(0.1, float(ownership_heartbeat_interval_sec))

        self._lock = threading.RLock()
        self._running = False
        self._configs: Dict[int, CameraIngestionConfig] = {}
        self._threads: Dict[int, threading.Thread] = {}
        self._stops: Dict[int, threading.Event] = {}
        self._metrics: Dict[int, _CameraIngestionMetrics] = {}
        self._service_metrics: Dict[str, Any] = {
            "thread_restarts_total": 0,
            "last_self_heal_at": None,
        }

    def register_camera(self, config: CameraIngestionConfig) -> None:
        with self._lock:
            self._configs[int(config.camera_id)] = config
            self._metrics.setdefault(int(config.camera_id), _CameraIngestionMetrics())
            if self._running and config.enabled and int(config.camera_id) not in self._threads:
                self._start_camera_thread_if_owned_locked(int(config.camera_id))

    def update_camera(self, camera_id: int, **kwargs: Any) -> None:
        with self._lock:
            current = self._configs.get(int(camera_id))
            if current is None:
                raise KeyError(f"Camera {camera_id} is not registered")

            for key, value in kwargs.items():
                if hasattr(current, key):
                    setattr(current, key, value)

            if self._running:
                enabled = bool(current.enabled)
                has_thread = int(camera_id) in self._threads
                if enabled and not has_thread:
                    self._start_camera_thread_if_owned_locked(int(camera_id))
                if not enabled and has_thread:
                    self._stop_camera_thread_locked(int(camera_id))

    def remove_camera(self, camera_id: int) -> None:
        with self._lock:
            self._configs.pop(int(camera_id), None)
            self._stop_camera_thread_locked(int(camera_id))

    def list_cameras(self) -> list[CameraIngestionConfig]:
        with self._lock:
            return list(self._configs.values())

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            for camera_id, cfg in self._configs.items():
                if cfg.enabled and camera_id not in self._threads:
                    self._start_camera_thread_if_owned_locked(camera_id)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            camera_ids = list(self._threads.keys())
            for camera_id in camera_ids:
                self._stop_camera_thread_locked(camera_id)

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def snapshot_metrics(self) -> dict[str, Any]:
        with self._lock:
            alive_threads = sum(1 for thread in self._threads.values() if thread.is_alive())
            health_counts = {"up": 0, "degraded": 0, "down": 0, "starting": 0, "standby": 0, "disabled": 0}
            ownership_counts = {"owned": 0, "standby": 0, "released": 0, "disabled": 0}
            per_camera = {
                camera_id: {
                    "frames_read": metric.frames_read,
                    "frames_enqueued": metric.frames_enqueued,
                    "frames_skipped_sampling": metric.frames_skipped_sampling,
                    "read_errors": metric.read_errors,
                    "read_none_errors": metric.read_none_errors,
                    "read_exception_errors": metric.read_exception_errors,
                    "consecutive_read_errors": metric.consecutive_read_errors,
                    "reconnect_attempts": metric.reconnect_attempts,
                    "reconnect_recoveries": metric.reconnect_recoveries,
                    "current_backoff_ms": metric.current_backoff_ms,
                    "health_status": metric.health_status,
                    "health_reason": metric.health_reason,
                    "health_changed_at": metric.health_changed_at,
                    "last_frame_at": metric.last_frame_at,
                    "last_success_at": metric.last_success_at,
                    "last_error_at": metric.last_error_at,
                    "last_error": metric.last_error,
                    "last_sequence": metric.last_sequence,
                    "read_fps_30s": self._compute_read_fps_30s(metric),
                    "ownership": {
                        "status": metric.ownership_status,
                        "owner_id": metric.ownership_owner_id,
                        "owner_role": metric.ownership_owner_role,
                        "claimed_at": metric.ownership_claimed_at,
                        "last_heartbeat_at": metric.ownership_last_heartbeat_at,
                        "lease_expires_at": metric.ownership_expires_at,
                        "acquired_total": metric.ownership_acquired_total,
                        "renewed_total": metric.ownership_renewed_total,
                        "denied_total": metric.ownership_denied_total,
                        "released_total": metric.ownership_released_total,
                    },
                }
                for camera_id, metric in self._metrics.items()
            }
            for metric in self._metrics.values():
                key = str(metric.health_status or "starting").lower()
                if key not in health_counts:
                    key = "starting"
                health_counts[key] += 1
                ownership_key = str(metric.ownership_status or "disabled").lower()
                if ownership_key not in ownership_counts:
                    ownership_key = "disabled"
                ownership_counts[ownership_key] += 1
            return {
                "service": {
                    "running": self._running,
                    "registered_cameras": len(self._configs),
                    "enabled_cameras": sum(1 for cfg in self._configs.values() if bool(cfg.enabled)),
                    "active_threads": len(self._threads),
                    "alive_threads": int(alive_threads),
                    "missing_threads": max(0, int(len(self._threads) - alive_threads)),
                    "thread_restarts_total": int(self._service_metrics.get("thread_restarts_total", 0) or 0),
                    "last_self_heal_at": self._service_metrics.get("last_self_heal_at"),
                    "health_counts": health_counts,
                    "ownership_backend": "sqlite" if self.camera_lease_store is not None else "disabled",
                    "ownership_owner_id": getattr(self.camera_lease_store, "owner_id", None),
                    "ownership_lease_ttl_sec": float(getattr(self.camera_lease_store, "lease_ttl_sec", 0.0) or 0.0),
                    "ownership_counts": ownership_counts,
                },
                "queue": self.frame_queue.snapshot(),
                "per_camera": per_camera,
            }

    def ensure_camera_threads(self) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                return {"checked": 0, "restarted": 0, "restarted_cameras": []}

            checked = 0
            restarted_cameras: list[int] = []
            for camera_id, cfg in self._configs.items():
                if not bool(cfg.enabled):
                    continue
                checked += 1
                thread = self._threads.get(int(camera_id))
                if thread is not None and thread.is_alive():
                    continue

                stale_stop = self._stops.pop(int(camera_id), None)
                if stale_stop is not None:
                    stale_stop.set()
                self._threads.pop(int(camera_id), None)
                if self._start_camera_thread_if_owned_locked(int(camera_id)):
                    restarted_cameras.append(int(camera_id))

            if restarted_cameras:
                self._service_metrics["thread_restarts_total"] = int(
                    self._service_metrics.get("thread_restarts_total", 0) or 0
                ) + len(restarted_cameras)
                self._service_metrics["last_self_heal_at"] = utc_now_iso()

            return {
                "checked": int(checked),
                "restarted": len(restarted_cameras),
                "restarted_cameras": restarted_cameras,
            }

    def _start_camera_thread_locked(self, camera_id: int) -> None:
        stop_event = threading.Event()
        thread = threading.Thread(
            target=self._camera_loop,
            args=(camera_id, stop_event),
            name=f"ingest-cam-{camera_id}",
            daemon=True,
        )
        self._stops[camera_id] = stop_event
        self._threads[camera_id] = thread
        thread.start()

    def _start_camera_thread_if_owned_locked(self, camera_id: int) -> bool:
        cfg = self._configs.get(int(camera_id))
        metric = self._metrics.setdefault(int(camera_id), _CameraIngestionMetrics())
        if cfg is None or not bool(cfg.enabled):
            self._mark_ownership_disabled(metric)
            return False
        if self._claim_or_refresh_ownership(metric=metric, cfg=cfg, mode="claim") is None:
            self._set_health(metric, "standby", "camera_owned_by_other_runtime")
            return False
        self._start_camera_thread_locked(int(camera_id))
        return True

    def _stop_camera_thread_locked(self, camera_id: int) -> None:
        stop_event = self._stops.pop(int(camera_id), None)
        thread = self._threads.pop(int(camera_id), None)
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        metric = self._metrics.setdefault(int(camera_id), _CameraIngestionMetrics())
        self._release_ownership(metric=metric, camera_id=int(camera_id))

    def _camera_loop(self, camera_id: int, stop_event: threading.Event) -> None:
        last_emit_monotonic = 0.0
        last_ownership_heartbeat_monotonic = 0.0
        while not stop_event.is_set():
            with self._lock:
                if not self._running:
                    break
                cfg = self._configs.get(int(camera_id))
                metric = self._metrics.setdefault(int(camera_id), _CameraIngestionMetrics())
                if metric.current_backoff_ms <= 0:
                    metric.current_backoff_ms = max(10, int(cfg.retry_backoff_ms)) if cfg else 150
                if metric.health_changed_at is None:
                    metric.health_changed_at = utc_now_iso()

            if cfg is None:
                break
            if not cfg.enabled:
                self._release_ownership(metric=metric, camera_id=int(camera_id))
                self._set_health(metric, "disabled", "camera_disabled")
                time.sleep(self.idle_sleep_sec)
                continue

            try:
                frame = self.frame_reader(int(camera_id), str(cfg.source))
            except Exception as exc:
                self._record_read_error(
                    metric=metric,
                    cfg=cfg,
                    reason=str(exc),
                    is_exception=True,
                )
                next_heartbeat = self._claim_or_refresh_ownership(
                    metric=metric,
                    cfg=cfg,
                    mode="renew",
                    last_heartbeat_monotonic=last_ownership_heartbeat_monotonic,
                )
                if next_heartbeat is None:
                    self._set_health(metric, "standby", "camera_owned_by_other_runtime")
                    break
                last_ownership_heartbeat_monotonic = next_heartbeat
                continue

            if frame is None:
                self._record_read_error(
                    metric=metric,
                    cfg=cfg,
                    reason="frame_reader_returned_none",
                    is_exception=False,
                )
                next_heartbeat = self._claim_or_refresh_ownership(
                    metric=metric,
                    cfg=cfg,
                    mode="renew",
                    last_heartbeat_monotonic=last_ownership_heartbeat_monotonic,
                )
                if next_heartbeat is None:
                    self._set_health(metric, "standby", "camera_owned_by_other_runtime")
                    break
                last_ownership_heartbeat_monotonic = next_heartbeat
                continue

            next_heartbeat = self._claim_or_refresh_ownership(
                metric=metric,
                cfg=cfg,
                mode="renew",
                last_heartbeat_monotonic=last_ownership_heartbeat_monotonic,
            )
            if next_heartbeat is None:
                self._set_health(metric, "standby", "camera_owned_by_other_runtime")
                break
            last_ownership_heartbeat_monotonic = next_heartbeat

            metric.frames_read += 1
            self._record_read_success(metric=metric, cfg=cfg)
            now_mono = time.monotonic()
            interval_sec = max(0.01, cfg.sample_interval_ms / 1000.0)
            if (now_mono - last_emit_monotonic) < interval_sec:
                metric.frames_skipped_sampling += 1
                time.sleep(self.idle_sleep_sec)
                continue

            metric.last_sequence += 1
            task = FrameTask(
                camera_id=int(camera_id),
                source=str(cfg.source),
                frame=frame,
                captured_at=utc_now_iso(),
                sequence=metric.last_sequence,
                metadata=dict(cfg.metadata or {}),
            )
            ok = self.frame_queue.put(task, dedupe_key=f"camera:{camera_id}")
            if ok:
                metric.frames_enqueued += 1
                metric.last_frame_at = task.captured_at
                last_emit_monotonic = now_mono
            else:
                self._set_health(metric, "down", "frame_queue_closed")
                break

            time.sleep(self.idle_sleep_sec)

        with self._lock:
            metric = self._metrics.setdefault(int(camera_id), _CameraIngestionMetrics())
        self._release_ownership(metric=metric, camera_id=int(camera_id))

    @staticmethod
    def _compute_read_fps_30s(metric: _CameraIngestionMetrics) -> float:
        now = time.monotonic()
        window_sec = 30.0
        while metric.recent_success_monotonic and (now - metric.recent_success_monotonic[0]) > window_sec:
            metric.recent_success_monotonic.popleft()
        if len(metric.recent_success_monotonic) <= 1:
            return 0.0
        span = metric.recent_success_monotonic[-1] - metric.recent_success_monotonic[0]
        if span <= 0:
            return 0.0
        return round(float(len(metric.recent_success_monotonic) / span), 3)

    @staticmethod
    def _set_health(metric: _CameraIngestionMetrics, status: str, reason: Optional[str]) -> None:
        normalized = str(status or "starting").strip().lower()
        if normalized != metric.health_status:
            metric.health_status = normalized
            metric.health_changed_at = utc_now_iso()
        metric.health_reason = reason

    def _record_read_error(
        self,
        *,
        metric: _CameraIngestionMetrics,
        cfg: CameraIngestionConfig,
        reason: str,
        is_exception: bool,
    ) -> None:
        metric.read_errors += 1
        if is_exception:
            metric.read_exception_errors += 1
        else:
            metric.read_none_errors += 1
        metric.consecutive_read_errors += 1
        metric.reconnect_attempts += 1
        metric.last_error_at = utc_now_iso()
        metric.last_error = reason

        base_backoff = max(10, int(cfg.retry_backoff_ms))
        max_backoff = max(base_backoff, int(cfg.retry_backoff_max_ms))
        factor = max(1.1, float(cfg.retry_backoff_factor))
        current_backoff = max(base_backoff, int(metric.current_backoff_ms or base_backoff))
        next_backoff = min(max_backoff, int(current_backoff * factor))
        metric.current_backoff_ms = next_backoff

        degraded_threshold = max(1, int(cfg.degraded_error_threshold))
        down_threshold = max(degraded_threshold, int(cfg.down_error_threshold))
        if metric.consecutive_read_errors >= down_threshold:
            self._set_health(metric, "down", reason)
        elif metric.consecutive_read_errors >= degraded_threshold:
            self._set_health(metric, "degraded", reason)
        else:
            self._set_health(metric, "degraded", reason)

        time.sleep(max(0.01, next_backoff / 1000.0))

    def _record_read_success(self, *, metric: _CameraIngestionMetrics, cfg: CameraIngestionConfig) -> None:
        if metric.consecutive_read_errors > 0:
            metric.reconnect_recoveries += 1
        metric.consecutive_read_errors = 0
        metric.current_backoff_ms = max(10, int(cfg.retry_backoff_ms))
        now_iso = utc_now_iso()
        metric.last_success_at = now_iso
        metric.recent_success_monotonic.append(time.monotonic())
        self._set_health(metric, "up", "frame_read_ok")

    @staticmethod
    def _default_frame_reader(camera_id: int, source: str) -> Any:
        return StreamService.get_camera_frame(camera_id=camera_id, rtsp_url=source)

    def _claim_or_refresh_ownership(
        self,
        *,
        metric: _CameraIngestionMetrics,
        cfg: CameraIngestionConfig,
        mode: str,
        last_heartbeat_monotonic: float = 0.0,
    ) -> Optional[float]:
        if self.camera_lease_store is None:
            self._mark_ownership_disabled(metric)
            return last_heartbeat_monotonic

        now_monotonic = time.monotonic()
        normalized_mode = str(mode or "renew").strip().lower()
        if normalized_mode == "renew":
            if last_heartbeat_monotonic > 0 and (now_monotonic - last_heartbeat_monotonic) < self.ownership_heartbeat_interval_sec:
                return last_heartbeat_monotonic

        state = self.camera_lease_store.claim_or_renew(
            int(cfg.camera_id),
            owner_metadata={
                "source": str(cfg.source),
                "sample_interval_ms": int(cfg.sample_interval_ms),
                **dict(cfg.metadata or {}),
            },
        )
        self._apply_ownership_state(metric=metric, state=state)
        if state.claimed:
            if normalized_mode == "claim":
                metric.ownership_acquired_total += 1
            else:
                metric.ownership_renewed_total += 1
            return now_monotonic

        metric.ownership_denied_total += 1
        return None

    def _release_ownership(self, *, metric: _CameraIngestionMetrics, camera_id: int) -> None:
        if self.camera_lease_store is None:
            self._mark_ownership_disabled(metric)
            return
        released = self.camera_lease_store.release(int(camera_id))
        if released:
            metric.ownership_released_total += 1
            metric.ownership_status = "released"
            metric.ownership_owner_id = None
            metric.ownership_owner_role = None
            metric.ownership_claimed_at = None
            metric.ownership_last_heartbeat_at = None
            metric.ownership_expires_at = None
            return

        current_state = self.camera_lease_store.get(int(camera_id))
        if current_state is not None:
            self._apply_ownership_state(metric=metric, state=current_state)
            return

        metric.ownership_status = "released"
        metric.ownership_owner_id = None
        metric.ownership_owner_role = None
        metric.ownership_claimed_at = None
        metric.ownership_last_heartbeat_at = None
        metric.ownership_expires_at = None

    @staticmethod
    def _apply_ownership_state(*, metric: _CameraIngestionMetrics, state: Any) -> None:
        metric.ownership_status = "owned" if bool(getattr(state, "claimed", False)) else "standby"
        metric.ownership_owner_id = getattr(state, "owner_id", None)
        metric.ownership_owner_role = getattr(state, "owner_role", None)
        metric.ownership_claimed_at = getattr(state, "claimed_at", None)
        metric.ownership_last_heartbeat_at = getattr(state, "heartbeat_at", None)
        metric.ownership_expires_at = getattr(state, "lease_expires_at", None)

    @staticmethod
    def _mark_ownership_disabled(metric: _CameraIngestionMetrics) -> None:
        metric.ownership_status = "disabled"
        metric.ownership_owner_id = None
        metric.ownership_owner_role = None
        metric.ownership_claimed_at = None
        metric.ownership_last_heartbeat_at = None
        metric.ownership_expires_at = None
