from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol


@dataclass(slots=True)
class DeadLetterRecord:
    category: str
    reason: str
    payload: dict[str, Any]
    camera_id: Optional[int] = None
    sequence: Optional[int] = None
    source: Optional[str] = None
    created_at: float = 0.0


class DeadLetterStore(Protocol):
    def write(self, record: DeadLetterRecord) -> Optional[int]:
        ...

    def snapshot(self, *, limit: int = 20) -> dict[str, Any]:
        ...


class InMemoryDeadLetterStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: list[dict[str, Any]] = []
        self._next_id = 1

    def write(self, record: DeadLetterRecord) -> Optional[int]:
        with self._lock:
            created_at = float(record.created_at or time.time())
            row = {
                "id": self._next_id,
                "category": str(record.category),
                "reason": str(record.reason),
                "payload": dict(record.payload or {}),
                "camera_id": int(record.camera_id) if record.camera_id is not None else None,
                "sequence": int(record.sequence) if record.sequence is not None else None,
                "source": str(record.source) if record.source is not None else None,
                "created_at": created_at,
            }
            self._next_id += 1
            self._records.append(row)
            return int(row["id"])

    def snapshot(self, *, limit: int = 20) -> dict[str, Any]:
        with self._lock:
            total = len(self._records)
            by_category: dict[str, int] = {}
            for row in self._records:
                key = str(row.get("category", "unknown"))
                by_category[key] = by_category.get(key, 0) + 1
            recent = list(reversed(self._records[-max(1, int(limit)) :]))
            return {
                "backend": "memory",
                "total": total,
                "by_category": by_category,
                "recent": recent,
            }


class SqliteDeadLetterStore:
    def __init__(
        self,
        *,
        db_path: str,
        namespace: str = "default",
    ):
        self.db_path = Path(db_path)
        self.namespace = str(namespace or "default")
        self._lock = threading.RLock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def write(self, record: DeadLetterRecord) -> Optional[int]:
        created_at = float(record.created_at or time.time())
        payload_json = _safe_json(record.payload or {})
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO scaling_dead_letters (
                    namespace, category, reason, payload_json,
                    camera_id, sequence, source, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.namespace,
                    str(record.category),
                    str(record.reason),
                    payload_json,
                    int(record.camera_id) if record.camera_id is not None else None,
                    int(record.sequence) if record.sequence is not None else None,
                    str(record.source) if record.source is not None else None,
                    created_at,
                ),
            )
            row_id = int(cur.lastrowid or 0)
            return row_id if row_id > 0 else None

    def snapshot(self, *, limit: int = 20) -> dict[str, Any]:
        with self._connect() as conn:
            total = int(
                conn.execute(
                    "SELECT COUNT(1) FROM scaling_dead_letters WHERE namespace = ?",
                    (self.namespace,),
                ).fetchone()[0]
            )
            rows = conn.execute(
                """
                SELECT category, COUNT(1)
                FROM scaling_dead_letters
                WHERE namespace = ?
                GROUP BY category
                """,
                (self.namespace,),
            ).fetchall()
            by_category = {str(row[0]): int(row[1]) for row in rows}
            recent_rows = conn.execute(
                """
                SELECT id, category, reason, payload_json, camera_id, sequence, source, created_at
                FROM scaling_dead_letters
                WHERE namespace = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (self.namespace, max(1, int(limit))),
            ).fetchall()
            recent = [
                {
                    "id": int(row[0]),
                    "category": str(row[1]),
                    "reason": str(row[2]),
                    "payload": _safe_json_loads(row[3]),
                    "camera_id": int(row[4]) if row[4] is not None else None,
                    "sequence": int(row[5]) if row[5] is not None else None,
                    "source": str(row[6]) if row[6] is not None else None,
                    "created_at": float(row[7]),
                }
                for row in recent_rows
            ]
            return {
                "backend": "sqlite",
                "namespace": self.namespace,
                "path": str(self.db_path),
                "total": total,
                "by_category": by_category,
                "recent": recent,
            }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scaling_dead_letters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL,
                    category TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    camera_id INTEGER NULL,
                    sequence INTEGER NULL,
                    source TEXT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scaling_dead_letters_namespace_id
                ON scaling_dead_letters(namespace, id)
                """
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


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, default=str, ensure_ascii=True)
    except Exception:
        return json.dumps({"repr": repr(value)}, ensure_ascii=True)


def _safe_json_loads(value: Any) -> Any:
    try:
        return json.loads(str(value))
    except Exception:
        return {"raw": str(value)}
