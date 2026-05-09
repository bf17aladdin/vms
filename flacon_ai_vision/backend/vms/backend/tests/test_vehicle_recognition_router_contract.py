from __future__ import annotations

import inspect

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vms.backend.core.database import get_db
from vms.backend.routers import vehicle_recognition


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _patch_testclient_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    if "app" in inspect.signature(httpx.Client.__init__).parameters:
        return

    original_init = httpx.Client.__init__

    def patched_init(self, *args, app=None, **kwargs):
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)


@pytest.fixture()
def app(db_session):
    app = FastAPI()
    app.include_router(vehicle_recognition.router)

    def override_get_db():
        yield db_session

    def override_current_user():
        return {"sub": "operator@example.com", "user_id": 17, "role": "operator"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[vehicle_recognition.get_current_user] = override_current_user
    return app


def test_vehicle_statistics_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    stats_payload = {
        "period_hours": 24,
        "camera_id": 3,
        "total_events": 12,
        "avg_confidence": 0.9342,
        "pipeline": {"detector_backend": "yolo:cpu", "ocr_backend": "easyocr"},
    }

    class _FakeVehiclePipeline:
        def __init__(self, _db):
            pass

        def get_statistics(self, *, hours: int = 24, camera_id=None):
            assert hours == 24
            assert camera_id == 3
            return stats_payload

    monkeypatch.setattr(vehicle_recognition, "VehicleRecognitionPipeline", _FakeVehiclePipeline)

    with TestClient(app) as client:
        response = client.get("/api/vehicle/statistics?hours=24&camera_id=3")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"success", "statistics"}
    assert payload["success"] is True
    assert payload["statistics"] == stats_payload


def test_vehicle_live_monitoring_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    monitoring_payload = {
        "summary": {"total_events": 4, "avg_latency_ms": 22.1},
        "buckets": [{"bucket_start": "2026-05-08T08:00:00+00:00", "events": 2}],
        "recent": [{"event_id": 91, "plate_number": "123 TUNIS 4567"}],
    }

    class _FakeVehiclePipeline:
        def __init__(self, _db):
            pass

        def get_live_monitoring(self, **kwargs):
            assert kwargs["camera_id"] == 5
            assert kwargs["window_minutes"] == 30
            assert kwargs["bucket_seconds"] == 120
            assert kwargs["recent_limit"] == 4
            return monitoring_payload

    monkeypatch.setattr(vehicle_recognition, "VehicleRecognitionPipeline", _FakeVehiclePipeline)

    with TestClient(app) as client:
        response = client.get(
            "/api/vehicle/monitor/live?camera_id=5&window_minutes=30&bucket_seconds=120&recent_limit=4"
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"success", "monitoring"}
    assert payload["success"] is True
    assert payload["monitoring"] == monitoring_payload


def test_vehicle_access_logs_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    logs_payload = [
        {
            "id": 201,
            "camera_id": 8,
            "plate_number": "MC-200",
            "decision": "allowed",
            "direction": "IN",
        }
    ]

    class _FakeVehiclePipeline:
        def __init__(self, _db):
            pass

        def get_access_logs(self, **kwargs):
            assert kwargs["camera_id"] == 8
            assert kwargs["plate_number"] == "MC-200"
            assert kwargs["decision"] == "allowed"
            assert kwargs["direction"] == "IN"
            return logs_payload

    monkeypatch.setattr(vehicle_recognition, "VehicleRecognitionPipeline", _FakeVehiclePipeline)

    with TestClient(app) as client:
        response = client.get(
            "/api/vehicle/access/logs?camera_id=8&plate_number=MC-200&decision=allowed&direction=IN"
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"success", "count", "logs"}
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["logs"] == logs_payload


def test_vehicle_security_alerts_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    alerts_payload = [
        {
            "id": 301,
            "camera_id": 4,
            "severity_level": "critical",
            "resolution_status": "open",
            "type": "camera_tamper",
        }
    ]

    class _FakeVehiclePipeline:
        def __init__(self, _db):
            pass

        def get_security_alerts(self, **kwargs):
            assert kwargs["camera_id"] == 4
            assert kwargs["severity_level"] == "critical"
            assert kwargs["resolution_status"] == "open"
            return alerts_payload

    monkeypatch.setattr(vehicle_recognition, "VehicleRecognitionPipeline", _FakeVehiclePipeline)

    with TestClient(app) as client:
        response = client.get(
            "/api/vehicle/access/alerts?camera_id=4&severity_level=critical&resolution_status=open"
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"success", "count", "alerts"}
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["alerts"] == alerts_payload
