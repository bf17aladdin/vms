# vms/backend/routers/ws.py - WebSocket endpoints for analytics, alerts, and /api/ws

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.time_utils import utc_now_naive_iso
from ..core.realtime_manager import get_realtime_manager
from ..core.security import authenticate_websocket
from ..services.alert_service import (
    get_alert_service,
    filter_alert_payloads,
    get_allowed_alert_types,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["websocket"])


class ConnectionManager:
    """Manage dedicated websocket channels with safe broadcast iteration."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info("Client connected. Total=%s", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.discard(websocket)
            logger.info("Client disconnected. Total=%s", len(self.active_connections))

    async def broadcast(self, message: dict) -> None:
        if not self.active_connections:
            return

        dead_connections = []
        for connection in tuple(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as exc:
                logger.debug("WebSocket send failed: %s", exc)
                dead_connections.append(connection)

        for connection in dead_connections:
            await self.disconnect(connection)

    async def broadcast_text(self, data: str) -> None:
        if not self.active_connections:
            return

        dead_connections = []
        for connection in tuple(self.active_connections):
            try:
                await connection.send_text(data)
            except Exception:
                dead_connections.append(connection)

        for connection in dead_connections:
            await self.disconnect(connection)

    async def send_personal(self, websocket: WebSocket, message: dict) -> None:
        try:
            await websocket.send_json(message)
        except Exception as exc:
            logger.debug("Personal WebSocket send failed: %s", exc)
            await self.disconnect(websocket)


analytics_manager = ConnectionManager()
alerts_manager = ConnectionManager()
events_manager = ConnectionManager()


def _api_timestamp() -> str:
    return utc_now_naive_iso()


def _infer_api_channel(event_type: str) -> str:
    normalized = str(event_type or "").strip().lower()
    if normalized.startswith("connection_") or normalized in {"ping", "pong"}:
        return "connection"
    if normalized in {"alert", "alert_created", "system_alert"} or normalized.endswith("_alert"):
        return "alerts"
    if normalized == "occupancy" or normalized.startswith("occupancy_"):
        return "occupancy"
    if normalized == "camera_status" or normalized.endswith("_status"):
        return "system"
    if normalized.startswith("unknown_") or normalized == "gallery_updated":
        return "gallery"
    if (
        normalized.endswith("_detected")
        or normalized.endswith("_match")
        or normalized.endswith("_upsert")
        or normalized.startswith("person_")
        or normalized.startswith("vehicle_")
    ):
        return "detection"
    return "event"


def _api_message(
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    channel: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "type": str(event_type),
        "event": str(event_type),
        "timestamp": _api_timestamp(),
        "channel": str(channel or _infer_api_channel(event_type)),
        "data": data or {},
    }


async def broadcast_api_event(
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    channel: Optional[str] = None,
) -> None:
    await get_realtime_manager().broadcast_event(
        _api_message(event_type=event_type, data=data, channel=channel)
    )


def broadcast_api_event_sync(
    event_type: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    channel: Optional[str] = None,
) -> None:
    payload = _api_message(event_type=event_type, data=data, channel=channel)
    if not get_realtime_manager().schedule_broadcast(payload):
        logger.debug("Unable to schedule /api/ws broadcast from sync context")


@router.websocket("/ws/analytics")
async def websocket_analytics(websocket: WebSocket):
    current_user = await authenticate_websocket(websocket)
    if current_user is None:
        return

    await analytics_manager.connect(websocket)

    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            try:
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await websocket.send_json({"action": "pong", "timestamp": _api_timestamp()})
            except json.JSONDecodeError:
                pass
    except asyncio.TimeoutError:
        logger.debug("Analytics WebSocket keepalive timeout")
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("Analytics WebSocket error: %s", exc)
    finally:
        await analytics_manager.disconnect(websocket)


@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    current_user = await authenticate_websocket(websocket)
    if current_user is None:
        return

    await alerts_manager.connect(websocket)

    service = get_alert_service()
    tenant_id = current_user.get("tenant_id")
    requested_type = websocket.query_params.get("type") or websocket.query_params.get("alert_type")
    raw_camera_id = websocket.query_params.get("camera_id")
    try:
        requested_camera_id = int(raw_camera_id) if raw_camera_id is not None else None
    except (TypeError, ValueError):
        requested_camera_id = None

    allowed_types = get_allowed_alert_types()
    initial_alerts = filter_alert_payloads(
        service.get_active_alerts(),
        allowed_types=allowed_types,
        requested_type=requested_type,
        camera_id=requested_camera_id,
        tenant_id=tenant_id,
    )
    for alert in initial_alerts:
        await websocket.send_json(alert)

    async def on_alert(alert):
        payload = alert.to_dict()
        filtered = filter_alert_payloads(
            [payload],
            allowed_types=allowed_types,
            requested_type=requested_type,
            camera_id=requested_camera_id,
            tenant_id=tenant_id,
        )
        if filtered:
            await alerts_manager.send_personal(websocket, filtered[0])

    callback_id = service.register_callback(on_alert, loop=asyncio.get_running_loop())

    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            try:
                msg = json.loads(data)
                if msg.get("action") == "acknowledge":
                    service.acknowledge_alert(msg.get("alert_id"))
                elif msg.get("action") == "ping":
                    await websocket.send_json({"action": "pong"})
            except json.JSONDecodeError:
                pass
    except asyncio.TimeoutError:
        pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("Alerts WebSocket error: %s", exc)
    finally:
        service.unregister_callback(callback_id)
        await alerts_manager.disconnect(websocket)


@router.websocket("/api/ws")
async def websocket_root_api(websocket: WebSocket):
    current_user = await authenticate_websocket(websocket)
    if current_user is None:
        return

    realtime_manager = get_realtime_manager()
    user_info = str(
        current_user.get("sub")
        or current_user.get("username")
        or current_user.get("user_id")
        or "authenticated"
    )

    await websocket.accept()
    await realtime_manager.connect(websocket, meta={"tenant_id": current_user.get("tenant_id")})
    logger.info("/api/ws client connected (%s)", user_info)

    try:
        await websocket.send_json(
            _api_message(
                event_type="connection_established",
                data={
                    "message": "Connected to FALCON AI VISION",
                    "authenticated": True,
                    "user_id": current_user.get("user_id"),
                    "username": current_user.get("sub") or current_user.get("username"),
                },
                channel="connection",
            )
        )

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                try:
                    msg = json.loads(data)
                    if msg.get("action") == "ping":
                        await websocket.send_json(
                            _api_message(
                                event_type="pong",
                                data={"action": "pong"},
                                channel="connection",
                            )
                        )
                except json.JSONDecodeError:
                    logger.debug("/api/ws invalid JSON: %s", data[:100])
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json(
                        _api_message(
                            event_type="ping",
                            data={"action": "ping"},
                            channel="connection",
                        )
                    )
                except Exception as exc:
                    logger.debug("/api/ws ping failed: %s", exc)
                    break
    except WebSocketDisconnect:
        logger.info("/api/ws client disconnected (%s)", user_info)
    except Exception as exc:
        logger.error("/api/ws error: %s", exc)
    finally:
        try:
            await realtime_manager.disconnect(websocket)
            await websocket.close()
        except Exception:
            pass
        logger.debug("/api/ws session closed (%s)", user_info)


async def broadcast_analytics(analytics_data: Dict) -> None:
    message = {
        "timestamp": utc_now_naive_iso(),
        **analytics_data,
    }
    await analytics_manager.broadcast(message)


async def broadcast_alert(alert) -> None:
    payload = alert.to_dict()
    await alerts_manager.broadcast(payload)
    await get_realtime_manager().broadcast_event(
        _api_message(
            event_type="alert_created",
            data=payload,
            channel="alerts",
        )
    )


async def broadcast_event(event_type: str, camera_id: int, message: str, data: dict = None) -> None:
    event = {
        "type": event_type,
        "camera_id": camera_id,
        "message": message,
        "timestamp": utc_now_naive_iso(),
        "data": data or {},
    }
    await events_manager.broadcast(event)
    await get_realtime_manager().broadcast_event(
        _api_message(
            event_type=event_type,
            data=event,
            channel="system",
        )
    )


def get_websocket_stats() -> Dict:
    realtime_manager = get_realtime_manager()
    return {
        "analytics_clients": len(analytics_manager.active_connections),
        "alerts_clients": len(alerts_manager.active_connections),
        "events_clients": len(events_manager.active_connections),
        "api_clients": len(realtime_manager.active_connections),
        "total_clients": (
            len(analytics_manager.active_connections)
            + len(alerts_manager.active_connections)
            + len(events_manager.active_connections)
            + len(realtime_manager.active_connections)
        ),
    }
