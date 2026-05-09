from __future__ import annotations

import threading
import time

from vms.backend.services.scaling.frame_task_queue import (
    BoundedTaskQueue,
    FrameTask,
    InferenceResultTask,
)
from vms.backend.services.scaling.dead_letter_store import InMemoryDeadLetterStore
from vms.backend.services.scaling.vehicle_inference_worker import VehicleInferenceWorker


def _mk_task(sequence: int) -> FrameTask:
    return FrameTask(
        camera_id=2,
        source="0",
        frame={"sequence": sequence},
        captured_at="2026-02-24T00:00:00+00:00",
        sequence=sequence,
    )


def test_inference_worker_processes_input_queue() -> None:
    input_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=32)
    output_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=32)

    def fake_inference(task: FrameTask) -> dict:
        return {
            "success": True,
            "camera_id": task.camera_id,
            "plate_number": f"TEST-{task.sequence}",
        }

    worker = VehicleInferenceWorker(
        input_queue=input_queue,
        output_queue=output_queue,
        inference_fn=fake_inference,
        workers=1,
        poll_timeout_sec=0.05,
    )

    for seq in range(1, 4):
        input_queue.put(_mk_task(sequence=seq))

    worker.start()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if output_queue.snapshot()["size"] >= 3:
            break
        time.sleep(0.02)
    worker.stop()

    metrics = worker.snapshot_metrics()
    assert metrics["processed"] >= 3
    assert metrics["failed"] == 0
    assert metrics["success"] >= 3
    assert metrics["per_camera"][2]["processed"] >= 3


def test_inference_worker_batches_tasks_with_batch_fn() -> None:
    input_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=64)
    output_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=64)
    batch_sizes: list[int] = []

    def fake_inference(task: FrameTask) -> dict:
        return {"success": True, "camera_id": task.camera_id}

    def fake_batch_inference(tasks: list[FrameTask]) -> list[dict]:
        batch_sizes.append(len(tasks))
        return [
            {
                "success": True,
                "camera_id": task.camera_id,
                "plate_number": f"BATCH-{task.sequence}",
            }
            for task in tasks
        ]

    worker = VehicleInferenceWorker(
        input_queue=input_queue,
        output_queue=output_queue,
        inference_fn=fake_inference,
        inference_batch_fn=fake_batch_inference,
        workers=1,
        poll_timeout_sec=0.05,
        batch_size=3,
        batch_max_wait_ms=25,
    )

    for seq in range(1, 6):
        input_queue.put(_mk_task(sequence=seq))

    worker.start()
    deadline = time.time() + 1.5
    while time.time() < deadline:
        if output_queue.snapshot()["size"] >= 5:
            break
        time.sleep(0.02)
    worker.stop()

    metrics = worker.snapshot_metrics()
    assert metrics["processed"] >= 5
    assert metrics["failed"] == 0
    assert metrics["batch_calls"] >= 2
    assert metrics["avg_batch_size"] > 1.0
    assert sum(batch_sizes) >= 5
    assert any(size > 1 for size in batch_sizes)


def test_inference_worker_batch_failure_marks_all_tasks_failed() -> None:
    input_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=16)
    output_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=16)

    def fake_inference(task: FrameTask) -> dict:
        return {"success": True, "camera_id": task.camera_id}

    def failing_batch_inference(tasks: list[FrameTask]) -> list[dict]:
        raise RuntimeError("batch_boom")

    worker = VehicleInferenceWorker(
        input_queue=input_queue,
        output_queue=output_queue,
        inference_fn=fake_inference,
        inference_batch_fn=failing_batch_inference,
        workers=1,
        poll_timeout_sec=0.05,
        batch_size=2,
        batch_max_wait_ms=20,
    )

    input_queue.put(_mk_task(sequence=1))
    input_queue.put(_mk_task(sequence=2))

    worker.start()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if output_queue.snapshot()["size"] >= 2:
            break
        time.sleep(0.02)
    worker.stop()

    metrics = worker.snapshot_metrics()
    assert metrics["processed"] >= 2
    assert metrics["failed"] >= 2
    assert metrics["batch_calls"] >= 1
    assert metrics["per_camera"][2]["failed"] >= 2


def test_inference_worker_exposes_per_camera_latency_metrics() -> None:
    input_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=32)
    output_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=32)

    def fake_inference(task: FrameTask) -> dict:
        return {"success": True, "camera_id": task.camera_id}

    worker = VehicleInferenceWorker(
        input_queue=input_queue,
        output_queue=output_queue,
        inference_fn=fake_inference,
        workers=1,
        poll_timeout_sec=0.05,
    )

    input_queue.put(
        FrameTask(
            camera_id=10,
            source="0",
            frame={},
            captured_at="2026-02-24T00:00:00+00:00",
            sequence=1,
        )
    )
    input_queue.put(
        FrameTask(
            camera_id=11,
            source="0",
            frame={},
            captured_at="2026-02-24T00:00:00+00:00",
            sequence=2,
        )
    )

    worker.start()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if output_queue.snapshot()["size"] >= 2:
            break
        time.sleep(0.02)
    worker.stop()

    metrics = worker.snapshot_metrics()
    assert 10 in metrics["per_camera"]
    assert 11 in metrics["per_camera"]
    assert metrics["per_camera"][10]["processed"] >= 1
    assert metrics["per_camera"][11]["processed"] >= 1


def test_inference_worker_writes_dead_letter_on_failed_inference() -> None:
    input_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=16)
    output_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=16)
    dead_letters = InMemoryDeadLetterStore()

    def fake_inference(task: FrameTask) -> dict:
        return {"success": False, "message": "forced_failure", "camera_id": task.camera_id}

    worker = VehicleInferenceWorker(
        input_queue=input_queue,
        output_queue=output_queue,
        inference_fn=fake_inference,
        dead_letter_store=dead_letters,
        workers=1,
        poll_timeout_sec=0.05,
    )

    input_queue.put(_mk_task(sequence=999))

    worker.start()
    deadline = time.time() + 1.0
    while time.time() < deadline:
        if worker.snapshot_metrics()["processed"] >= 1:
            break
        time.sleep(0.02)
    worker.stop()

    metrics = worker.snapshot_metrics()
    dead_snapshot = dead_letters.snapshot(limit=10)
    assert metrics["processed"] >= 1
    assert metrics["failed"] >= 1
    assert metrics["dead_lettered"] >= 1
    assert dead_snapshot["total"] >= 1
    assert dead_snapshot["by_category"]["inference_failed"] >= 1


def test_inference_worker_self_heals_dead_threads() -> None:
    input_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=16)
    output_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=16)

    def fake_inference(task: FrameTask) -> dict:
        return {"success": True, "camera_id": task.camera_id}

    worker = VehicleInferenceWorker(
        input_queue=input_queue,
        output_queue=output_queue,
        inference_fn=fake_inference,
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


def test_inference_worker_routes_same_camera_to_same_sticky_thread() -> None:
    input_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=32)
    output_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=32)
    seen_threads: dict[int, set[str]] = {}
    seen_lock = threading.Lock()

    def fake_inference(task: FrameTask) -> dict:
        with seen_lock:
            seen_threads.setdefault(int(task.camera_id), set()).add(threading.current_thread().name)
        time.sleep(0.01)
        return {"success": True, "camera_id": task.camera_id, "sequence": task.sequence}

    worker = VehicleInferenceWorker(
        input_queue=input_queue,
        output_queue=output_queue,
        inference_fn=fake_inference,
        workers=2,
        poll_timeout_sec=0.02,
        sticky_by_camera=True,
    )

    for sequence in range(1, 4):
        input_queue.put(
            FrameTask(
                camera_id=1,
                source="0",
                frame={"sequence": sequence},
                captured_at="2026-02-24T00:00:00+00:00",
                sequence=sequence,
            )
        )
        input_queue.put(
            FrameTask(
                camera_id=2,
                source="0",
                frame={"sequence": sequence},
                captured_at="2026-02-24T00:00:00+00:00",
                sequence=100 + sequence,
            )
        )

    worker.start()
    deadline = time.time() + 1.5
    while time.time() < deadline:
        if worker.snapshot_metrics()["processed"] >= 6:
            break
        time.sleep(0.02)
    worker.stop()

    metrics = worker.snapshot_metrics()
    assert metrics["dispatcher_running"] is False
    assert len(seen_threads.get(1, set())) == 1
    assert len(seen_threads.get(2, set())) == 1
