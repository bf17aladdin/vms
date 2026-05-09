from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vms.backend.routers import ws


def _assert_legacy_naive_isoformat(raw: str) -> None:
    parsed = datetime.fromisoformat(raw)
    assert parsed.tzinfo is None


def _patch_testclient_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    if "app" in inspect.signature(httpx.Client.__init__).parameters:
        return

    original_init = httpx.Client.__init__

    def patched_init(self, *args, app=None, **kwargs):
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)


@pytest.fixture()
def app():
    app = FastAPI()
    app.include_router(ws.router)
    return app


class _FakeRealtimeManager:
    def __init__(self):
        self.active_connections = set()
        self.broadcasts = []

    async def connect(self, websocket, *, meta=None):
        self.active_connections.add(websocket)

    async def disconnect(self, websocket):
        self.active_connections.discard(websocket)

    async def broadcast_event(self, payload):
        self.broadcasts.append(payload)

    def schedule_broadcast(self, payload):
        self.broadcasts.append(payload)
        return True


def test_ws_analytics_ping_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    async def fake_authenticate_websocket(_websocket, *, required=True):
        assert required is True
        return {"sub": "operator@example.com", "role": "operator"}

    monkeypatch.setattr(ws, "authenticate_websocket", fake_authenticate_websocket)
    monkeypatch.setattr(ws, "analytics_manager", ws.ConnectionManager())

    with TestClient(app) as client:
        with client.websocket_connect("/ws/analytics") as websocket:
            websocket.send_text(json.dumps({"action": "ping"}))
            payload = websocket.receive_json()

    assert payload["action"] == "pong"
    assert set(payload.keys()) == {"action", "timestamp"}
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_api_ws_connection_and_pong_keep_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    async def fake_authenticate_websocket(_websocket, *, required=True):
        assert required is True
        return {
            "sub": "operator@example.com",
            "username": "operator@example.com",
            "user_id": 17,
            "tenant_id": 4,
            "role": "operator",
        }

    realtime_manager = _FakeRealtimeManager()
    monkeypatch.setattr(ws, "authenticate_websocket", fake_authenticate_websocket)
    monkeypatch.setattr(ws, "get_realtime_manager", lambda: realtime_manager)

    with TestClient(app) as client:
        with client.websocket_connect("/api/ws") as websocket:
            connection_payload = websocket.receive_json()
            websocket.send_text(json.dumps({"action": "ping"}))
            pong_payload = websocket.receive_json()

    assert set(connection_payload.keys()) == {"type", "event", "timestamp", "channel", "data"}
    assert connection_payload["type"] == "connection_established"
    assert connection_payload["event"] == "connection_established"
    assert connection_payload["channel"] == "connection"
    assert connection_payload["data"] == {
        "message": "Connected to FALCON AI VISION",
        "authenticated": True,
        "user_id": 17,
        "username": "operator@example.com",
    }
    _assert_legacy_naive_isoformat(connection_payload["timestamp"])

    assert set(pong_payload.keys()) == {"type", "event", "timestamp", "channel", "data"}
    assert pong_payload["type"] == "pong"
    assert pong_payload["event"] == "pong"
    assert pong_payload["channel"] == "connection"
    assert pong_payload["data"] == {"action": "pong"}
    _assert_legacy_naive_isoformat(pong_payload["timestamp"])


def test_broadcast_analytics_keeps_contract(monkeypatch) -> None:
    class _FakeConnectionManager:
        def __init__(self):
            self.payloads = []

        async def broadcast(self, payload):
            self.payloads.append(payload)

    analytics_manager = _FakeConnectionManager()
    monkeypatch.setattr(ws, "analytics_manager", analytics_manager)

    asyncio.run(ws.broadcast_analytics({"camera_id": 9, "fps": 24.5}))

    assert len(analytics_manager.payloads) == 1
    payload = analytics_manager.payloads[0]
    assert payload["camera_id"] == 9
    assert payload["fps"] == 24.5
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_broadcast_event_keeps_contract(monkeypatch) -> None:
    class _FakeConnectionManager:
        def __init__(self):
            self.payloads = []

        async def broadcast(self, payload):
            self.payloads.append(payload)

    events_manager = _FakeConnectionManager()
    realtime_manager = _FakeRealtimeManager()
    monkeypatch.setattr(ws, "events_manager", events_manager)
    monkeypatch.setattr(ws, "get_realtime_manager", lambda: realtime_manager)

    asyncio.run(
        ws.broadcast_event(
            "camera_status",
            5,
            "Camera online",
            {"fps": 29.7, "status": "connected"},
        )
    )

    assert len(events_manager.payloads) == 1
    event_payload = events_manager.payloads[0]
    assert set(event_payload.keys()) == {"type", "camera_id", "message", "timestamp", "data"}
    assert event_payload["type"] == "camera_status"
    assert event_payload["camera_id"] == 5
    assert event_payload["message"] == "Camera online"
    assert event_payload["data"] == {"fps": 29.7, "status": "connected"}
    _assert_legacy_naive_isoformat(event_payload["timestamp"])

    assert len(realtime_manager.broadcasts) == 1
    api_payload = realtime_manager.broadcasts[0]
    assert set(api_payload.keys()) == {"type", "event", "timestamp", "channel", "data"}
    assert api_payload["type"] == "camera_status"
    assert api_payload["event"] == "camera_status"
    assert api_payload["channel"] == "system"
    assert api_payload["data"]["camera_id"] == 5
    assert api_payload["data"]["message"] == "Camera online"
    _assert_legacy_naive_isoformat(api_payload["timestamp"])
    _assert_legacy_naive_isoformat(api_payload["data"]["timestamp"])
