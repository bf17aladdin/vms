from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class VehicleService:
    """Persisted vehicle service used by legacy API routes and tests."""

    def __init__(self, db: Session):
        self.db = db

    def record_detection(
        self,
        license_plate: str,
        confidence: float,
        camera_id: int,
        zone_id: Optional[int] = None,
        vehicle_type: Optional[str] = None,
        color: Optional[str] = None,
        brand: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict:
        from vms.backend.models import VehicleDetection, VehicleEntry

        try:
            active_entry = (
                self.db.query(VehicleEntry)
                .filter(
                    VehicleEntry.license_plate == license_plate,
                    VehicleEntry.status == "active",
                )
                .order_by(VehicleEntry.entry_time.desc())
                .first()
            )

            if not active_entry:
                active_entry = VehicleEntry(
                    license_plate=license_plate,
                    vehicle_type=vehicle_type,
                    brand=brand,
                    model=model,
                    color=color,
                    entry_camera_id=camera_id,
                    entry_time=datetime.utcnow(),
                    entry_confidence=confidence,
                    status="active",
                )
                self.db.add(active_entry)
                self.db.flush()
            else:
                if vehicle_type and not active_entry.vehicle_type:
                    active_entry.vehicle_type = vehicle_type
                if color and not active_entry.color:
                    active_entry.color = color
                if brand and not active_entry.brand:
                    active_entry.brand = brand
                if model and not active_entry.model:
                    active_entry.model = model

            detection = VehicleDetection(
                license_plate=license_plate,
                plate_confidence=confidence,
                vehicle_type=vehicle_type or active_entry.vehicle_type,
                color=color or active_entry.color,
                vehicle_entry_id=active_entry.id,
                camera_id=camera_id,
                zone_id=zone_id,
                detected_at=datetime.utcnow(),
            )
            self.db.add(detection)
            self.db.commit()
            self.db.refresh(active_entry)
            self.db.refresh(detection)

            return {
                "success": True,
                "vehicle_entry_id": active_entry.id,
                "detection_id": detection.id,
                "license_plate": license_plate,
                "confidence": confidence,
                "camera_id": camera_id,
                "zone_id": zone_id,
                "vehicle_type": detection.vehicle_type,
                "color": detection.color,
                "brand": active_entry.brand,
                "model": active_entry.model,
                "message": "Detection enregistree",
                "timestamp": detection.detected_at.isoformat(),
            }
        except Exception as exc:
            self.db.rollback()
            logger.exception("Failed to record vehicle detection for plate %s", license_plate)
            return {
                "success": False,
                "license_plate": license_plate,
                "message": str(exc),
            }

    def record_exit(self, license_plate: str, camera_id: int) -> Dict:
        from vms.backend.models import VehicleEntry

        try:
            active_entry = (
                self.db.query(VehicleEntry)
                .filter(
                    VehicleEntry.license_plate == license_plate,
                    VehicleEntry.status == "active",
                )
                .order_by(VehicleEntry.entry_time.desc())
                .first()
            )
            if not active_entry:
                return {
                    "success": False,
                    "message": "Vehicle entry not found",
                }

            exit_time = datetime.utcnow()
            active_entry.exit_camera_id = camera_id
            active_entry.exit_time = exit_time
            active_entry.exit_confidence = active_entry.entry_confidence
            active_entry.status = "exited"
            if active_entry.entry_time:
                duration = exit_time - active_entry.entry_time
                active_entry.duration_minutes = max(0, int(duration.total_seconds() // 60))

            self.db.commit()
            self.db.refresh(active_entry)

            return {
                "success": True,
                "vehicle_entry_id": active_entry.id,
                "license_plate": license_plate,
                "duration_minutes": active_entry.duration_minutes or 0,
                "message": "Exit recorded",
                "timestamp": exit_time.isoformat(),
            }
        except Exception as exc:
            self.db.rollback()
            logger.exception("Failed to record vehicle exit for plate %s", license_plate)
            return {
                "success": False,
                "message": str(exc),
            }

    def get_detection_history(
        self,
        license_plate: Optional[str] = None,
        camera_id: Optional[int] = None,
        limit: int = 50,
    ) -> List[Dict]:
        from vms.backend.models import VehicleDetection

        query = self.db.query(VehicleDetection)
        if license_plate:
            query = query.filter(VehicleDetection.license_plate == license_plate)
        if camera_id is not None:
            query = query.filter(VehicleDetection.camera_id == camera_id)

        detections = query.order_by(VehicleDetection.detected_at.desc()).limit(limit).all()
        return [
            {
                "id": detection.id,
                "vehicle_entry_id": detection.vehicle_entry_id,
                "license_plate": detection.license_plate,
                "confidence": float(detection.plate_confidence or 0.0),
                "vehicle_type": detection.vehicle_type,
                "color": detection.color,
                "camera_id": detection.camera_id,
                "zone_id": detection.zone_id,
                "detected_at": detection.detected_at.isoformat(),
            }
            for detection in detections
        ]

    def get_statistics(self, days: int = 7) -> Dict:
        from vms.backend.models import VehicleDetection, VehicleEntry

        since = datetime.utcnow() - timedelta(days=days)
        detections = (
            self.db.query(VehicleDetection)
            .filter(VehicleDetection.detected_at >= since)
            .all()
        )
        entries = (
            self.db.query(VehicleEntry)
            .filter(VehicleEntry.entry_time >= since)
            .all()
        )

        by_type: Dict[str, int] = {}
        by_camera: Dict[str, int] = {}
        for detection in detections:
            dtype = detection.vehicle_type or "unknown"
            by_type[dtype] = by_type.get(dtype, 0) + 1
            camera_key = str(detection.camera_id)
            by_camera[camera_key] = by_camera.get(camera_key, 0) + 1

        durations = [
            entry.duration_minutes
            for entry in entries
            if entry.duration_minutes is not None
        ]

        return {
            "total_detections": len(detections),
            "unique_vehicles": len(
                {detection.license_plate for detection in detections if detection.license_plate}
            ),
            "avg_duration_minutes": round(sum(durations) / len(durations), 2)
            if durations
            else 0,
            "total": len(detections),
            "by_type": by_type,
            "by_camera": by_camera,
        }

    @staticmethod
    def detect_vehicles_in_stream(
        db: Session,
        camera_id: int,
        confidence_threshold: float = 0.5,
    ) -> List[Dict]:
        from vms.backend.models import Camera
        from vms.backend.services.stream_service import StreamService
        from vms.backend.services.vehicle_ai.vehicle_pipeline import VehicleRecognitionPipeline

        camera = db.query(Camera).filter(Camera.id == int(camera_id)).first()
        if camera is None:
            raise ValueError(f"Camera {camera_id} not found")

        source = VehicleService._build_camera_source(camera)
        if not source:
            raise ValueError(f"Camera {camera_id} does not have a usable RTSP source")

        frame = StreamService.get_camera_frame(camera_id=int(camera_id), rtsp_url=source)
        if frame is None:
            raise RuntimeError(f"Unable to read a frame from camera {camera_id}")

        pipeline = VehicleRecognitionPipeline(db)
        target_confidence = max(0.0, min(1.0, float(confidence_threshold)))
        original_detector_conf = getattr(getattr(pipeline, "detector", None), "min_conf", None)
        original_stage_conf = getattr(getattr(pipeline, "detection_module", None), "min_vehicle_conf", None)

        try:
            if original_detector_conf is not None:
                pipeline.detector.min_conf = target_confidence
            if original_stage_conf is not None:
                pipeline.detection_module.min_vehicle_conf = target_confidence

            result = pipeline.recognize_from_frame(
                frame_bgr=frame,
                camera_id=int(camera_id),
                persist=False,
                save_snapshot=False,
            )
        finally:
            if original_detector_conf is not None:
                pipeline.detector.min_conf = original_detector_conf
            if original_stage_conf is not None:
                pipeline.detection_module.min_vehicle_conf = original_stage_conf

        if not bool(result.get("success", False)):
            raise RuntimeError(str(result.get("message") or "Vehicle recognition failed"))

        if not bool(result.get("vehicle_detected")) and not result.get("plate_number"):
            return []

        profile = result.get("vehicle_profile") if isinstance(result.get("vehicle_profile"), dict) else {}
        detection: Dict[str, Any] = {
            "camera_id": int(camera_id),
            "vehicle_detected": bool(result.get("vehicle_detected")),
            "plate_number": result.get("plate_number"),
            "plate_type": result.get("plate_type") or "unknown",
            "confidence": float(result.get("confidence") or 0.0),
            "vehicle_type": result.get("vehicle_type") or profile.get("vehicle_type"),
            "body_style": result.get("body_style") or profile.get("body_style"),
            "color": result.get("dominant_color") or profile.get("dominant_color"),
            "brand": result.get("brand") or profile.get("brand"),
            "model": result.get("model") or profile.get("model"),
            "decision": result.get("decision"),
            "reason": result.get("decision_reason") or result.get("message"),
            "timestamp": result.get("timestamp") or datetime.utcnow().isoformat(),
            "pipeline": result.get("pipeline") or {},
        }
        if isinstance(result.get("vehicle_bbox"), dict):
            detection["vehicle_bbox"] = result["vehicle_bbox"]
        if isinstance(result.get("plate_bbox"), dict):
            detection["plate_bbox"] = result["plate_bbox"]
        return [detection]

    @staticmethod
    def get_all_detections(
        db: Session,
        camera_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict]:
        from vms.backend.models import VehicleDetection

        query = db.query(VehicleDetection)
        if camera_id is not None:
            query = query.filter(VehicleDetection.camera_id == camera_id)

        detections = query.order_by(VehicleDetection.detected_at.desc()).offset(skip).limit(limit).all()
        return [
            {
                "id": detection.id,
                "license_plate": detection.license_plate,
                "vehicle_type": detection.vehicle_type,
                "color": detection.color,
                "camera_id": detection.camera_id,
                "detected_at": detection.detected_at.isoformat(),
            }
            for detection in detections
        ]

    @staticmethod
    def track_plate(db: Session, plate_number: str) -> List[Dict]:
        return VehicleService(db).get_detection_history(license_plate=plate_number, limit=200)

    @staticmethod
    def get_alerts(db: Session, skip: int = 0, limit: int = 50) -> List[Dict]:
        from vms.backend.models import Alert, SecurityAlert

        safe_skip = max(0, int(skip))
        safe_limit = max(1, min(int(limit), 500))
        fetch_size = safe_skip + safe_limit + 20

        security_rows = (
            db.query(SecurityAlert)
            .order_by(SecurityAlert.timestamp.desc())
            .limit(fetch_size)
            .all()
        )
        legacy_rows = (
            db.query(Alert)
            .filter(Alert.rule_type.in_(["vehicle", "vehicle_detection"]))
            .order_by(Alert.timestamp.desc())
            .limit(fetch_size)
            .all()
        )

        combined: List[tuple[str, Dict[str, Any]]] = []
        for row in security_rows:
            combined.append(
                (
                    row.timestamp.isoformat() if row.timestamp else "",
                    VehicleService._serialize_security_alert(row),
                )
            )
        for row in legacy_rows:
            combined.append(
                (
                    row.timestamp.isoformat() if row.timestamp else "",
                    VehicleService._serialize_legacy_alert(row),
                )
            )

        combined.sort(key=lambda item: item[0], reverse=True)
        return [payload for _, payload in combined[safe_skip : safe_skip + safe_limit]]

    @staticmethod
    def create_alert_zone(db: Session, camera_id: int, zone_name: str) -> Dict:
        from vms.backend.models import Camera, Zone

        normalized_name = str(zone_name or "").strip()
        if not normalized_name:
            raise ValueError("zone_name is required")

        camera = db.query(Camera).filter(Camera.id == int(camera_id)).first()
        if camera is None:
            raise ValueError(f"Camera {camera_id} not found")

        existing = (
            db.query(Zone)
            .filter(
                Zone.camera_id == int(camera_id),
                Zone.name == normalized_name,
            )
            .first()
        )
        if existing is not None:
            return {
                "id": int(existing.id),
                "camera_id": int(existing.camera_id),
                "zone_name": existing.name,
                "created_at": existing.created_at.isoformat() if existing.created_at else datetime.utcnow().isoformat(),
                "existing": True,
            }

        zone = Zone(
            tenant_id=getattr(camera, "tenant_id", None),
            camera_id=int(camera_id),
            site_id=getattr(camera, "site_id", None),
            name=normalized_name,
            description="Vehicle alert zone created from legacy vehicle detection endpoint",
            zone_type="custom",
            is_active=True,
        )
        db.add(zone)
        db.commit()
        db.refresh(zone)
        return {
            "id": int(zone.id),
            "camera_id": int(zone.camera_id),
            "zone_name": zone.name,
            "created_at": zone.created_at.isoformat() if zone.created_at else datetime.utcnow().isoformat(),
            "existing": False,
        }

    @staticmethod
    def _build_camera_source(camera: Any) -> Optional[str]:
        from vms.backend.services.camera_service import CameraService

        rtsp_url = str(getattr(camera, "rtsp_url", "") or "").strip()
        if rtsp_url:
            injected = CameraService._inject_rtsp_auth(
                rtsp_url,
                getattr(camera, "username", None),
                getattr(camera, "password", None),
            )
            return injected or rtsp_url

        ip_address = str(getattr(camera, "ip_address", "") or "").strip()
        if not ip_address:
            return None

        port = int(getattr(camera, "port", 554) or 554)
        username = str(getattr(camera, "username", "") or "").strip()
        password = str(getattr(camera, "password", "") or "").strip()
        if username and password:
            return f"rtsp://{username}:{password}@{ip_address}:{port}/stream"
        if username:
            return f"rtsp://{username}@{ip_address}:{port}/stream"
        return f"rtsp://{ip_address}:{port}/stream"

    @staticmethod
    def _serialize_security_alert(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "source": "security_alert",
            "type": row.type,
            "severity": row.severity_level,
            "status": row.resolution_status,
            "camera_id": row.camera_id,
            "site_id": row.site_id,
            "plate_number": row.plate_number,
            "normalized_plate": row.normalized_plate,
            "message": row.message,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "event_id": row.event_id,
            "access_log_id": row.access_log_id,
            "snapshot_path": row.snapshot_path,
            "details": row.details or {},
        }

    @staticmethod
    def _serialize_legacy_alert(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "source": "alert",
            "type": row.rule_type,
            "severity": row.severity,
            "status": "resolved" if bool(row.is_resolved) else "open",
            "camera_id": row.camera_id,
            "site_id": None,
            "plate_number": None,
            "normalized_plate": None,
            "message": row.message,
            "title": row.title,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "event_id": None,
            "access_log_id": None,
            "snapshot_path": None,
            "details": row.extra_data or {},
        }
