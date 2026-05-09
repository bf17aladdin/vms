from __future__ import annotations

import threading
import time
from typing import Any, Dict

from .dead_letter_store import DeadLetterRecord, DeadLetterStore
from .frame_task_queue import BoundedTaskQueue, InferenceResultTask
from .vehicle_event_persistence_service import VehicleEventPersistenceService


class VehicleEventWriterWorker:
    """Consumes inference results and writes vehicle events asynchronously."""

    def __init__(
        self,
        *,
        input_queue: BoundedTaskQueue[InferenceResultTask],
        persistence_service: VehicleEventPersistenceService,
        dead_letter_store: DeadLetterStore | None = None,
        name: str = "vehicle-event-writer-worker",
        workers: int = 1,
        poll_timeout_sec: float = 0.25,
        max_retries: int = 2,
        retry_backoff_sec: float = 0.05,
    ):
        self.input_queue = input_queue
        self.persistence_service = persistence_service
        self.dead_letter_store = dead_letter_store
        self.name = name
        self.workers = max(1, int(workers))
        self.poll_timeout_sec = max(0.01, float(poll_timeout_sec))
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_sec = max(0.0, float(retry_backoff_sec))

        self._lock = threading.RLock()
        self._running = False
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._thread_seq = 0
        self._metrics: Dict[str, int] = {
            "processed": 0,
            "persisted": 0,
            "failed": 0,
            "skipped": 0,
            "retried": 0,
            "dead_lettered": 0,
            "thread_restarts": 0,
        }

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop.clear()
            self._threads = []
            for _ in range(self.workers):
                self._spawn_worker_thread_locked()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._stop.set()
            for thread in self._threads:
                if thread.is_alive():
                    thread.join(timeout=2.0)
            self._threads = []

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def snapshot_metrics(self) -> dict[str, Any]:
        with self._lock:
            alive_workers = sum(1 for thread in self._threads if thread.is_alive())
            return {
                "running": self._running,
                "workers": self.workers,
                "expected_workers": self.workers,
                "alive_workers": int(alive_workers),
                **self._metrics,
                "input_queue": self.input_queue.snapshot(),
            }

    def ensure_worker_threads(self) -> dict[str, int]:
        with self._lock:
            alive_threads = [thread for thread in self._threads if thread.is_alive()]
            if (not self._running) or self._stop.is_set():
                self._threads = alive_threads
                return {
                    "expected_workers": int(self.workers),
                    "alive_workers": len(alive_threads),
                    "restarted": 0,
                }

            restarted = 0
            self._threads = alive_threads
            while len(self._threads) < self.workers:
                self._spawn_worker_thread_locked()
                restarted += 1
            if restarted > 0:
                self._metrics["thread_restarts"] += int(restarted)
            return {
                "expected_workers": int(self.workers),
                "alive_workers": sum(1 for thread in self._threads if thread.is_alive()),
                "restarted": int(restarted),
            }

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            result = self.input_queue.get(timeout=self.poll_timeout_sec)
            if result is None:
                continue

            with self._lock:
                self._metrics["processed"] += 1

            if not result.success:
                with self._lock:
                    self._metrics["skipped"] += 1
                self._write_dead_letter(
                    result=result,
                    category="writer_skipped_inference_failure",
                    reason=str(result.error or "inference_failed"),
                )
                continue

            persisted = False
            for attempt in range(self.max_retries + 1):
                try:
                    event_id = self.persistence_service.persist(result)
                    if event_id is None:
                        with self._lock:
                            self._metrics["skipped"] += 1
                        self._write_dead_letter(
                            result=result,
                            category="writer_persist_none",
                            reason="persist_returned_none",
                        )
                    else:
                        with self._lock:
                            self._metrics["persisted"] += 1
                    persisted = True
                    break
                except Exception:
                    if attempt < self.max_retries:
                        with self._lock:
                            self._metrics["retried"] += 1
                        if self.retry_backoff_sec > 0:
                            time.sleep(self.retry_backoff_sec)
                        continue
                    with self._lock:
                        self._metrics["failed"] += 1
                    self._write_dead_letter(
                        result=result,
                        category="writer_persist_failed",
                        reason="persist_failed_max_retries",
                    )
                    break

            if not persisted and self.retry_backoff_sec > 0:
                time.sleep(self.retry_backoff_sec)

    def _write_dead_letter(
        self,
        *,
        result: InferenceResultTask,
        category: str,
        reason: str,
    ) -> None:
        if self.dead_letter_store is None:
            return
        payload = result.payload if isinstance(result.payload, dict) else {}
        try:
            self.dead_letter_store.write(
                DeadLetterRecord(
                    category=str(category),
                    reason=str(reason),
                    payload=dict(payload),
                    camera_id=int(result.camera_id),
                    sequence=int(result.sequence),
                    source=str(result.source),
                    created_at=time.time(),
                )
            )
            with self._lock:
                self._metrics["dead_lettered"] += 1
        except Exception:
            return

    def _spawn_worker_thread_locked(self) -> threading.Thread:
        self._thread_seq += 1
        thread = threading.Thread(
            target=self._run_loop,
            name=f"{self.name}-{self._thread_seq}",
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()
        return thread
