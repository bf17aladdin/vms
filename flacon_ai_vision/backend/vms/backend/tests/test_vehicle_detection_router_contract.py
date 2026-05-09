from __future__ import annotations

import inspect
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vms.backend.core.database import get_db
from vms.backend.routers import vehicle_detection


def _assert_legacy_naive_isoformat(raw: str) -> None:
    parsed = datetime.fromisoformat(raw)
    assert parsed.tzinfo is None


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
    app.include_router(vehicle_detection.router)

    def override_get_db():
        yield db_session

    def override_current_user():
        return {"sub": "operator@example.com", "user_id": 17, "role": "operator"}

    def override_current_admin():
        return {"sub": "admin@example.com", "user_id": 1, "role": "admin"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[vehicle_detection.get_current_user] = override_current_user
    app.dependency_overrides[vehicle_detection.get_current_admin] = override_current_admin
    return app


def test_vehicle_detections_list_route_keeps_legacy_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    monkeypatch.setattr(
        vehicle_detection.VehicleService,
        "get_all_detections",
        staticmethod(
            lambda db, camera_id=None, skip=0, limit=100: [
                {
                    "id": 5,
                    "license_plate": "123 TUNIS 4567",
                    "vehicle_type": "car",
                    "color": "white",
                    "camera_id": 3,
                    "detected_at": "2026-05-08T08:00:00+00:00",
                }
            ]
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/vehicle-detections/?camera_id=3&skip=0&limit=25")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"count", "detections", "message"}
    assert payload["count"] == 1
    assert payload["message"] == "Vehicle detections retrieved successfully"
    assert payload["detections"][0]["license_plate"] == "123 TUNIS 4567"


def test_vehicle_detect_route_keeps_legacy_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)
    monkeypatch.setattr(vehicle_detection, "ensure_manual_inference_allowed", lambda operation: None)
    monkeypatch.setattr(
        vehicle_detection.VehicleService,
        "detect_vehicles_in_stream",
        staticmethod(
            lambda db, camera_id, confidence_threshold=0.5: [
                {
                    "camera_id": camera_id,
                    "vehicle_detected": True,
                    "plate_number": "456 TUNIS 9999",
                    "confidence": 0.93,
                }
            ]
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/vehicle-detections/detect/7?confidence=0.61")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"camera_id", "detections_count", "detections", "timestamp"}
    assert payload["camera_id"] == 7
    assert payload["detections_count"] == 1
    assert payload["detections"][0]["plate_number"] == "456 TUNIS 9999"
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_track_plate_route_keeps_legacy_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)
    monkeypatch.setattr(
        vehicle_detection.VehicleService,
        "track_plate",
        staticmethod(
            lambda db, plate_number: [
                {
                    "id": 91,
                    "license_plate": plate_number,
                    "camera_id": 4,
                    "detected_at": "2026-05-08T09:00:00",
                }
            ]
        ),
    )

    with TestClient(app) as client:
        response = client.post("/api/vehicle-detections/track-plate?plate_number=AA-123-BB")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"plate", "detections_count", "detections", "timestamp"}
    assert payload["plate"] == "AA-123-BB"
    assert payload["detections_count"] == 1
    assert payload["detections"][0]["license_plate"] == "AA-123-BB"
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_vehicle_statistics_route_keeps_legacy_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    def fake_get_statistics(self, days: int = 7):
        assert days == 7
        return {
            "total": 12,
            "by_type": {"car": 10, "truck": 2},
            "by_camera": {"3": 8, "7": 4},
        }

    monkeypatch.setattr(vehicle_detection.VehicleService, "get_statistics", fake_get_statistics)

    with TestClient(app) as client:
        response = client.get("/api/vehicle-detections/statistics")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"total_detections", "by_type", "by_camera", "timestamp"}
    assert payload["total_detections"] == 12
    assert payload["by_type"]["car"] == 10
    assert payload["by_camera"]["7"] == 4
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_vehicle_alert_and_zone_routes_keep_legacy_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)
    now_iso = datetime.now(timezone.utc).isoformat()

    monkeypatch.setattr(
        vehicle_detection.VehicleService,
        "get_alerts",
        staticmethod(
            lambda db, skip=0, limit=50: [
                {
                    "id": 11,
                    "source": "security_alert",
                    "type": "unknown_plate",
                    "severity": "high",
                    "timestamp": now_iso,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        vehicle_detection.VehicleService,
        "create_alert_zone",
        staticmethod(
            lambda db, camera_id, zone_name: {
                "id": 44,
                "camera_id": camera_id,
                "zone_name": zone_name,
                "created_at": now_iso,
            }
        ),
    )

    with TestClient(app) as client:
        alerts_response = client.get("/api/vehicle-detections/alerts?skip=0&limit=10")
        zone_response = client.post("/api/vehicle-detections/set-alert-zone/5?zone_name=Gate-A")

    assert alerts_response.status_code == 200, alerts_response.text
    alerts_payload = alerts_response.json()
    assert set(alerts_payload.keys()) == {"count", "alerts", "message"}
    assert alerts_payload["count"] == 1
    assert alerts_payload["alerts"][0]["type"] == "unknown_plate"
    assert alerts_payload["message"] == "Vehicle alerts retrieved successfully"

    assert zone_response.status_code == 200, zone_response.text
    zone_payload = zone_response.json()
    assert set(zone_payload.keys()) == {"zone_id", "camera_id", "zone_name", "message"}
    assert zone_payload["zone_id"] == 44
    assert zone_payload["camera_id"] == 5
    assert zone_payload["zone_name"] == "Gate-A"
    assert zone_payload["message"] == "Alert zone created successfully"
