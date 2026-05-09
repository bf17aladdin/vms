# vms/backend/services/soc_dashboard_service.py - SOC Dashboard Service

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import threading
import time

from sqlalchemy import func

from ..core.database import get_db
from ..models import Camera, FaceDetection, UnknownDetection, VehicleEvent
from .alert_service import get_alert_service

logger = logging.getLogger(__name__)


def _count_rows(db, model, *criteria) -> int:
    query = db.query(func.count()).select_from(model)
    if criteria:
        query = query.filter(*criteria)
    return int(query.scalar() or 0)

@dataclass
class OpsMetrics:
    """Operational metrics for SOC dashboard"""
    cameras_active: int = 0
    cameras_total: int = 0
    cameras_degraded: int = 0
    cameras_down: int = 0
    faces_detected: int = 0
    vehicles_detected: int = 0
    alerts_triggered: int = 0
    avg_latency_ms: float = 0.0
    avg_fps: float = 0.0
    unknown_rate: float = 0.0
    false_positive_rate: float = 0.0
    pending_unknowns: int = 0
    processing_queue_size: int = 0
    last_update: str = ""

@dataclass
class AlertData:
    """Alert data structure"""
    id: str
    type: str
    severity: str
    title: str
    description: str
    camera_id: int
    camera_name: str
    timestamp: str
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[str] = None

@dataclass
class CameraActivity:
    """Camera activity data"""
    camera_id: int
    camera_name: str
    detections: int
    avg_latency: float
    fps: float
    alerts: int

@dataclass
class CrossCameraRoute:
    """Cross-camera movement route"""
    from_camera: int
    to_camera: int
    transitions: int
    avg_time: float

class SocDashboardService:
    """
    SOC Dashboard Service - Real-time metrics, analytics, and alerts
    """

    def __init__(self):
        self.metrics = OpsMetrics()
        self.alerts: List[AlertData] = []
        self.camera_activities: List[CameraActivity] = []
        self.cross_camera_routes: List[CrossCameraRoute] = []
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        """Start the dashboard service"""
        if self._running:
            return

        self._running = True
        self._update_thread = threading.Thread(target=self._metrics_update_loop, daemon=True)
        self._update_thread.start()
        logger.info("SOC Dashboard service started")

    def stop(self):
        """Stop the dashboard service"""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=5)
        logger.info("SOC Dashboard service stopped")

    def _metrics_update_loop(self):
        """Background thread for updating metrics"""
        while self._running:
            try:
                self._update_metrics()
                time.sleep(30)  # Update every 30 seconds
            except Exception as e:
                logger.error(f"Error updating SOC metrics: {e}")
                time.sleep(60)  # Wait longer on error

    def _update_metrics(self):
        """Update all operational metrics"""
        db = None
        try:
            with self._lock:
                # Get database session
                db = next(get_db())

                # Time window for metrics (last hour)
                time_window = datetime.utcnow() - timedelta(hours=1)

                # Camera status
                cameras = db.query(Camera).all()
                self.metrics.cameras_total = len(cameras)

                face_camera_ids = {
                    int(camera_id)
                    for (camera_id,) in db.query(FaceDetection.camera_id)
                    .filter(FaceDetection.detected_at >= time_window)
                    .distinct()
                    .all()
                    if camera_id is not None
                }
                vehicle_camera_ids = {
                    int(camera_id)
                    for (camera_id,) in db.query(VehicleEvent.camera_id)
                    .filter(VehicleEvent.timestamp >= time_window)
                    .distinct()
                    .all()
                    if camera_id is not None
                }
                active_camera_ids = face_camera_ids | vehicle_camera_ids
                self.metrics.cameras_active = len(active_camera_ids)

                # Degraded cameras (high latency or low FPS - simplified)
                self.metrics.cameras_degraded = 0  # TODO: implement based on performance data
                self.metrics.cameras_down = self.metrics.cameras_total - self.metrics.cameras_active

                # Detection counts
                face_events = _count_rows(
                    db,
                    FaceDetection,
                    FaceDetection.detected_at >= time_window,
                )
                self.metrics.faces_detected = face_events

                vehicle_events = _count_rows(
                    db,
                    VehicleEvent,
                    VehicleEvent.timestamp >= time_window,
                )
                self.metrics.vehicles_detected = vehicle_events

                # Alerts triggered / active
                alert_service = get_alert_service()
                self.metrics.alerts_triggered = len(alert_service.get_active_alerts())

                # Performance metrics (simplified - would need actual performance data)
                self.metrics.avg_latency_ms = 150.0  # TODO: calculate from actual data
                self.metrics.avg_fps = 25.0  # TODO: calculate from actual data

                # Quality metrics
                total_faces = max(face_events, 1)
                unknown_faces = _count_rows(
                    db,
                    UnknownDetection,
                    UnknownDetection.created_at >= time_window,
                    UnknownDetection.detection_type == 'face',
                )
                self.metrics.unknown_rate = unknown_faces / total_faces

                resolved_unknowns = _count_rows(
                    db,
                    UnknownDetection,
                    UnknownDetection.resolved_at >= time_window,
                    UnknownDetection.is_resolved.is_(True),
                )
                ignored_unknowns = _count_rows(
                    db,
                    UnknownDetection,
                    UnknownDetection.resolved_at >= time_window,
                    UnknownDetection.is_ignored.is_(True),
                )
                resolutions_total = resolved_unknowns + ignored_unknowns
                self.metrics.false_positive_rate = (
                    ignored_unknowns / resolutions_total if resolutions_total > 0 else 0.0
                )

                # Queue metrics
                self.metrics.pending_unknowns = _count_rows(
                    db,
                    UnknownDetection,
                    UnknownDetection.is_resolved.is_(False),
                    UnknownDetection.is_ignored.is_(False),
                )
                self.metrics.processing_queue_size = 0  # TODO: implement queue monitoring

                self.metrics.last_update = datetime.utcnow().isoformat()

                # Update camera activities
                self._update_camera_activities(db, time_window)

                # Update cross-camera routes
                self._update_cross_camera_routes(db, time_window)

        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

    def _update_camera_activities(self, db, time_window):
        """Update camera activity data"""
        cameras = db.query(Camera).all()
        activities = []
        alert_rows = get_alert_service().get_alert_history(limit=500)
        alerts_by_camera: Dict[int, int] = {}
        for row in alert_rows:
            camera_id = int(row.get("camera_id") or 0)
            if camera_id <= 0:
                continue
            alerts_by_camera[camera_id] = alerts_by_camera.get(camera_id, 0) + 1

        for camera in cameras:
            face_detections = _count_rows(
                db,
                FaceDetection,
                FaceDetection.detected_at >= time_window,
                FaceDetection.camera_id == camera.id,
            )
            vehicle_detections = _count_rows(
                db,
                VehicleEvent,
                VehicleEvent.timestamp >= time_window,
                VehicleEvent.camera_id == camera.id,
            )
            detections = face_detections + vehicle_detections

            activities.append(CameraActivity(
                camera_id=camera.id,
                camera_name=camera.name,
                detections=detections,
                avg_latency=150.0,  # TODO: actual latency data
                fps=25.0,  # TODO: actual FPS data
                alerts=alerts_by_camera.get(int(camera.id), 0)
            ))

        self.camera_activities = activities

    def _update_cross_camera_routes(self, db, time_window):
        """Update cross-camera movement routes"""
        # This is a simplified implementation
        # In a real system, you'd track person/vehicle movements across cameras
        routes = []

        # Mock data for demonstration
        routes.append(CrossCameraRoute(
            from_camera=1,
            to_camera=2,
            transitions=15,
            avg_time=45.0
        ))
        routes.append(CrossCameraRoute(
            from_camera=2,
            to_camera=3,
            transitions=8,
            avg_time=32.0
        ))

        self.cross_camera_routes = routes

    def get_current_metrics(self) -> OpsMetrics:
        """Get current operational metrics"""
        with self._lock:
            return self.metrics

    def get_recent_alerts(self, limit: int = 50) -> List[AlertData]:
        """Get recent alerts"""
        with self._lock:
            alert_rows = get_alert_service().get_alert_history(limit=max(1, limit))
            if alert_rows:
                normalized_alerts = [self._to_alert_data(row) for row in alert_rows]
                self.alerts = normalized_alerts[-100:]
                return normalized_alerts[:limit]
            return self.alerts[-limit:] if self.alerts else []

    def get_camera_activities(self) -> List[CameraActivity]:
        """Get camera activity data"""
        with self._lock:
            return self.camera_activities.copy()

    def get_cross_camera_routes(self) -> List[CrossCameraRoute]:
        """Get cross-camera movement routes"""
        with self._lock:
            return self.cross_camera_routes.copy()

    def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        """Acknowledge an alert"""
        with self._lock:
            for alert in self.alerts:
                if alert.id == alert_id and not alert.acknowledged:
                    alert.acknowledged = True
                    alert.acknowledged_by = user
                    alert.acknowledged_at = datetime.utcnow().isoformat()
                    return True
        return False

    def add_alert(self, alert: AlertData):
        """Add a new alert"""
        with self._lock:
            self.alerts.append(alert)
            # Keep only last 100 alerts
            if len(self.alerts) > 100:
                self.alerts = self.alerts[-100:]

    @staticmethod
    def _to_alert_data(raw: Dict[str, Any]) -> AlertData:
        camera_id = int(raw.get("camera_id") or 0)
        message = str(raw.get("message") or raw.get("type") or "Alert")
        return AlertData(
            id=str(raw.get("id") or f"alert-{camera_id}-{raw.get('timestamp') or datetime.utcnow().isoformat()}"),
            type=str(raw.get("type") or "system"),
            severity=str(raw.get("severity") or "medium"),
            title=message,
            description=message,
            camera_id=camera_id,
            camera_name=str(raw.get("camera_name") or f"Camera {camera_id or '?'}"),
            timestamp=str(raw.get("timestamp") or datetime.utcnow().isoformat()),
            acknowledged=bool(raw.get("acknowledged", False)),
            acknowledged_by=(
                str(raw.get("acknowledged_by"))
                if raw.get("acknowledged_by") is not None
                else None
            ),
            acknowledged_at=(
                str(raw.get("acknowledged_at"))
                if raw.get("acknowledged_at") is not None
                else None
            ),
        )

# Global service instance
_soc_dashboard_service: Optional[SocDashboardService] = None

def get_soc_dashboard_service() -> SocDashboardService:
    """Get the global SOC dashboard service instance"""
    global _soc_dashboard_service
    if _soc_dashboard_service is None:
        _soc_dashboard_service = SocDashboardService()
        _soc_dashboard_service.start()
    return _soc_dashboard_service
