from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session


class VehicleLiveMonitoringModule:
    """DB-backed live monitoring snapshot for REST polling dashboards."""

    def __init__(self, db: Session):
        self.db = db

    def collect(
        self,
        *,
        camera_id: Optional[int] = None,
        window_minutes: int = 60,
        bucket_seconds: int = 60,
        recent_limit: int = 8,
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        from vms.backend.models import SecurityAlert, VehicleEvent

        now = self._to_utc_naive(reference_time or datetime.utcnow())
        safe_window_minutes = max(1, int(window_minutes))
        safe_bucket_seconds = max(10, int(bucket_seconds))
        safe_recent_limit = max(1, int(recent_limit))
        cutoff = now - timedelta(minutes=safe_window_minutes)

        event_query = self.db.query(VehicleEvent).filter(VehicleEvent.timestamp >= cutoff)
        alert_query = self.db.query(SecurityAlert).filter(SecurityAlert.timestamp >= cutoff)
        if camera_id is not None:
            event_query = event_query.filter(VehicleEvent.camera_id == int(camera_id))
            alert_query = alert_query.filter(SecurityAlert.camera_id == int(camera_id))

        event_rows = [self._serialize_event_row(row) for row in event_query.all()]
        alert_rows = [self._serialize_alert_row(row) for row in alert_query.all()]

        return self.build_snapshot_from_rows(
            event_rows=event_rows,
            alert_rows=alert_rows,
            camera_id=camera_id,
            window_minutes=safe_window_minutes,
            bucket_seconds=safe_bucket_seconds,
            recent_limit=safe_recent_limit,
            reference_time=now,
        )

    @classmethod
    def build_snapshot_from_rows(
        cls,
        *,
        event_rows: List[Dict[str, Any]],
        alert_rows: List[Dict[str, Any]],
        camera_id: Optional[int],
        window_minutes: int,
        bucket_seconds: int,
        recent_limit: int,
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = cls._to_utc_naive(reference_time or datetime.utcnow())
        safe_window_minutes = max(1, int(window_minutes))
        safe_bucket_seconds = max(10, int(bucket_seconds))
        safe_recent_limit = max(1, int(recent_limit))
        cutoff = now - timedelta(minutes=safe_window_minutes)
        window_seconds = max(60, safe_window_minutes * 60)

        # Cap timeline points so payload stays lightweight for polling.
        max_points = 240
        point_count = int(math.ceil(window_seconds / safe_bucket_seconds))
        if point_count > max_points:
            safe_bucket_seconds = int(math.ceil(window_seconds / max_points))
            point_count = int(math.ceil(window_seconds / safe_bucket_seconds))
        point_count = max(1, point_count)

        timeline: List[Dict[str, Any]] = []
        for idx in range(point_count):
            bucket_start = cutoff + timedelta(seconds=idx * safe_bucket_seconds)
            bucket_end = bucket_start + timedelta(seconds=safe_bucket_seconds)
            timeline.append(
                {
                    "bucket_start": bucket_start.isoformat(),
                    "bucket_end": bucket_end.isoformat(),
                    "events": 0,
                    "anomalies": 0,
                    "priority_events": 0,
                    "alerts": 0,
                    "critical_alerts": 0,
                    "high_alerts": 0,
                }
            )

        events_total = 0
        anomalies_total = 0
        priority_events_total = 0
        confidence_sum = 0.0
        consistency_sum = 0.0
        latest_event_at: Optional[datetime] = None

        for row in event_rows:
            ts = cls._to_utc_naive(cls._as_datetime(row.get("timestamp")))
            if ts is None or ts < cutoff:
                continue

            events_total += 1
            if bool(row.get("anomaly_detected")):
                anomalies_total += 1
            if bool(row.get("is_priority")):
                priority_events_total += 1
            confidence_sum += float(row.get("confidence") or 0.0)
            consistency_sum += float(row.get("consistency_score") or 0.0)
            if latest_event_at is None or ts > latest_event_at:
                latest_event_at = ts

            idx = min(point_count - 1, int(((ts - cutoff).total_seconds()) // safe_bucket_seconds))
            if idx >= 0:
                timeline[idx]["events"] += 1
                if bool(row.get("anomaly_detected")):
                    timeline[idx]["anomalies"] += 1
                if bool(row.get("is_priority")):
                    timeline[idx]["priority_events"] += 1

        alerts_total = 0
        latest_alert_at: Optional[datetime] = None
        severity_counts: Dict[str, int] = {
            "low": 0,
            "medium": 0,
            "high": 0,
            "critical": 0,
            "unknown": 0,
        }
        resolution_counts: Dict[str, int] = {
            "open": 0,
            "in_review": 0,
            "resolved": 0,
            "unknown": 0,
        }
        type_counts: Dict[str, int] = {}
        filtered_alerts: List[Dict[str, Any]] = []

        for row in alert_rows:
            ts = cls._to_utc_naive(cls._as_datetime(row.get("timestamp")))
            if ts is None or ts < cutoff:
                continue

            alerts_total += 1
            if latest_alert_at is None or ts > latest_alert_at:
                latest_alert_at = ts

            severity = str(row.get("severity_level") or "unknown").strip().lower()
            status = str(row.get("resolution_status") or "unknown").strip().lower()
            alert_type = str(row.get("type") or "unknown").strip().lower()
            severity_counts[severity if severity in severity_counts else "unknown"] += 1
            resolution_counts[status if status in resolution_counts else "unknown"] += 1
            type_counts[alert_type] = int(type_counts.get(alert_type, 0)) + 1

            idx = min(point_count - 1, int(((ts - cutoff).total_seconds()) // safe_bucket_seconds))
            if idx >= 0:
                timeline[idx]["alerts"] += 1
                if severity == "critical":
                    timeline[idx]["critical_alerts"] += 1
                if severity == "high":
                    timeline[idx]["high_alerts"] += 1

            filtered_alerts.append(
                {
                    "id": row.get("id"),
                    "timestamp": ts.isoformat(),
                    "type": alert_type,
                    "severity_level": severity,
                    "resolution_status": status,
                    "message": row.get("message"),
                    "plate_number": row.get("plate_number"),
                    "camera_id": row.get("camera_id"),
                    "event_id": row.get("event_id"),
                }
            )

        filtered_alerts.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        recent_alerts = filtered_alerts[:safe_recent_limit]

        avg_confidence = float(confidence_sum / events_total) if events_total else 0.0
        avg_consistency = float(consistency_sum / events_total) if events_total else 0.0
        anomaly_rate = float(anomalies_total / events_total) if events_total else 0.0

        return {
            "generated_at": now.isoformat(),
            "camera_id": camera_id,
            "window_minutes": safe_window_minutes,
            "bucket_seconds": safe_bucket_seconds,
            "stats": {
                "events_total": events_total,
                "anomalies_total": anomalies_total,
                "priority_events_total": priority_events_total,
                "alerts_total": alerts_total,
                "alerts_open": int(resolution_counts.get("open", 0)),
                "alerts_in_review": int(resolution_counts.get("in_review", 0)),
                "alerts_resolved": int(resolution_counts.get("resolved", 0)),
                "alerts_by_severity": severity_counts,
                "alerts_by_type": type_counts,
                "avg_confidence": round(avg_confidence, 4),
                "avg_consistency_score": round(avg_consistency, 4),
                "anomaly_rate": round(anomaly_rate, 4),
                "latest_event_at": latest_event_at.isoformat() if latest_event_at else None,
                "latest_alert_at": latest_alert_at.isoformat() if latest_alert_at else None,
            },
            "timeline": timeline,
            "recent_alerts": recent_alerts,
            "polling_hint_ms": 5000,
        }

    @staticmethod
    def _serialize_event_row(row: Any) -> Dict[str, Any]:
        return {
            "id": getattr(row, "id", None),
            "timestamp": getattr(row, "timestamp", None),
            "confidence": getattr(row, "confidence", 0.0),
            "consistency_score": getattr(row, "consistency_score", 0.0),
            "anomaly_detected": bool(getattr(row, "anomaly_detected", False)),
            "is_priority": bool(getattr(row, "is_priority", False)),
        }

    @staticmethod
    def _serialize_alert_row(row: Any) -> Dict[str, Any]:
        return {
            "id": getattr(row, "id", None),
            "timestamp": getattr(row, "timestamp", None),
            "type": getattr(row, "type", None),
            "severity_level": getattr(row, "severity_level", None),
            "resolution_status": getattr(row, "resolution_status", None),
            "message": getattr(row, "message", None),
            "plate_number": getattr(row, "plate_number", None),
            "camera_id": getattr(row, "camera_id", None),
            "event_id": getattr(row, "event_id", None),
        }

    @staticmethod
    def _as_datetime(value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except Exception:
                return None
        return None

    @staticmethod
    def _to_utc_naive(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)
