from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Protocol

from sqlalchemy.orm import Session

from vms.backend.core.database import SessionLocal
from vms.backend.models import VehicleEvent

from .frame_task_queue import InferenceResultTask


class VehicleEventPersistenceService(Protocol):
    def persist(self, result: InferenceResultTask) -> Optional[int]:
        """Persist an inference result and return event id when available."""


class SqlAlchemyVehicleEventPersistenceService:
    """
    Async-friendly persistence adapter.

    This service intentionally persists only vehicle event rows so it can run
    independently from the legacy synchronous route path.
    """

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def persist(self, result: InferenceResultTask) -> Optional[int]:
        if not result.success:
            return None

        payload = result.payload or {}
        if not isinstance(payload, dict):
            return None

        existing_event_id = _to_opt_int(payload.get("event_id"))
        if existing_event_id is not None and existing_event_id > 0:
            return existing_event_id

        camera_id = _to_opt_int(payload.get("camera_id")) or int(result.camera_id)
        if camera_id <= 0:
            raise ValueError("camera_id is required for async vehicle event persistence")

        row = VehicleEvent(
            plate_number=_to_opt_str(payload.get("plate_display") or payload.get("plate_number")),
            plate_type=_to_opt_str(payload.get("plate_type")) or "unknown",
            confidence=float(payload.get("confidence") or 0.0),
            vehicle_detected=bool(payload.get("vehicle_detected", False)),
            vehicle_type=_to_opt_str(payload.get("vehicle_class") or payload.get("vehicle_type")),
            vehicle_confidence=float(payload.get("vehicle_confidence") or 0.0),
            vehicle_bbox=payload.get("vehicle_bbox"),
            plate_confidence=float(payload.get("plate_confidence") or 0.0),
            plate_bbox=payload.get("plate_bbox"),
            raw_plate_text=_to_opt_str(payload.get("raw_plate_text")),
            normalized_plate=_to_opt_str(payload.get("normalized_plate")),
            camera_id=camera_id,
            zone_id=_to_opt_int(payload.get("zone_id")),
            site_id=_to_opt_int(payload.get("site_id")),
            timestamp=_parse_ts(payload.get("timestamp")) or datetime.now(timezone.utc),
            snapshot_path=_to_opt_str(payload.get("snapshot_path")),
            severity=_to_opt_str(payload.get("severity")) or "info",
            is_priority=bool(payload.get("priority", False)),
            security_tag=_to_opt_str(payload.get("security_tag")),
            reason=_to_opt_str(payload.get("decision_reason") or payload.get("reason")),
            matched_registry=bool(payload.get("matched_registry", False)),
            pipeline_meta={
                "async_writer": True,
                "captured_at": result.captured_at,
                "produced_at": result.produced_at,
                "sequence": result.sequence,
                "latency_ms": result.latency_ms,
                "payload": payload,
            },
        )

        db: Session = self.session_factory()
        try:
            db.add(row)
            db.commit()
            db.refresh(row)
            return int(row.id)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _to_opt_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_opt_str(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _parse_ts(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None
