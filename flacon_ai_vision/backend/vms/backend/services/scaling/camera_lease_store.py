from __future__ import annotations

import json
import os
import socket
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


def _utc_iso_from_epoch(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat()


def build_default_owner_id(role: str) -> str:
    host = socket.gethostname().strip() or "unknown-host"
    pid = os.getpid()
    nonce = uuid4().hex[:8]
    return f"{str(role or 'runtime').strip().lower()}:{host}:{pid}:{nonce}"


@dataclass(slots=True)
class CameraLeaseState:
    camera_id: int
    namespace: str
    owner_id: Optional[str]
    owner_role: Optional[str]
    owner_metadata: dict[str, Any]
    claimed: bool
    claimed_at: Optional[str]
    heartbeat_at: Optional[str]
    lease_expires_at: Optional[str]
    version: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SqliteCameraLeaseStore:
    """
    SQLite-backed camera ownership lease store.

    It provides a shared claim/renew/release primitive so only one runtime
    process owns a camera at a time. Ownership automatically fails over when
    the lease expires and another process claims it.
    """

    def __init__(
        self,
        *,
        db_path: str,
        namespace: str,
        owner_id: Optional[str] = None,
        owner_role: str = "ingestion",
        lease_ttl_sec: float = 8.0,
    ):
        self.db_path = Path(db_path)
        self.namespace = str(namespace or "distributed").strip() or "distributed"
        self.owner_role = str(owner_role or "ingestion").strip().lower() or "ingestion"
        self.owner_id = str(owner_id or build_default_owner_id(self.owner_role))
        # Keep a small floor to avoid zero/negative leases, but do not silently
        # stretch short TTLs because failover tests and fast standby takeover
        # rely on the configured expiry window.
        self.lease_ttl_sec = max(0.05, float(lease_ttl_sec))
        self._lock = threading.RLock()

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def claim_or_renew(
        self,
        camera_id: int,
        *,
        owner_metadata: Optional[dict[str, Any]] = None,
    ) -> CameraLeaseState:
        now = time.time()
        expires_at = now + self.lease_ttl_sec
        metadata_json = json.dumps(owner_metadata or {}, sort_keys=True)
        namespace = self.namespace
        camera_key = int(camera_id)

        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT owner_id, owner_role, owner_metadata, claimed_at, heartbeat_at, lease_expires_at, version
                    FROM scaling_camera_leases
                    WHERE namespace = ? AND camera_id = ?
                    """,
                    (namespace, camera_key),
                ).fetchone()

                if row is None:
                    version = 1
                    conn.execute(
                        """
                        INSERT INTO scaling_camera_leases (
                            namespace,
                            camera_id,
                            owner_id,
                            owner_role,
                            owner_metadata,
                            claimed_at,
                            heartbeat_at,
                            lease_expires_at,
                            version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            namespace,
                            camera_key,
                            self.owner_id,
                            self.owner_role,
                            metadata_json,
                            now,
                            now,
                            expires_at,
                            version,
                        ),
                    )
                    conn.execute("COMMIT")
                    return CameraLeaseState(
                        camera_id=camera_key,
                        namespace=namespace,
                        owner_id=self.owner_id,
                        owner_role=self.owner_role,
                        owner_metadata=dict(owner_metadata or {}),
                        claimed=True,
                        claimed_at=_utc_iso_from_epoch(now),
                        heartbeat_at=_utc_iso_from_epoch(now),
                        lease_expires_at=_utc_iso_from_epoch(expires_at),
                        version=version,
                    )

                current_owner_id = str(row[0]) if row[0] is not None else None
                current_owner_role = str(row[1]) if row[1] is not None else None
                current_owner_metadata = self._parse_owner_metadata(row[2])
                current_claimed_at = float(row[3]) if row[3] is not None else None
                current_heartbeat_at = float(row[4]) if row[4] is not None else None
                current_lease_expires_at = float(row[5]) if row[5] is not None else None
                current_version = int(row[6] or 0)

                current_is_owner = current_owner_id == self.owner_id
                current_is_expired = current_lease_expires_at is None or current_lease_expires_at <= now
                if current_is_owner or current_is_expired:
                    claimed_at = current_claimed_at if current_is_owner and current_claimed_at is not None else now
                    version = current_version + 1
                    conn.execute(
                        """
                        UPDATE scaling_camera_leases
                        SET owner_id = ?,
                            owner_role = ?,
                            owner_metadata = ?,
                            claimed_at = ?,
                            heartbeat_at = ?,
                            lease_expires_at = ?,
                            version = ?
                        WHERE namespace = ? AND camera_id = ?
                        """,
                        (
                            self.owner_id,
                            self.owner_role,
                            metadata_json,
                            claimed_at,
                            now,
                            expires_at,
                            version,
                            namespace,
                            camera_key,
                        ),
                    )
                    conn.execute("COMMIT")
                    return CameraLeaseState(
                        camera_id=camera_key,
                        namespace=namespace,
                        owner_id=self.owner_id,
                        owner_role=self.owner_role,
                        owner_metadata=dict(owner_metadata or {}),
                        claimed=True,
                        claimed_at=_utc_iso_from_epoch(claimed_at),
                        heartbeat_at=_utc_iso_from_epoch(now),
                        lease_expires_at=_utc_iso_from_epoch(expires_at),
                        version=version,
                    )

                conn.execute("COMMIT")
                return CameraLeaseState(
                    camera_id=camera_key,
                    namespace=namespace,
                    owner_id=current_owner_id,
                    owner_role=current_owner_role,
                    owner_metadata=current_owner_metadata,
                    claimed=False,
                    claimed_at=_utc_iso_from_epoch(current_claimed_at),
                    heartbeat_at=_utc_iso_from_epoch(current_heartbeat_at),
                    lease_expires_at=_utc_iso_from_epoch(current_lease_expires_at),
                    version=current_version,
                )

    def release(self, camera_id: int) -> bool:
        namespace = self.namespace
        camera_key = int(camera_id)
        with self._lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                released = conn.execute(
                    """
                    DELETE FROM scaling_camera_leases
                    WHERE namespace = ? AND camera_id = ? AND owner_id = ?
                    """,
                    (namespace, camera_key, self.owner_id),
                ).rowcount or 0
                conn.execute("COMMIT")
        return bool(released)

    def get(self, camera_id: int) -> Optional[CameraLeaseState]:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT owner_id, owner_role, owner_metadata, claimed_at, heartbeat_at, lease_expires_at, version
                    FROM scaling_camera_leases
                    WHERE namespace = ? AND camera_id = ?
                    """,
                    (self.namespace, int(camera_id)),
                ).fetchone()
        if row is None:
            return None
        owner_id = str(row[0]) if row[0] is not None else None
        return CameraLeaseState(
            camera_id=int(camera_id),
            namespace=self.namespace,
            owner_id=owner_id,
            owner_role=str(row[1]) if row[1] is not None else None,
            owner_metadata=self._parse_owner_metadata(row[2]),
            claimed=owner_id == self.owner_id,
            claimed_at=_utc_iso_from_epoch(float(row[3]) if row[3] is not None else None),
            heartbeat_at=_utc_iso_from_epoch(float(row[4]) if row[4] is not None else None),
            lease_expires_at=_utc_iso_from_epoch(float(row[5]) if row[5] is not None else None),
            version=int(row[6] or 0),
        )

    def snapshot(self, *, limit: int = 100, include_expired: bool = False) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT camera_id, owner_id, owner_role, owner_metadata, claimed_at, heartbeat_at, lease_expires_at, version
                    FROM scaling_camera_leases
                    WHERE namespace = ?
                    ORDER BY camera_id ASC
                    LIMIT ?
                    """,
                    (self.namespace, max(1, int(limit))),
                ).fetchall()

        leases: list[dict[str, Any]] = []
        for row in rows:
            lease_expires_raw = float(row[6]) if row[6] is not None else None
            if (not include_expired) and lease_expires_raw is not None and lease_expires_raw <= now:
                continue
            owner_id = str(row[1]) if row[1] is not None else None
            leases.append(
                {
                    "camera_id": int(row[0]),
                    "owner_id": owner_id,
                    "owner_role": str(row[2]) if row[2] is not None else None,
                    "owner_metadata": self._parse_owner_metadata(row[3]),
                    "claimed_at": _utc_iso_from_epoch(float(row[4]) if row[4] is not None else None),
                    "heartbeat_at": _utc_iso_from_epoch(float(row[5]) if row[5] is not None else None),
                    "lease_expires_at": _utc_iso_from_epoch(lease_expires_raw),
                    "expired": bool(lease_expires_raw is not None and lease_expires_raw <= now),
                    "owned_by_self": owner_id == self.owner_id,
                    "version": int(row[7] or 0),
                }
            )

        return {
            "backend": "sqlite",
            "db_path": str(self.db_path),
            "namespace": self.namespace,
            "owner_id": self.owner_id,
            "owner_role": self.owner_role,
            "lease_ttl_sec": float(self.lease_ttl_sec),
            "active_leases": leases,
            "active_leases_count": len(leases),
        }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scaling_camera_leases (
                    namespace TEXT NOT NULL,
                    camera_id INTEGER NOT NULL,
                    owner_id TEXT NOT NULL,
                    owner_role TEXT NOT NULL,
                    owner_metadata TEXT NULL,
                    claimed_at REAL NOT NULL,
                    heartbeat_at REAL NOT NULL,
                    lease_expires_at REAL NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (namespace, camera_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scaling_camera_leases_namespace_expiry
                ON scaling_camera_leases (namespace, lease_expires_at)
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

    @staticmethod
    def _parse_owner_metadata(raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(str(raw))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
