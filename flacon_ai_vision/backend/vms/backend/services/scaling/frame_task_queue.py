from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Condition
from typing import Any, Deque, Dict, Generic, Optional, TypeVar

T = TypeVar("T")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class FrameTask:
    camera_id: int
    source: str
    frame: Any
    captured_at: str
    sequence: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InferenceResultTask:
    camera_id: int
    source: str
    captured_at: str
    produced_at: str
    sequence: int
    success: bool
    payload: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None


class BoundedTaskQueue(Generic[T]):
    """
    Thread-safe bounded queue with optional dedup-by-key.

    Designed for high-frequency camera workloads where keeping only
    the latest task per camera can prevent queue backlog explosions.
    """

    def __init__(self, maxsize: int = 256):
        self.maxsize = max(1, int(maxsize))
        self._items: Deque[T] = deque()
        self._keys: Deque[Optional[str]] = deque()
        self._closed = False
        self._cv = Condition()
        self._metrics: Dict[str, int] = {
            "enqueued": 0,
            "dequeued": 0,
            "dropped_overflow": 0,
            "dropped_replaced": 0,
            "high_watermark": 0,
        }

    def put(self, item: T, dedupe_key: Optional[str] = None) -> bool:
        """
        Add a queue item.

        Returns False only when queue is closed.
        """
        with self._cv:
            if self._closed:
                return False

            if dedupe_key:
                self._drop_existing_key_locked(dedupe_key)

            if len(self._items) >= self.maxsize:
                self._items.popleft()
                self._keys.popleft()
                self._metrics["dropped_overflow"] += 1

            self._items.append(item)
            self._keys.append(dedupe_key)
            self._metrics["enqueued"] += 1
            self._metrics["high_watermark"] = max(
                self._metrics["high_watermark"],
                len(self._items),
            )
            self._cv.notify()
            return True

    def get(self, timeout: Optional[float] = None) -> Optional[T]:
        with self._cv:
            if timeout is None:
                while not self._items and not self._closed:
                    self._cv.wait()
            else:
                if timeout <= 0:
                    return self._pop_locked()
                end_at = datetime.now().timestamp() + timeout
                while not self._items and not self._closed:
                    remaining = end_at - datetime.now().timestamp()
                    if remaining <= 0:
                        break
                    self._cv.wait(remaining)

            return self._pop_locked()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    def size(self) -> int:
        with self._cv:
            return len(self._items)

    def is_closed(self) -> bool:
        with self._cv:
            return self._closed

    def snapshot(self) -> dict[str, int]:
        with self._cv:
            return {
                **self._metrics,
                "size": len(self._items),
                "maxsize": self.maxsize,
            }

    def _drop_existing_key_locked(self, dedupe_key: str) -> None:
        if not self._items:
            return

        kept_items: Deque[T] = deque()
        kept_keys: Deque[Optional[str]] = deque()
        replaced = 0

        for queued_item, queued_key in zip(self._items, self._keys):
            if queued_key == dedupe_key:
                replaced += 1
                continue
            kept_items.append(queued_item)
            kept_keys.append(queued_key)

        if replaced:
            self._items = kept_items
            self._keys = kept_keys
            self._metrics["dropped_replaced"] += replaced

    def _pop_locked(self) -> Optional[T]:
        if not self._items:
            return None
        item = self._items.popleft()
        self._keys.popleft()
        self._metrics["dequeued"] += 1
        return item
