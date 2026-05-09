from __future__ import annotations

import threading
import time

from vms.backend.services.scaling.dead_letter_store import InMemoryDeadLetterStore
from vms.backend.services.scaling.frame_task_queue import BoundedTaskQueue, InferenceResultTask
from vms.backend.services.scaling.vehicle_event_writer_worker import VehicleEventWriterWorker


class _FakePersistenceService:
    def __init__(self, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls = 0
        self.saved: list[dict] = []

    def persist(self, result: InferenceResultTask):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("transient error")
        payload = result.payload or {}
        self.saved.append(payload)
        return len(self.saved)


class _NonePersistenceService:
    def __init__(self) -> None:
        self.calls = 0

    def persist(self, result: InferenceResultTask):
        self.calls += 1
        return None


def _success_result() -> InferenceResultTask:
    return InferenceResultTask(
        camera_id=5,
        source="0",
        captured_at="2026-02-24T00:00:00+00:00",
        produced_at="2026-02-24T00:00:01+00:00",
        sequence=1,
        success=True,
        payload={"camera_id": 5, "plate_number": "AA-123"},
    )


def _failed_result() -> InferenceResultTask:
    return InferenceResultTask(
        camera_id=5,
        source="0",
        captured_at="2026-02-24T00:00:00+00:00",
        produced_at="2026-02-24T00:00:01+00:00",
        sequence=2,
        success=False,
        payload={"camera_id": 5},
        error="inference_failed",
    )


def test_event_writer_skips_failed_results() -> None:
    queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=16)
    persistence = _FakePersistenceService()
    worker = VehicleEventWriterWorker(
        input_queue=queue,
        persistence_service=persistence,
        workers=1,
        poll_timeout_sec=0.05,
        max_retries=0,
    )

    queue.put(_success_result())
    queue.put(_failed_result())
    worker.start()
    time.sleep(0.20)
    worker.stop()

    metrics = worker.snapshot_metrics()
    assert metrics["processed"] >= 2
    assert metrics["persisted"] >= 1
    assert metrics["skipped"] >= 1
    assert len(persistence.saved) >= 1


def test_event_writer_retries_transient_failure() -> None:
    queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=16)
    persistence = _FakePersistenceService(fail_first=True)
    worker = VehicleEventWriterWorker(
        input_queue=queue,
        persistence_service=persistence,
        workers=1,
        poll_timeout_sec=0.05,
        max_retries=1,
        retry_backoff_sec=0.01,
    )

    queue.put(_success_result())
    worker.start()
    time.sleep(0.25)
    worker.stop()

    metrics = worker.snapshot_metrics()
    assert metrics["persisted"] >= 1
    assert metrics["retried"] >= 1


def test_event_writer_writes_dead_letters_for_skip_and_persist_none() -> None:
    queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=16)
    dead_letters = InMemoryDeadLetterStore()
    persistence = _NonePersistenceService()
    worker = VehicleEventWriterWorker(
        input_queue=queue,
        persistence_service=persistence,
        dead_letter_store=dead_letters,
        workers=1,
        poll_timeout_sec=0.05,
        max_retries=0,
    )

    queue.put(_failed_result())
    queue.put(_success_result())
    worker.start()
    time.sleep(0.30)
    worker.stop()

    metrics = worker.snapshot_metrics()
    dead_snapshot = dead_letters.snapshot(limit=10)
    assert metrics["processed"] >= 2
    assert metrics["dead_lettered"] >= 2
    assert dead_snapshot["total"] >= 2
    assert dead_snapshot["by_category"]["writer_skipped_inference_failure"] >= 1
    assert dead_snapshot["by_category"]["writer_persist_none"] >= 1


def test_event_writer_self_heals_dead_threads() -> None:
    queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=16)
    persistence = _FakePersistenceService()
    worker = VehicleEventWriterWorker(
        input_queue=queue,
        persistence_service=persistence,
        workers=2,
        poll_timeout_sec=0.05,
    )

    worker.start()
    time.sleep(0.1)
    with worker._lock:
        alive = [thread for thread in worker._threads if thread.is_alive()]
        worker._threads = alive[:1]
        worker._threads.append(threading.Thread(target=lambda: None, daemon=True))

    healed = worker.ensure_worker_threads()
    worker.stop()

    metrics = worker.snapshot_metrics()
    assert healed["restarted"] >= 1
    assert metrics["thread_restarts"] >= 1
