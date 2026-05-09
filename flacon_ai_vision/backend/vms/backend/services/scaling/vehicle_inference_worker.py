from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

from .dead_letter_store import DeadLetterRecord, DeadLetterStore
from .frame_task_queue import BoundedTaskQueue, FrameTask, InferenceResultTask, utc_now_iso
from .runtime_tuning import stable_bucket_for_camera


class VehicleInferenceWorker:
    """Consumes frame tasks and produces inference results asynchronously."""

    def __init__(
        self,
        *,
        input_queue: BoundedTaskQueue[FrameTask],
        output_queue: BoundedTaskQueue[InferenceResultTask],
        inference_fn: Callable[[FrameTask], dict[str, Any]],
        inference_batch_fn: Optional[Callable[[list[FrameTask]], list[dict[str, Any]]]] = None,
        dead_letter_store: Optional[DeadLetterStore] = None,
        name: str = "vehicle-inference-worker",
        workers: int = 1,
        poll_timeout_sec: float = 0.25,
        batch_size: int = 1,
        batch_max_wait_ms: float = 0.0,
        sticky_by_camera: bool = False,
        local_queue_maxsize: int = 256,
        sticky_hash_salt: str = "",
        ownership_lease_store: Optional[Any] = None,
        ownership_resource_id: Optional[int] = None,
        ownership_heartbeat_interval_sec: float = 2.0,
    ):
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.inference_fn = inference_fn
        self.inference_batch_fn = inference_batch_fn
        self.dead_letter_store = dead_letter_store
        self.name = name
        self.workers = max(1, int(workers))
        self.poll_timeout_sec = max(0.01, float(poll_timeout_sec))
        self.batch_size = max(1, int(batch_size))
        self.batch_max_wait_sec = max(0.0, float(batch_max_wait_ms) / 1000.0)
        self.sticky_by_camera = bool(sticky_by_camera)
        self.local_queue_maxsize = max(16, int(local_queue_maxsize))
        self.sticky_hash_salt = str(sticky_hash_salt or "")
        self.ownership_lease_store = ownership_lease_store
        self.ownership_resource_id = max(1, int(ownership_resource_id or 1))
        self.ownership_heartbeat_interval_sec = max(0.1, float(ownership_heartbeat_interval_sec))
        self._dispatcher_enabled = bool(self.sticky_by_camera or self.ownership_lease_store is not None)

        self._lock = threading.RLock()
        self._running = False
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._dispatcher_thread: Optional[threading.Thread] = None
        self._thread_seq = 0
        self._worker_queues: list[BoundedTaskQueue[FrameTask]] = []
        self._metrics: Dict[str, float] = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "latency_ms_total": 0.0,
            "latency_ms_max": 0.0,
            "batch_calls": 0,
            "batch_tasks_total": 0,
            "batch_tasks_max": 0,
            "batch_partial": 0,
            "dead_lettered": 0,
            "thread_restarts": 0,
        }
        self._per_camera_metrics: Dict[int, Dict[str, float]] = {}
        self._ownership: Dict[str, Any] = {
            "enabled": bool(self.ownership_lease_store is not None),
            "resource_id": int(self.ownership_resource_id),
            "status": "disabled" if self.ownership_lease_store is None else "starting",
            "owner_id": getattr(self.ownership_lease_store, "owner_id", None),
            "owner_role": getattr(self.ownership_lease_store, "owner_role", None),
            "claimed_at": None,
            "last_heartbeat_at": None,
            "lease_expires_at": None,
            "acquired_total": 0,
            "renewed_total": 0,
            "denied_total": 0,
            "released_total": 0,
        }

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._stop.clear()
            self._threads = []
            self._dispatcher_thread = None
            self._worker_queues = []

            if self._dispatcher_enabled:
                for slot in range(self.workers):
                    queue = BoundedTaskQueue[FrameTask](maxsize=self.local_queue_maxsize)
                    self._worker_queues.append(queue)
                    self._spawn_worker_thread_locked(task_queue=queue, slot=slot)
                self._spawn_dispatcher_thread_locked()
                return

            for _ in range(self.workers):
                self._spawn_worker_thread_locked(task_queue=None, slot=None)

    def stop(self) -> None:
        with self._lock:
            self._running = False
            self._stop.set()
            dispatcher = self._dispatcher_thread
            threads = list(self._threads)
            worker_queues = list(self._worker_queues)
            self._dispatcher_thread = None

        for queue in worker_queues:
            queue.close()

        if dispatcher is not None and dispatcher.is_alive():
            dispatcher.join(timeout=2.0)

        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=2.0)

        with self._lock:
            self._threads = []
            self._worker_queues = []

        self._release_ownership()

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def snapshot_metrics(self) -> dict[str, Any]:
        with self._lock:
            alive_workers = sum(1 for thread in self._threads if thread.is_alive())
            processed = int(self._metrics["processed"])
            avg_latency = (
                float(self._metrics["latency_ms_total"]) / processed
                if processed > 0
                else 0.0
            )
            batch_calls = int(self._metrics["batch_calls"])
            avg_batch_size = (
                float(self._metrics["batch_tasks_total"]) / batch_calls
                if batch_calls > 0
                else 0.0
            )
            per_camera = {
                camera_id: {
                    "processed": int(values.get("processed", 0)),
                    "success": int(values.get("success", 0)),
                    "failed": int(values.get("failed", 0)),
                    "avg_latency_ms": round(
                        float(values.get("latency_ms_total", 0.0)) / max(1, int(values.get("processed", 0))),
                        3,
                    ),
                    "max_latency_ms": round(float(values.get("latency_ms_max", 0.0)), 3),
                }
                for camera_id, values in sorted(self._per_camera_metrics.items(), key=lambda item: item[0])
            }
            worker_queues = {
                slot: queue.snapshot()
                for slot, queue in enumerate(self._worker_queues)
            }
            return {
                "running": self._running,
                "workers": self.workers,
                "expected_workers": self.workers,
                "alive_workers": int(alive_workers),
                "dispatcher_running": bool(self._dispatcher_thread is not None and self._dispatcher_thread.is_alive()),
                "sticky_by_camera": bool(self.sticky_by_camera),
                "batch_size": self.batch_size,
                "batch_max_wait_ms": round(self.batch_max_wait_sec * 1000.0, 3),
                "batch_enabled": bool(self.batch_size > 1 and self.inference_batch_fn is not None),
                "processed": processed,
                "success": int(self._metrics["success"]),
                "failed": int(self._metrics["failed"]),
                "avg_latency_ms": round(avg_latency, 3),
                "max_latency_ms": round(float(self._metrics["latency_ms_max"]), 3),
                "batch_calls": batch_calls,
                "avg_batch_size": round(avg_batch_size, 3),
                "max_batch_size": int(self._metrics["batch_tasks_max"]),
                "partial_batches": int(self._metrics["batch_partial"]),
                "dead_lettered": int(self._metrics["dead_lettered"]),
                "thread_restarts": int(self._metrics["thread_restarts"]),
                "per_camera": per_camera,
                "input_queue": self.input_queue.snapshot(),
                "output_queue": self.output_queue.snapshot(),
                "local_worker_queues": worker_queues,
                "ownership": dict(self._ownership),
            }

    def ensure_worker_threads(self) -> dict[str, int]:
        with self._lock:
            alive_threads = [thread for thread in self._threads if thread.is_alive()]
            self._threads = alive_threads
            if (not self._running) or self._stop.is_set():
                return {
                    "expected_workers": int(self.workers),
                    "alive_workers": len(alive_threads),
                    "restarted": 0,
                    "dispatcher_restarted": 0,
                }

            restarted_workers = 0
            dispatcher_restarted = 0
            if self._dispatcher_enabled:
                alive_slots = {
                    int(getattr(thread, "_sticky_slot"))
                    for thread in alive_threads
                    if getattr(thread, "_sticky_slot", None) is not None
                }
                while len(self._worker_queues) < self.workers:
                    self._worker_queues.append(BoundedTaskQueue[FrameTask](maxsize=self.local_queue_maxsize))
                for slot in range(self.workers):
                    if slot in alive_slots:
                        continue
                    self._spawn_worker_thread_locked(task_queue=self._worker_queues[slot], slot=slot)
                    restarted_workers += 1
                if self._dispatcher_thread is None or not self._dispatcher_thread.is_alive():
                    self._spawn_dispatcher_thread_locked()
                    dispatcher_restarted = 1
            else:
                while len(self._threads) < self.workers:
                    self._spawn_worker_thread_locked(task_queue=None, slot=None)
                    restarted_workers += 1

            restarted_total = int(restarted_workers + dispatcher_restarted)
            if restarted_total > 0:
                self._metrics["thread_restarts"] += restarted_total
            return {
                "expected_workers": int(self.workers),
                "alive_workers": sum(1 for thread in self._threads if thread.is_alive()),
                "restarted": restarted_total,
                "dispatcher_restarted": int(dispatcher_restarted),
            }

    def _run_loop(self, task_queue: Optional[BoundedTaskQueue[FrameTask]] = None) -> None:
        queue = task_queue or self.input_queue
        while not self._stop.is_set():
            first_task = queue.get(timeout=self.poll_timeout_sec)
            if first_task is None:
                continue

            batch = self._collect_batch(first_task, queue)
            batch_started = time.perf_counter()
            payloads = self._run_batch_inference(batch)
            batch_latency_ms = (time.perf_counter() - batch_started) * 1000.0
            per_task_latency_ms = batch_latency_ms / max(1, len(batch))

            for task, payload in zip(batch, payloads):
                safe_payload = payload if isinstance(payload, dict) else {
                    "success": False,
                    "message": "inference_fn_non_dict_response",
                }
                success = bool(safe_payload.get("success", False))
                error = None if success else str(safe_payload.get("message") or "")
                result = InferenceResultTask(
                    camera_id=task.camera_id,
                    source=task.source,
                    captured_at=task.captured_at,
                    produced_at=utc_now_iso(),
                    sequence=task.sequence,
                    success=success,
                    payload=safe_payload,
                    error=error or None,
                    latency_ms=per_task_latency_ms,
                )
                self.output_queue.put(result)
                if not success:
                    self._write_dead_letter(task=task, payload=safe_payload, reason=error or "inference_failed")
                self._record_metrics(
                    success=success,
                    latency_ms=per_task_latency_ms,
                    camera_id=int(task.camera_id),
                )
            self._record_batch_metrics(batch_size=len(batch))

    def _run_dispatcher_loop(self) -> None:
        last_ownership_heartbeat_monotonic = 0.0
        retry_sleep_sec = max(0.05, min(self.ownership_heartbeat_interval_sec, self.poll_timeout_sec))
        while not self._stop.is_set():
            next_heartbeat = self._claim_or_refresh_ownership(
                last_heartbeat_monotonic=last_ownership_heartbeat_monotonic,
            )
            if next_heartbeat is None:
                last_ownership_heartbeat_monotonic = 0.0
                self._drain_local_worker_queues()
                self._stop.wait(retry_sleep_sec)
                continue
            last_ownership_heartbeat_monotonic = next_heartbeat

            timeout = self.poll_timeout_sec
            if self.ownership_lease_store is not None:
                elapsed = max(0.0, time.monotonic() - last_ownership_heartbeat_monotonic)
                heartbeat_remaining = max(0.01, self.ownership_heartbeat_interval_sec - elapsed)
                timeout = min(timeout, heartbeat_remaining)

            task = self.input_queue.get(timeout=timeout)
            if task is None:
                continue
            queue = self._worker_queues[self._worker_slot(int(task.camera_id))]
            queue.put(task, dedupe_key=f"camera:{int(task.camera_id)}")

        self._release_ownership()

    def _collect_batch(
        self,
        first_task: FrameTask,
        queue: BoundedTaskQueue[FrameTask],
    ) -> list[FrameTask]:
        batch: list[FrameTask] = [first_task]
        if self.batch_size <= 1:
            return batch

        deadline = (
            time.perf_counter() + self.batch_max_wait_sec
            if self.batch_max_wait_sec > 0
            else None
        )
        while len(batch) < self.batch_size:
            timeout = 0.0
            if deadline is not None:
                timeout = max(0.0, deadline - time.perf_counter())
                if timeout <= 0:
                    break
            item = queue.get(timeout=timeout)
            if item is None:
                break
            batch.append(item)
        return batch

    def _run_batch_inference(self, batch: list[FrameTask]) -> list[dict[str, Any]]:
        if not batch:
            return []

        use_batch_fn = bool(self.batch_size > 1 and self.inference_batch_fn is not None)
        if use_batch_fn:
            try:
                outputs = self.inference_batch_fn(batch)
                if not isinstance(outputs, list):
                    raise RuntimeError("inference_batch_fn_non_list_response")
                if len(outputs) != len(batch):
                    raise RuntimeError("inference_batch_fn_invalid_output_size")
                return [
                    output if isinstance(output, dict) else {
                        "success": False,
                        "message": "inference_batch_fn_non_dict_item",
                    }
                    for output in outputs
                ]
            except Exception as exc:
                msg = str(exc)
                return [{"success": False, "message": msg} for _ in batch]

        payloads: list[dict[str, Any]] = []
        for task in batch:
            try:
                payload = self.inference_fn(task)
                if not isinstance(payload, dict):
                    payload = {"success": False, "message": "inference_fn_non_dict_response"}
            except Exception as exc:
                payload = {"success": False, "message": str(exc)}
            payloads.append(payload)
        return payloads

    def _record_metrics(self, *, success: bool, latency_ms: float, camera_id: int) -> None:
        with self._lock:
            self._metrics["processed"] += 1
            if success:
                self._metrics["success"] += 1
            else:
                self._metrics["failed"] += 1
            self._metrics["latency_ms_total"] += float(latency_ms)
            self._metrics["latency_ms_max"] = max(
                float(self._metrics["latency_ms_max"]),
                float(latency_ms),
            )
            per_camera = self._per_camera_metrics.setdefault(
                int(camera_id),
                {
                    "processed": 0.0,
                    "success": 0.0,
                    "failed": 0.0,
                    "latency_ms_total": 0.0,
                    "latency_ms_max": 0.0,
                },
            )
            per_camera["processed"] += 1
            if success:
                per_camera["success"] += 1
            else:
                per_camera["failed"] += 1
            per_camera["latency_ms_total"] += float(latency_ms)
            per_camera["latency_ms_max"] = max(
                float(per_camera["latency_ms_max"]),
                float(latency_ms),
            )

    def _record_batch_metrics(self, *, batch_size: int) -> None:
        with self._lock:
            self._metrics["batch_calls"] += 1
            self._metrics["batch_tasks_total"] += int(batch_size)
            self._metrics["batch_tasks_max"] = max(
                int(self._metrics["batch_tasks_max"]),
                int(batch_size),
            )
            if self.batch_size > 1 and int(batch_size) < self.batch_size:
                self._metrics["batch_partial"] += 1

    def _write_dead_letter(self, *, task: FrameTask, payload: dict[str, Any], reason: str) -> None:
        if self.dead_letter_store is None:
            return
        try:
            self.dead_letter_store.write(
                DeadLetterRecord(
                    category="inference_failed",
                    reason=str(reason or "inference_failed"),
                    payload=payload,
                    camera_id=int(task.camera_id),
                    sequence=int(task.sequence),
                    source=str(task.source),
                    created_at=time.time(),
                )
            )
            with self._lock:
                self._metrics["dead_lettered"] += 1
        except Exception:
            return

    def _spawn_worker_thread_locked(
        self,
        *,
        task_queue: Optional[BoundedTaskQueue[FrameTask]],
        slot: Optional[int],
    ) -> threading.Thread:
        self._thread_seq += 1
        name_suffix = f"-slot-{slot}" if slot is not None else ""
        thread = threading.Thread(
            target=self._run_loop,
            args=(task_queue,),
            name=f"{self.name}-{self._thread_seq}{name_suffix}",
            daemon=True,
        )
        if slot is not None:
            setattr(thread, "_sticky_slot", int(slot))
        self._threads.append(thread)
        thread.start()
        return thread

    def _spawn_dispatcher_thread_locked(self) -> threading.Thread:
        self._thread_seq += 1
        thread = threading.Thread(
            target=self._run_dispatcher_loop,
            name=f"{self.name}-dispatcher-{self._thread_seq}",
            daemon=True,
        )
        self._dispatcher_thread = thread
        thread.start()
        return thread

    def _worker_slot(self, camera_id: int) -> int:
        return stable_bucket_for_camera(
            int(camera_id),
            self.workers,
            salt=self.sticky_hash_salt,
        )

    def _claim_or_refresh_ownership(self, *, last_heartbeat_monotonic: float) -> Optional[float]:
        if self.ownership_lease_store is None:
            self._mark_ownership_disabled()
            return time.monotonic()

        now_monotonic = time.monotonic()
        if last_heartbeat_monotonic > 0 and (
            now_monotonic - last_heartbeat_monotonic
        ) < self.ownership_heartbeat_interval_sec:
            return last_heartbeat_monotonic

        state = self.ownership_lease_store.claim_or_renew(
            int(self.ownership_resource_id),
            owner_metadata={
                "workers": int(self.workers),
                "sticky_by_camera": bool(self.sticky_by_camera),
                "batch_size": int(self.batch_size),
                "sticky_hash_salt": self.sticky_hash_salt,
            },
        )
        self._apply_ownership_state(state)
        with self._lock:
            if bool(getattr(state, "claimed", False)):
                if last_heartbeat_monotonic > 0:
                    self._ownership["renewed_total"] = int(self._ownership.get("renewed_total", 0) or 0) + 1
                else:
                    self._ownership["acquired_total"] = int(self._ownership.get("acquired_total", 0) or 0) + 1
                return now_monotonic

            self._ownership["denied_total"] = int(self._ownership.get("denied_total", 0) or 0) + 1
        return None

    def _release_ownership(self) -> None:
        if self.ownership_lease_store is None:
            self._mark_ownership_disabled()
            return
        released = self.ownership_lease_store.release(int(self.ownership_resource_id))
        with self._lock:
            if released:
                self._ownership["released_total"] = int(self._ownership.get("released_total", 0) or 0) + 1
                self._ownership["status"] = "released"
                self._ownership["owner_id"] = None
                self._ownership["owner_role"] = None
                self._ownership["claimed_at"] = None
                self._ownership["last_heartbeat_at"] = None
                self._ownership["lease_expires_at"] = None
                return

        current_state = self.ownership_lease_store.get(int(self.ownership_resource_id))
        if current_state is not None:
            self._apply_ownership_state(current_state)
            return

        with self._lock:
            self._ownership["status"] = "released"
            self._ownership["owner_id"] = None
            self._ownership["owner_role"] = None
            self._ownership["claimed_at"] = None
            self._ownership["last_heartbeat_at"] = None
            self._ownership["lease_expires_at"] = None

    def _apply_ownership_state(self, state: Any) -> None:
        with self._lock:
            self._ownership["enabled"] = True
            self._ownership["status"] = "owned" if bool(getattr(state, "claimed", False)) else "standby"
            self._ownership["owner_id"] = getattr(state, "owner_id", None)
            self._ownership["owner_role"] = getattr(state, "owner_role", None)
            self._ownership["claimed_at"] = getattr(state, "claimed_at", None)
            self._ownership["last_heartbeat_at"] = getattr(state, "heartbeat_at", None)
            self._ownership["lease_expires_at"] = getattr(state, "lease_expires_at", None)

    def _mark_ownership_disabled(self) -> None:
        with self._lock:
            self._ownership["enabled"] = False
            self._ownership["status"] = "disabled"
            self._ownership["owner_id"] = None
            self._ownership["owner_role"] = None
            self._ownership["claimed_at"] = None
            self._ownership["last_heartbeat_at"] = None
            self._ownership["lease_expires_at"] = None

    def _drain_local_worker_queues(self) -> None:
        for queue in list(self._worker_queues):
            while True:
                task = queue.get(timeout=0.0)
                if task is None:
                    break
