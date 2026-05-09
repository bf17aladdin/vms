from __future__ import annotations

from vms.backend.services.scaling.frame_task_queue import BoundedTaskQueue, FrameTask


def _mk_task(camera_id: int, sequence: int) -> FrameTask:
    return FrameTask(
        camera_id=camera_id,
        source=f"cam-{camera_id}",
        frame={"camera_id": camera_id, "sequence": sequence},
        captured_at="2026-02-24T00:00:00+00:00",
        sequence=sequence,
    )


def test_dedupe_replaces_old_task_for_same_camera() -> None:
    queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=8)
    queue.put(_mk_task(camera_id=1, sequence=1), dedupe_key="camera:1")
    queue.put(_mk_task(camera_id=1, sequence=2), dedupe_key="camera:1")

    snapshot = queue.snapshot()
    assert snapshot["size"] == 1
    assert snapshot["dropped_replaced"] == 1

    task = queue.get(timeout=0.01)
    assert task is not None
    assert task.sequence == 2
    assert task.camera_id == 1


def test_overflow_drops_oldest_item() -> None:
    queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=2)
    queue.put(_mk_task(camera_id=1, sequence=1))
    queue.put(_mk_task(camera_id=2, sequence=2))
    queue.put(_mk_task(camera_id=3, sequence=3))

    snapshot = queue.snapshot()
    assert snapshot["size"] == 2
    assert snapshot["dropped_overflow"] == 1

    first = queue.get(timeout=0.01)
    second = queue.get(timeout=0.01)
    assert first is not None and second is not None
    assert first.sequence == 2
    assert second.sequence == 3
