from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from vms.backend import crud, models, schemas
from vms.backend.core.audit import write_audit_log
from vms.backend.services.access_decision_service import AccessDecisionRequest, AccessDecisionResult
from vms.backend.services.alert_service import AlertSeverity, AlertType, get_alert_service
from vms.backend.services.unknown_detection_service import UnknownDetectionService


class ActionEngine:
    """Translate access decisions into incidents, alerts, logs, queue writes, and realtime events."""

    EVENT_DECISION_MAP = {
        "allow": "allowed",
        "deny": "denied",
        "review": "review_required",
        "unknown": "review_required",
    }
    EVENT_SEVERITY_MAP = {
        "allow": "info",
        "deny": "critical",
        "review": "warning",
        "unknown": "warning",
    }
    EVENT_TYPE_MAP = {
        "face": "person",
        "vehicle": "vehicle",
    }
    ALERT_TYPE_MAP = {
        "face": AlertType.FACE,
        "vehicle": AlertType.VEHICLE,
    }
    DECISION_LABEL_MAP = {
        "allow": "Access allowed",
        "deny": "Access denied",
        "review": "Manual review required",
        "unknown": "Unknown detection queued",
    }

    def __init__(self, db: Session, creator_id: Optional[int] = None):
        self.db = db
        self.creator_id = int(creator_id) if creator_id and int(creator_id) > 0 else None
        self.unknown_detection_service = UnknownDetectionService(db)

    def handle_decision(
        self,
        *,
        request: AccessDecisionRequest,
        result: AccessDecisionResult,
        camera_id: int,
        zone_id: Optional[int] = None,
        frame_bgr: Optional[Any] = None,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        confidence: float = 0.0,
        snapshot_path: Optional[str] = None,
        source_table: Optional[str] = None,
        source_detection_id: Optional[int] = None,
        label: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
        detected_at: Optional[datetime] = None,
    ) -> Dict[str, Optional[int]]:
        incident_id: Optional[int] = None
        alert_id: Optional[int] = None
        unknown_detection_id = int(request.unknown_detection_id or 0) or None

        if result.decision == "deny":
            incident_id = self.create_incident(
                request=request,
                result=result,
                camera_id=camera_id,
                zone_id=zone_id,
                confidence=confidence,
                snapshot_path=snapshot_path,
                source_table=source_table,
                source_detection_id=source_detection_id,
                label=label,
                extra_data=extra_data,
                detected_at=detected_at,
            )
        elif result.decision == "review":
            alert_id = self.create_review_alert(
                request=request,
                result=result,
                camera_id=camera_id,
                source_table=source_table,
                source_detection_id=source_detection_id,
                label=label,
                extra_data=extra_data,
                detected_at=detected_at,
            )

        if result.unknown_queue_action == "required" and frame_bgr is not None:
            unknown_payload = self.capture_unknown_detection(
                detection_type=result.detection_type,
                frame_bgr=frame_bgr,
                bbox=bbox,
                camera_id=camera_id,
                zone_id=zone_id,
                confidence=confidence,
                source_table=source_table,
                source_detection_id=source_detection_id,
                notes="Unknown detection enqueued by action engine",
                metadata={
                    "decision": result.decision,
                    "reason_code": result.reason_code,
                    "unknown_queue_action": result.unknown_queue_action,
                    "entity_type": result.entity_type,
                    "entity_id": result.entity_id,
                    **(extra_data or {}),
                },
            )
            if bool(unknown_payload.get("saved")):
                unknown_detection_id = int(unknown_payload.get("id") or 0) or None

        self.record_decision_log(
            request=request,
            result=result,
            camera_id=camera_id,
            source_table=source_table,
            source_detection_id=source_detection_id,
            incident_id=incident_id,
            alert_id=alert_id,
            unknown_detection_id=unknown_detection_id,
            extra_data=extra_data,
        )
        self.emit_decision_event(
            result=result,
            camera_id=camera_id,
            incident_id=incident_id,
            alert_id=alert_id,
            unknown_detection_id=unknown_detection_id,
            source_table=source_table,
            source_detection_id=source_detection_id,
            reference_label=label,
            extra_data=extra_data,
            detected_at=detected_at,
        )
        return {
            "event_id": incident_id,
            "alert_id": alert_id,
            "unknown_detection_id": unknown_detection_id,
        }

    def create_incident(
        self,
        *,
        request: AccessDecisionRequest,
        result: AccessDecisionResult,
        camera_id: int,
        zone_id: Optional[int] = None,
        confidence: float = 0.0,
        snapshot_path: Optional[str] = None,
        source_table: Optional[str] = None,
        source_detection_id: Optional[int] = None,
        label: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
        detected_at: Optional[datetime] = None,
    ) -> Optional[int]:
        try:
            camera = self._get_camera(camera_id=camera_id)
            event_data = schemas.EventCreate(
                camera_id=int(camera_id),
                zone_id=int(zone_id) if zone_id is not None else None,
                site_id=int(camera.site_id) if camera and camera.site_id is not None else None,
                event_type=self.EVENT_TYPE_MAP.get(result.detection_type, "alarm"),
                severity=self.EVENT_SEVERITY_MAP.get(result.decision, "warning"),
                decision=self.EVENT_DECISION_MAP.get(result.decision, "review_required"),
                description=result.explanation,
                detected_objects={
                    self.EVENT_TYPE_MAP.get(result.detection_type, "object"): 1,
                    "decision": result.decision,
                    "reason_code": result.reason_code,
                    "reference_label": self._reference_label(result=result, label=label),
                },
                confidence=float(max(0.0, min(1.0, confidence))),
                detected_at=detected_at or datetime.utcnow(),
                snapshot_path=snapshot_path,
                extra_data={
                    "event_id": source_detection_id,
                    "source_detection_id": source_detection_id,
                    "source_table": source_table,
                    "timestamp": (detected_at or datetime.utcnow()).isoformat(),
                    "access_decision": result.to_dict(),
                    **(extra_data or {}),
                },
            )
            creator_id = self._creator_id(camera=camera)
            event = crud.create_event(self.db, event_data, creator_id=creator_id)
            return int(event.id)
        except Exception:
            self.db.rollback()
            return None

    def create_review_alert(
        self,
        *,
        request: AccessDecisionRequest,
        result: AccessDecisionResult,
        camera_id: int,
        source_table: Optional[str] = None,
        source_detection_id: Optional[int] = None,
        label: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
        detected_at: Optional[datetime] = None,
    ) -> Optional[int]:
        try:
            camera = self._get_camera(camera_id=camera_id)
            alert = get_alert_service().create_alert(
                camera_id=int(camera_id),
                camera_name=str(camera.name) if camera is not None else f"Camera {int(camera_id)}",
                alert_type=self.ALERT_TYPE_MAP.get(result.detection_type, AlertType.SYSTEM),
                message=result.explanation,
                severity=AlertSeverity.MEDIUM,
                tenant_id=int(camera.tenant_id) if camera and camera.tenant_id is not None else None,
                data={
                    "decision": result.decision,
                    "reason_code": result.reason_code,
                    "reason": result.reason_code,
                    "explanation": result.explanation,
                    "event_id": source_detection_id,
                    "source_detection_id": source_detection_id,
                    "source_table": source_table,
                    "timestamp": (detected_at or datetime.utcnow()).isoformat(),
                    "detection_type": result.detection_type,
                    "entity_type": result.entity_type,
                    "entity_id": result.entity_id,
                    "reference_label": self._reference_label(result=result, label=label),
                    "checks": [check.to_dict() for check in result.checks],
                    **(extra_data or {}),
                },
            )
            return int(alert.id) if alert.id is not None else None
        except Exception:
            return None

    def capture_unknown_detection(
        self,
        *,
        detection_type: str,
        frame_bgr: Any,
        bbox: Optional[Tuple[int, int, int, int]],
        camera_id: int,
        zone_id: Optional[int] = None,
        confidence: float = 0.0,
        source_table: Optional[str] = None,
        source_detection_id: Optional[int] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.unknown_detection_service.capture_from_frame(
            detection_type=detection_type,
            frame_bgr=frame_bgr,
            bbox=bbox,
            camera_id=int(camera_id),
            zone_id=int(zone_id) if zone_id is not None else None,
            confidence=float(max(0.0, min(1.0, confidence))),
            source_table=source_table,
            source_detection_id=source_detection_id,
            notes=notes,
            metadata=metadata,
        )

    def record_decision_log(
        self,
        *,
        request: AccessDecisionRequest,
        result: AccessDecisionResult,
        camera_id: int,
        source_table: Optional[str] = None,
        source_detection_id: Optional[int] = None,
        incident_id: Optional[int] = None,
        alert_id: Optional[int] = None,
        unknown_detection_id: Optional[int] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        write_audit_log(
            event_type="access_decision",
            action=f"pipeline_{result.detection_type}_{result.decision}",
            method="PIPELINE",
            path=f"/pipelines/{result.detection_type}",
            status_code=200,
            user_id=self.creator_id,
            details={
                "camera_id": int(camera_id),
                "source_table": source_table,
                "source_detection_id": source_detection_id,
                "incident_id": incident_id,
                "alert_id": alert_id,
                "unknown_detection_id": unknown_detection_id,
                "decision": result.decision,
                "reason_code": result.reason_code,
                "explanation": result.explanation,
                "confidence": float(result.confidence),
                "entity_type": result.entity_type,
                "entity_id": result.entity_id,
                "matched": bool(result.matched),
                "unknown_queue_action": result.unknown_queue_action,
                "request_metadata": request.metadata,
                **(extra_data or {}),
            },
        )

    def emit_decision_event(
        self,
        *,
        result: AccessDecisionResult,
        camera_id: int,
        incident_id: Optional[int] = None,
        alert_id: Optional[int] = None,
        unknown_detection_id: Optional[int] = None,
        source_table: Optional[str] = None,
        source_detection_id: Optional[int] = None,
        reference_label: Optional[str] = None,
        extra_data: Optional[Dict[str, Any]] = None,
        detected_at: Optional[datetime] = None,
    ) -> None:
        try:
            from vms.backend.routers.ws import broadcast_api_event_sync

            payload = {
                "camera_id": int(camera_id),
                "decision": result.decision,
                "label": self.DECISION_LABEL_MAP.get(result.decision, "Decision"),
                "reason": result.reason_code,
                "reason_code": result.reason_code,
                "explanation": result.explanation,
                "detection_type": result.detection_type,
                "entity_type": result.entity_type,
                "entity_id": result.entity_id,
                "matched": result.matched,
                "confidence": float(result.confidence),
                "unknown_queue_action": result.unknown_queue_action,
                "reference_label": self._reference_label(result=result, label=reference_label),
                "event_id": incident_id,
                "incident_id": incident_id,
                "alert_id": alert_id,
                "unknown_detection_id": unknown_detection_id,
                "source_table": source_table,
                "source_detection_id": source_detection_id,
                "checks": [check.to_dict() for check in result.checks],
                "timestamp": (detected_at or datetime.utcnow()).isoformat(),
                **(extra_data or {}),
            }
            broadcast_api_event_sync("decision", payload, channel="system")
        except Exception:
            return

    def _get_camera(self, *, camera_id: int) -> Optional[models.Camera]:
        return self.db.query(models.Camera).filter(models.Camera.id == int(camera_id)).first()

    def _creator_id(self, *, camera: Optional[models.Camera]) -> int:
        if self.creator_id is not None:
            return int(self.creator_id)
        if camera is not None and camera.owner_id is not None:
            return int(camera.owner_id)
        return 1

    def _reference_label(self, *, result: AccessDecisionResult, label: Optional[str]) -> Optional[str]:
        if result.reference_label:
            return str(result.reference_label)
        if label:
            return str(label)
        if result.entity_id is not None:
            return f"{result.entity_type} #{int(result.entity_id)}"
        return None
