from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Optional

from .frame_task_queue import BoundedTaskQueue, FrameTask
from .multi_camera_ingestion_service import MultiCameraIngestionService

try:
    import psutil  # type: ignore

    _HAS_PSUTIL = True
except Exception:
    psutil = None
    _HAS_PSUTIL = False


@dataclass(slots=True)
class AdaptiveRateControllerConfig:
    enabled: bool = False
    poll_interval_sec: float = 2.0
    min_sample_interval_ms: int = 120
    max_sample_interval_ms: int = 500
    adjust_step_ms: int = 40
    queue_high_ratio: float = 0.35
    queue_low_ratio: float = 0.05
    cpu_high_pct: float = 85.0
    cpu_low_pct: float = 55.0


class AdaptiveRateController:
    """
    Dynamic sampling controller.

    It adjusts per-camera `sample_interval_ms` based on queue pressure and
    optional CPU pressure. Increasing sample interval lowers inference FPS.
    """

    def __init__(
        self,
        *,
        ingestion_service: MultiCameraIngestionService,
        frame_queue: BoundedTaskQueue[FrameTask],
        config: Optional[AdaptiveRateControllerConfig] = None,
        cpu_provider: Optional[Callable[[], Optional[float]]] = None,
        name: str = "adaptive-rate-controller",
    ):
        self.ingestion_service = ingestion_service
        self.frame_queue = frame_queue
        self.config = config or AdaptiveRateControllerConfig()
        self.cpu_provider = cpu_provider or self._default_cpu_provider
        self.name = name

        self._lock = threading.RLock()
        self._running = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._metrics = {
            "ticks": 0,
            "adjustments_up": 0,
            "adjustments_down": 0,
            "noops": 0,
            "last_reason": "init",
            "last_queue_ratio": 0.0,
            "last_cpu_percent": None,
            "last_tick_at": None,
            "per_camera_interval_ms": {},
        }

    def start(self) -> None:
        with self._lock:
            if self._running or not self.config.enabled:
                return
            self._running = True
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name=self.name,
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._stop.set()
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "config": asdict(self.config),
                **self._metrics,
            }

    def tick_once(self) -> None:
        if not self.config.enabled:
            return

        queue_snapshot = self.frame_queue.snapshot()
        size = int(queue_snapshot.get("size", 0))
        maxsize = max(1, int(queue_snapshot.get("maxsize", 1)))
        queue_ratio = float(size / maxsize)
        cpu_pct = self._safe_cpu_percent()
        action, reason = self._decide_action(queue_ratio=queue_ratio, cpu_pct=cpu_pct)

        adjusted_count = 0
        per_camera_interval_ms: dict[int, int] = {}
        cameras = self.ingestion_service.list_cameras()
        for cfg in cameras:
            camera_id = int(cfg.camera_id)
            current = int(cfg.sample_interval_ms)
            updated = current
            if action == "up":
                updated = min(int(self.config.max_sample_interval_ms), current + int(self.config.adjust_step_ms))
            elif action == "down":
                updated = max(int(self.config.min_sample_interval_ms), current - int(self.config.adjust_step_ms))

            if updated != current:
                self.ingestion_service.update_camera(camera_id, sample_interval_ms=updated)
                adjusted_count += 1
            per_camera_interval_ms[camera_id] = updated

        with self._lock:
            self._metrics["ticks"] += 1
            self._metrics["last_reason"] = reason
            self._metrics["last_queue_ratio"] = round(queue_ratio, 4)
            self._metrics["last_cpu_percent"] = None if cpu_pct is None else round(float(cpu_pct), 2)
            self._metrics["last_tick_at"] = time.time()
            self._metrics["per_camera_interval_ms"] = per_camera_interval_ms

            if action == "up":
                self._metrics["adjustments_up"] += adjusted_count
            elif action == "down":
                self._metrics["adjustments_down"] += adjusted_count
            else:
                self._metrics["noops"] += 1

    def _run_loop(self) -> None:
        poll = max(0.2, float(self.config.poll_interval_sec))
        while not self._stop.is_set():
            self.tick_once()
            self._stop.wait(poll)

    def _decide_action(self, *, queue_ratio: float, cpu_pct: Optional[float]) -> tuple[str, str]:
        queue_high = queue_ratio >= float(self.config.queue_high_ratio)
        queue_low = queue_ratio <= float(self.config.queue_low_ratio)
        cpu_high = (cpu_pct is not None) and (cpu_pct >= float(self.config.cpu_high_pct))
        cpu_low = (cpu_pct is None) or (cpu_pct <= float(self.config.cpu_low_pct))

        if queue_high or cpu_high:
            if queue_high and cpu_high:
                return "up", "queue_high_and_cpu_high"
            if queue_high:
                return "up", "queue_high"
            return "up", "cpu_high"

        if queue_low and cpu_low:
            return "down", "queue_low_and_cpu_ok"

        return "noop", "stable_zone"

    def _safe_cpu_percent(self) -> Optional[float]:
        try:
            value = self.cpu_provider()
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _default_cpu_provider() -> Optional[float]:
        if not _HAS_PSUTIL:
            return None
        # Non-blocking sample.
        return float(psutil.cpu_percent(interval=None))

