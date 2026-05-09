from __future__ import annotations

import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Generic, Optional, TypeVar

T = TypeVar("T")


class SqliteTaskQueue(Generic[T]):
    """
    SQLite-backed queue to support multi-process runtime topology.

    It preserves the same surface used by the in-memory queue:
    - put(item, dedupe_key=None) -> bool
    - get(timeout=None) -> Optional[item]
    - close()
    - size()
    - is_closed()
    - snapshot()
    """

    def __init__(
        self,
        *,
        db_path: str,
        topic: str,
        maxsize: int = 256,
        poll_interval_sec: float = 0.01,
        purge_on_start: bool = False,
        serializer: Optional[Callable[[T], bytes]] = None,
        deserializer: Optional[Callable[[bytes], T]] = None,
    ):
        self.db_path = Path(db_path)
        self.topic = str(topic)
        self.maxsize = max(1, int(maxsize))
        self.poll_interval_sec = max(0.001, float(poll_interval_sec))
        self._serializer = serializer or self._default_serialize
        self._deserializer = deserializer or self._default_deserialize
        self._closed = False
        self._lock = threading.RLock()
        self._metrics: Dict[str, int] = {
            "enqueued": 0,
            "dequeued": 0,
            "dropped_overflow": 0,
            "dropped_replaced": 0,
            "high_watermark": 0,
        }

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        if purge_on_start:
            self._purge_topic()

    def put(self, item: T, dedupe_key: Optional[str] = None) -> bool:
        with self._lock:
            if self._closed:
                return False

        payload = self._serializer(item)
        replaced = 0
        overflow = 0
        size_after = 0

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if dedupe_key:
                replaced = conn.execute(
                    "DELETE FROM scaling_queue_messages WHERE topic = ? AND dedupe_key = ?",
                    (self.topic, str(dedupe_key)),
                ).rowcount or 0

            size_before = int(
                conn.execute(
                    "SELECT COUNT(1) FROM scaling_queue_messages WHERE topic = ?",
                    (self.topic,),
                ).fetchone()[0]
            )
            if size_before >= self.maxsize:
                overflow = int(size_before - self.maxsize + 1)
                conn.execute(
                    """
                    DELETE FROM scaling_queue_messages
                    WHERE id IN (
                        SELECT id
                        FROM scaling_queue_messages
                        WHERE topic = ?
                        ORDER BY id ASC
                        LIMIT ?
                    )
                    """,
                    (self.topic, overflow),
                )

            conn.execute(
                """
                INSERT INTO scaling_queue_messages (topic, dedupe_key, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (self.topic, str(dedupe_key) if dedupe_key else None, payload, time.time()),
            )

            size_after = int(
                conn.execute(
                    "SELECT COUNT(1) FROM scaling_queue_messages WHERE topic = ?",
                    (self.topic,),
                ).fetchone()[0]
            )
            conn.execute("COMMIT")

        with self._lock:
            self._metrics["enqueued"] += 1
            self._metrics["dropped_replaced"] += int(replaced)
            self._metrics["dropped_overflow"] += int(max(0, overflow))
            self._metrics["high_watermark"] = max(self._metrics["high_watermark"], int(size_after))
        return True

    def get(self, timeout: Optional[float] = None) -> Optional[T]:
        if timeout is not None and float(timeout) <= 0:
            return self._try_get_once()

        deadline = None if timeout is None else (time.time() + float(timeout))
        while True:
            value = self._try_get_once()
            if value is not None:
                return value

            if self.is_closed() and self.size() <= 0:
                return None

            if deadline is not None and time.time() >= deadline:
                return None
            time.sleep(self.poll_interval_sec)

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def size(self) -> int:
        with self._connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(1) FROM scaling_queue_messages WHERE topic = ?",
                    (self.topic,),
                ).fetchone()[0]
            )

    def is_closed(self) -> bool:
        with self._lock:
            return self._closed

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                **self._metrics,
                "size": self.size(),
                "maxsize": self.maxsize,
            }

    def _try_get_once(self) -> Optional[T]:
        row = None
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT id, payload
                FROM scaling_queue_messages
                WHERE topic = ?
                ORDER BY id ASC
                LIMIT 1
                """,
                (self.topic,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute("DELETE FROM scaling_queue_messages WHERE id = ?", (int(row[0]),))
            conn.execute("COMMIT")

        with self._lock:
            self._metrics["dequeued"] += 1
        payload_raw = bytes(row[1])
        return self._deserializer(payload_raw)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scaling_queue_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    dedupe_key TEXT NULL,
                    payload BLOB NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scaling_queue_topic_id
                ON scaling_queue_messages (topic, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scaling_queue_topic_dedupe
                ON scaling_queue_messages (topic, dedupe_key)
                """
            )

    def _purge_topic(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM scaling_queue_messages WHERE topic = ?",
                (self.topic,),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @staticmethod
    def _default_serialize(item: T) -> bytes:
        return pickle.dumps(item, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def _default_deserialize(raw: bytes) -> T:
        return pickle.loads(raw)
