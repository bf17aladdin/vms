from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session


class SystemHealthService:
    """Production health aggregation + persistence."""

    def __init__(self, db: Session):
        self.db = db

    def get_full_health(self, *, persist: bool = True, window_minutes: int = 60) -> Dict[str, Any]:
        database = self._db_latency()
        vehicle = self._vehicle_latency(window_minutes=window_minutes)
        cameras = self._camera_health()

        checks = {
            "database": database,
            "ocr": {
                "status": vehicle["ocr_status"],
                "avg_latency_ms": vehicle["avg_ocr_latency_ms"],
                "sample_count": vehicle["sample_count"],
            },
            "pipeline": {
                "status": vehicle["pipeline_status"],
                "avg_latency_ms": vehicle["avg_pipeline_latency_ms"],
                "sample_count": vehicle["sample_count"],
            },
            "cameras": cameras,
        }

        overall = self._overall_status(checks)
        now_iso = datetime.utcnow().isoformat()

        if persist:
            self._write_log(
                service_name="database",
                status=database["status"],
                latency_ms=database.get("latency_ms"),
                details=database,
            )
            self._write_log(
                service_name="ocr",
                status=vehicle["ocr_status"],
                latency_ms=vehicle.get("avg_ocr_latency_ms"),
                details={
                    "sample_count": vehicle["sample_count"],
                    "window_minutes": window_minutes,
                },
            )
            self._write_log(
                service_name="pipeline",
                status=vehicle["pipeline_status"],
                latency_ms=vehicle.get("avg_pipeline_latency_ms"),
                details={
                    "sample_count": vehicle["sample_count"],
                    "window_minutes": window_minutes,
                },
            )
            self._write_log(
                service_name="cameras",
                status=cameras["status"],
                latency_ms=cameras.get("avg_latency_ms"),
                details=cameras,
            )

        return {
            "success": True,
            "status": overall,
            "timestamp": now_iso,
            "checks": checks,
        }

    def _db_latency(self) -> Dict[str, Any]:
        started = time.perf_counter()
        try:
            self.db.execute(text("SELECT 1"))
            latency = (time.perf_counter() - started) * 1000.0
            status = "healthy" if latency <= 1200.0 else "degraded"
            return {
                "status": status,
                "latency_ms": round(float(latency), 3),
            }
        except Exception as exc:
            return {
                "status": "down",
                "latency_ms": None,
                "error": str(exc)[:240],
            }

    def _vehicle_latency(self, *, window_minutes: int) -> Dict[str, Any]:
        from vms.backend.models import VehicleEvent

        cutoff = datetime.utcnow() - timedelta(minutes=max(1, int(window_minutes)))
        rows = (
            self.db.query(VehicleEvent.pipeline_meta)
            .filter(VehicleEvent.timestamp >= cutoff)
            .order_by(VehicleEvent.timestamp.desc())
            .limit(500)
            .all()
        )

        ocr_latencies: List[float] = []
        pipeline_latencies: List[float] = []
        for row in rows:
            meta = row[0] if isinstance(row, tuple) else getattr(row, "pipeline_meta", None)
            if not isinstance(meta, dict):
                continue
            ocr = meta.get("ocr_latency_ms")
            pipe = meta.get("pipeline_latency_ms")
            try:
                if ocr is not None:
                    ocr_latencies.append(float(ocr))
            except Exception:
                pass
            try:
                if pipe is not None:
                    pipeline_latencies.append(float(pipe))
            except Exception:
                pass

        avg_ocr = (sum(ocr_latencies) / len(ocr_latencies)) if ocr_latencies else 0.0
        avg_pipe = (sum(pipeline_latencies) / len(pipeline_latencies)) if pipeline_latencies else 0.0

        ocr_status = "healthy"
        if not ocr_latencies:
            ocr_status = "degraded"
        elif avg_ocr > 900.0:
            ocr_status = "degraded"

        pipe_status = "healthy"
        if not pipeline_latencies:
            pipe_status = "degraded"
        elif avg_pipe > 1500.0:
            pipe_status = "degraded"

        return {
            "sample_count": min(len(ocr_latencies), len(pipeline_latencies)) if (ocr_latencies and pipeline_latencies) else max(len(ocr_latencies), len(pipeline_latencies)),
            "avg_ocr_latency_ms": round(float(avg_ocr), 3),
            "avg_pipeline_latency_ms": round(float(avg_pipe), 3),
            "ocr_status": ocr_status,
            "pipeline_status": pipe_status,
        }

    def _camera_health(self) -> Dict[str, Any]:
        from vms.backend.models import Camera, SecurityAlert

        rows = self.db.query(Camera).all()
        total = len(rows)
        online = 0
        offline = 0
        unknown = 0
        statuses: List[Dict[str, Any]] = []
        for row in rows:
            raw = str(row.connection_status or "").strip().lower()
            if raw in {"connected", "online"}:
                state = "online"
                online += 1
            elif raw in {"disconnected", "timeout", "error", "offline"}:
                state = "offline"
                offline += 1
            else:
                state = "unknown"
                unknown += 1
            statuses.append(
                {
                    "camera_id": int(row.id),
                    "name": row.name,
                    "status": state,
                    "connection_status": row.connection_status,
                    "last_check": row.last_connection_check.isoformat() if row.last_connection_check else None,
                }
            )

        tamper_open = (
            self.db.query(func.count(SecurityAlert.id))
            .filter(SecurityAlert.type.in_(["camera_tamper", "signal_loss", "black_frame", "camera_covered"]))
            .filter(SecurityAlert.resolution_status.in_(["open", "in_review"]))
            .scalar()
        )
        tamper_open = int(tamper_open or 0)

        if total == 0:
            status = "degraded"
        elif offline > 0 or tamper_open > 0:
            status = "degraded"
        else:
            status = "healthy"

        return {
            "status": status,
            "total": total,
            "online": online,
            "offline": offline,
            "unknown": unknown,
            "open_tamper_alerts": tamper_open,
            "cameras": statuses,
            "avg_latency_ms": None,
        }

    def _write_log(
        self,
        *,
        service_name: str,
        status: str,
        latency_ms: Optional[float],
        details: Optional[Dict[str, Any]],
    ) -> None:
        from vms.backend.models import SystemHealthLog

        normalized_status = str(status or "unknown").lower()
        err_count = self._next_error_count(service_name=service_name, status=normalized_status)
        row = SystemHealthLog(
            service_name=service_name,
            status=normalized_status,
            last_check=datetime.utcnow(),
            latency_ms=float(latency_ms) if latency_ms is not None else None,
            error_count=err_count,
            details=details or {},
        )
        self.db.add(row)
        self.db.commit()

    def _next_error_count(self, *, service_name: str, status: str) -> int:
        from vms.backend.models import SystemHealthLog

        if status == "healthy":
            return 0
        prev = (
            self.db.query(SystemHealthLog)
            .filter(SystemHealthLog.service_name == service_name)
            .order_by(SystemHealthLog.last_check.desc())
            .first()
        )
        if prev is None:
            return 1
        try:
            return int(prev.error_count or 0) + 1
        except Exception:
            return 1

    def _overall_status(self, checks: Dict[str, Dict[str, Any]]) -> str:
        statuses = [str(v.get("status", "unknown")).lower() for v in checks.values()]
        if "down" in statuses:
            return "down"
        if "degraded" in statuses:
            return "degraded"
        return "healthy"
