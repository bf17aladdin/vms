# vms/backend/core/realtime_manager.py - WebSocket real-time events

import asyncio
from datetime import datetime
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Supported realtime event types."""

    PERSON_DETECTED = "person_detected"
    PERSON_REID_MATCH = "person_reid_match"
    VEHICLE_DETECTED = "vehicle_detected"
    ANOMALY_DETECTED = "anomaly_detected"
    CAMERA_STATUS = "camera_status"
    SYSTEM_ALERT = "system_alert"


class RealtimeManager:
    """Manage websocket clients and realtime event fan-out."""

    def __init__(self):
        self.active_connections: Set[Any] = set()
        self.connection_meta: Dict[Any, Dict[str, Any]] = {}
        self.event_history: List[Dict[str, Any]] = []
        self.max_history = 1000
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    async def connect(self, websocket: Any, *, meta: Optional[Dict[str, Any]] = None):
        """Register a new websocket connection."""
        if websocket not in self.active_connections:
            self.active_connections.add(websocket)
        if meta is not None:
            self.connection_meta[websocket] = dict(meta)
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        logger.info("WebSocket connected. Total=%s", len(self.active_connections))

    async def disconnect(self, websocket: Any):
        """Remove a websocket connection."""
        self.active_connections.discard(websocket)
        self.connection_meta.pop(websocket, None)
        logger.info("WebSocket disconnected. Total=%s", len(self.active_connections))

    async def broadcast_event(self, event_data: Dict[str, Any]):
        """Broadcast one realtime event to all active clients."""
        raw_payload = dict(event_data)
        event_type = str(raw_payload.get("type") or "unknown")
        event_timestamp = raw_payload.get("timestamp") or datetime.utcnow().isoformat()
        event_channel = str(raw_payload.get("channel") or "realtime")
        event_body = raw_payload.get("data")
        if event_body is None:
            event_body = {
                key: value
                for key, value in raw_payload.items()
                if key not in {"type", "timestamp", "channel", "data"}
            }

        payload: Dict[str, Any] = {
            "type": event_type,
            "event": event_type,
            "timestamp": event_timestamp,
            "channel": event_channel,
            "data": event_body,
        }
        if isinstance(event_body, dict):
            for key, value in event_body.items():
                payload.setdefault(key, value)

        self.event_history.append(payload)
        if len(self.event_history) > self.max_history:
            self.event_history = self.event_history[-self.max_history :]

        disconnected: Set[Any] = set()
        event_tenant = payload.get("tenant_id")
        if event_tenant is None and isinstance(payload.get("data"), dict):
            event_tenant = payload.get("data", {}).get("tenant_id")
        # Iterate over a stable snapshot so concurrent connect/disconnect calls
        # do not mutate the set while this coroutine is awaiting send_json().
        for websocket in tuple(self.active_connections):
            try:
                if event_tenant is not None:
                    conn_tenant = self.connection_meta.get(websocket, {}).get("tenant_id")
                    if conn_tenant is not None and int(conn_tenant) != int(event_tenant):
                        continue
                await websocket.send_json(payload)
            except Exception as exc:
                logger.warning("Failed to send realtime event: %s", exc)
                disconnected.add(websocket)

        for websocket in disconnected:
            self.active_connections.discard(websocket)

    def schedule_broadcast(self, event_data: Dict[str, Any]) -> bool:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast_event(event_data))
            return True
        except RuntimeError:
            pass

        if self._event_loop is not None and self._event_loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self.broadcast_event(event_data), self._event_loop)
                return True
            except Exception:
                logger.debug("Unable to schedule realtime broadcast on stored event loop", exc_info=True)
        return False

    async def broadcast_person_detection(
        self,
        personnel_id: Optional[int] = None,
        camera_id: Optional[int] = None,
        confidence: float = 0.0,
        detection: Optional[Dict[str, Any]] = None,
    ):
        payload = dict(detection or {})
        payload.setdefault("personnel_id", personnel_id)
        payload.setdefault("camera_id", camera_id)
        payload.setdefault("confidence", confidence)
        await self.broadcast_event(
            {
                "type": EventType.PERSON_DETECTED,
                "channel": "detection",
                "data": payload,
            }
        )

    async def broadcast_person_reid_match(
        self,
        source_detection: Dict[str, Any],
        match_detection: Dict[str, Any],
    ):
        await self.broadcast_event(
            {
                "type": EventType.PERSON_REID_MATCH,
                "channel": "detection",
                "data": {
                    "source_detection_id": source_detection.get("id"),
                    "match_detection_id": match_detection.get("id"),
                    "source_camera_id": source_detection.get("camera_id"),
                    "match_camera_id": match_detection.get("camera_id"),
                    "similarity": match_detection.get("similarity"),
                    "source_detection": source_detection,
                    "match_detection": match_detection,
                },
            }
        )

    async def broadcast_vehicle_detection(
        self,
        plate: Optional[str] = None,
        camera_id: Optional[int] = None,
        vehicle_type: Optional[str] = None,
        detection: Optional[Dict[str, Any]] = None,
    ):
        payload = dict(detection or {})
        payload.setdefault("license_plate", plate)
        payload.setdefault("camera_id", camera_id)
        payload.setdefault("vehicle_type", vehicle_type)
        await self.broadcast_event(
            {
                "type": EventType.VEHICLE_DETECTED,
                "channel": "detection",
                "data": payload,
            }
        )

    async def broadcast_anomaly(self, anomaly_type: str, details: Dict[str, Any]):
        await self.broadcast_event(
            {
                "type": EventType.ANOMALY_DETECTED,
                "channel": "alert",
                "data": {
                    "anomaly_type": anomaly_type,
                    "severity": details.get("severity", "warning"),
                    "details": details,
                },
            }
        )

    async def broadcast_camera_status(self, camera_id: int, status: str, fps: float = 0):
        await self.broadcast_event(
            {
                "type": EventType.CAMERA_STATUS,
                "channel": "system",
                "data": {
                    "camera_id": camera_id,
                    "status": status,
                    "fps": fps,
                },
            }
        )

    async def broadcast_alert(self, title: str, message: str, severity: str = "warning"):
        await self.broadcast_event(
            {
                "type": EventType.SYSTEM_ALERT,
                "channel": "alert",
                "data": {
                    "title": title,
                    "message": message,
                    "severity": severity,
                },
            }
        )

    def get_connection_stats(self) -> Dict[str, Any]:
        return {
            "connected_clients": len(self.active_connections),
            "event_history_size": len(self.event_history),
            "recent_events": [event for event in self.event_history[-10:]],
        }


_realtime: Optional[RealtimeManager] = None


def get_realtime_manager() -> RealtimeManager:
    global _realtime
    if _realtime is None:
        _realtime = RealtimeManager()
    return _realtime
