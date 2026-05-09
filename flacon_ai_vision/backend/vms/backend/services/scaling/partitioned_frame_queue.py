from __future__ import annotations

from typing import Any, Optional

from .frame_task_queue import FrameTask
from .runtime_tuning import stable_bucket_for_camera


class PartitionedFrameQueueWriter:
    """
    Write-only queue facade that routes frame tasks to a partition-specific queue.

    It is used by ingestion nodes so inference nodes can consume dedicated topics
    per partition instead of a single shared frame queue.
    """

    def __init__(self, *, queues: list[Any], partition_count: int, hash_salt: str = ""):
        if not queues:
            raise ValueError("PartitionedFrameQueueWriter requires at least one queue")
        self.queues = list(queues)
        self.partition_count = max(1, int(partition_count))
        self.hash_salt = str(hash_salt or "")

    def put(self, item: FrameTask, dedupe_key: Optional[str] = None) -> bool:
        queue = self.queues[self.partition_for_camera(int(item.camera_id))]
        return bool(queue.put(item, dedupe_key=dedupe_key))

    def close(self) -> None:
        for queue in self.queues:
            try:
                queue.close()
            except Exception:
                continue

    def size(self) -> int:
        total = 0
        for queue in self.queues:
            try:
                total += int(queue.size())
            except Exception:
                continue
        return total

    def is_closed(self) -> bool:
        closed = True
        for queue in self.queues:
            try:
                closed = closed and bool(queue.is_closed())
            except Exception:
                closed = False
        return closed

    def snapshot(self) -> dict[str, Any]:
        per_partition: dict[int, dict[str, Any]] = {}
        aggregate = {
            "enqueued": 0,
            "dequeued": 0,
            "dropped_overflow": 0,
            "dropped_replaced": 0,
            "high_watermark": 0,
            "size": 0,
            "maxsize": 0,
        }
        for index, queue in enumerate(self.queues):
            try:
                snap = dict(queue.snapshot())
            except Exception:
                snap = {}
            per_partition[index] = snap
            for key in aggregate.keys():
                aggregate[key] += int(snap.get(key, 0) or 0)

        aggregate["backend"] = "partitioned"
        aggregate["partition_count"] = int(self.partition_count)
        aggregate["per_partition"] = per_partition
        return aggregate

    def partition_for_camera(self, camera_id: int) -> int:
        return stable_bucket_for_camera(
            int(camera_id),
            self.partition_count,
            salt=self.hash_salt,
        )
