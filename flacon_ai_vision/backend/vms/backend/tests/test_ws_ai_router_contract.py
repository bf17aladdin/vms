from __future__ import annotations

import inspect
from datetime import datetime

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vms.backend.routers import ws_ai


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
    app.include_router(ws_ai.router)
    return app


def test_ws_ai_stream_frame_and_stats_keep_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    async def fake_authenticate_websocket(_websocket, *, required=True):
        assert required is True
        return {"sub": "operator@example.com", "role": "operator"}

    class _FakePipeline:
        async def process_frame(self, frame, db=None):
            assert frame.shape == (8, 8, 3)
            assert db is None
            return {
                "timestamp": "2026-05-08T10:15:00+00:00",
                "motion": {"detected": True, "confidence": 0.82},
                "objects": [{"class": "car"}, {"class": "person"}],
                "faces": [{"id": 1}],
                "vehicles": [{"id": 10}, {"id": 11}],
                "latency_ms": 31.2,
                "ai_latency_ms": 18.4,
            }

        def get_stats(self):
            return {"frames_processed": 12, "avg_latency_ms": 28.1}

    class _FakeCV2:
        IMREAD_COLOR = 1

        @staticmethod
        def imdecode(_frame_array, _flag):
            return np.zeros((8, 8, 3), dtype=np.uint8)

    monkeypatch.setattr(ws_ai, "authenticate_websocket", fake_authenticate_websocket)
    monkeypatch.setattr(
        ws_ai,
        "get_manual_inference_guard_status",
        lambda: {"allowed": True, "message": "Manual inference allowed."},
    )
    monkeypatch.setattr(ws_ai, "get_pipeline", lambda camera_id, camera_name=None: _FakePipeline())
    monkeypatch.setattr(ws_ai, "cv2", _FakeCV2)
    monkeypatch.setattr(ws_ai, "np", np)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/ai/stream/cam-77") as websocket:
            websocket.send_json({"action": "frame_data", "frame_data": "ZmFrZS1mcmFtZQ=="})
            frame_payload = websocket.receive_json()

            assert set(frame_payload.keys()) == {
                "camera_id",
                "timestamp",
                "detections",
                "latency_ms",
                "ai_latency_ms",
            }
            assert frame_payload["camera_id"] == "cam-77"
            assert frame_payload["timestamp"] == "2026-05-08T10:15:00+00:00"
            assert set(frame_payload["detections"].keys()) == {
                "motion",
                "objects",
                "faces_count",
                "vehicles_count",
            }
            assert frame_payload["detections"]["faces_count"] == 1
            assert frame_payload["detections"]["vehicles_count"] == 2
            assert frame_payload["detections"]["objects"] == [{"class": "car"}, {"class": "person"}]
            assert frame_payload["latency_ms"] == 31.2
            assert frame_payload["ai_latency_ms"] == 18.4

            websocket.send_json({"action": "get_stats"})
            stats_payload = websocket.receive_json()

            assert set(stats_payload.keys()) == {"camera_id", "stats"}
            assert stats_payload["camera_id"] == "cam-77"
            assert stats_payload["stats"] == {"frames_processed": 12, "avg_latency_ms": 28.1}


def test_ws_ai_stream_blocked_guard_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    async def fake_authenticate_websocket(_websocket, *, required=True):
        assert required is True
        return {"sub": "operator@example.com", "role": "operator"}

    monkeypatch.setattr(ws_ai, "authenticate_websocket", fake_authenticate_websocket)
    monkeypatch.setattr(
        ws_ai,
        "get_manual_inference_guard_status",
        lambda: {
            "allowed": False,
            "mode": "production",
            "production_runtime_running": True,
            "message": "Manual inference blocked: production runtime is active.",
        },
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws/ai/stream/cam-prod") as websocket:
            payload = websocket.receive_json()

    assert set(payload.keys()) == {"code", "message", "guard"}
    assert payload["code"] == "MANUAL_INFERENCE_BLOCKED"
    assert payload["guard"]["allowed"] is False
    assert payload["guard"]["mode"] == "production"


def test_ws_ai_status_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    class _FakeProcessor:
        pipelines = {"cam-1": object(), "cam-2": object()}

        def get_all_stats(self):
            return {
                "cam-1": {"frames_processed": 14, "avg_latency_ms": 21.3},
                "cam-2": {"frames_processed": 9, "avg_latency_ms": 27.8},
            }

    monkeypatch.setattr(ws_ai, "get_async_processor", lambda: _FakeProcessor())
    monkeypatch.setattr(
        ws_ai,
        "connected_clients",
        {"cam-1_socket": object(), "cam-2_socket": object()},
    )

    with TestClient(app) as client:
        response = client.get("/ws/status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {
        "connected_clients",
        "active_pipelines",
        "clients",
        "pipelines",
        "timestamp",
    }
    assert payload["connected_clients"] == 2
    assert payload["active_pipelines"] == 2
    assert set(payload["clients"]) == {"cam-1_socket", "cam-2_socket"}
    assert payload["pipelines"]["cam-1"]["frames_processed"] == 14
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_ws_ai_cameras_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    class _FakeProcessor:
        def get_all_stats(self):
            return {
                "cam-77": {
                    "camera_name": "North Gate",
                    "frames_processed": 33,
                    "errors": 1,
                },
                "cam-88": {
                    "camera_name": "Parking",
                    "frames_processed": 7,
                    "errors": 0,
                },
            }

    monkeypatch.setattr(ws_ai, "get_async_processor", lambda: _FakeProcessor())
    monkeypatch.setattr(ws_ai, "connected_clients", {"cam-77_socket": object()})

    with TestClient(app) as client:
        response = client.get("/ws/cameras")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"total_cameras", "cameras", "timestamp"}
    assert payload["total_cameras"] == 2
    assert payload["cameras"] == [
        {
            "id": "cam-77",
            "name": "North Gate",
            "frames_processed": 33,
            "errors": 1,
            "connected": True,
        },
        {
            "id": "cam-88",
            "name": "Parking",
            "frames_processed": 7,
            "errors": 0,
            "connected": False,
        },
    ]
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_ws_ai_broadcast_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    class _FakeSocket:
        def __init__(self):
            self.messages = []

        async def send_json(self, payload):
            self.messages.append(payload)

    fake_socket = _FakeSocket()
    monkeypatch.setattr(ws_ai, "connected_clients", {"cam-77_socket": fake_socket})

    with TestClient(app) as client:
        response = client.post(
            "/ws/broadcast/system_alert",
            json={"severity": "high", "title": "GPU overload"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {
        "status": "broadcasted",
        "clients_notified": 1,
        "clients_failed": 0,
    }
    assert len(fake_socket.messages) == 1
    outbound = fake_socket.messages[0]
    assert set(outbound.keys()) == {"event_type", "payload", "timestamp"}
    assert outbound["event_type"] == "system_alert"
    assert outbound["payload"] == {"severity": "high", "title": "GPU overload"}
    _assert_legacy_naive_isoformat(outbound["timestamp"])
