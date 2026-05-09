from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import warnings
from pathlib import Path
from uuid import uuid4


BACKEND_PACKAGE_ROOT = Path(__file__).resolve().parents[4]
if str(BACKEND_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_PACKAGE_ROOT))

TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="falcon-api-integration-"))
TEST_DB_PATH = TEST_RUNTIME_DIR / "integration.sqlite3"

os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB_PATH.as_posix()}")
os.environ.setdefault("FACE_PGVECTOR_ENABLED", "false")
os.environ.setdefault("REQUEST_LOGGING_ENABLED", "false")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_FILE_PATH", str((TEST_RUNTIME_DIR / "integration.log").resolve()))
os.environ.setdefault("SECRET_KEY", "integration-test-secret-key")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("RELOAD", "false")

import httpx
import pytest
from sqlalchemy.exc import SAWarning

import vms.backend.core.audit as audit_module
import vms.backend.core.database as database_module
from vms.backend.main import app
from vms.backend.routers import ai_services as ai_services_router


warnings.filterwarnings(
    "ignore",
    message="Can't sort tables for DROP;.*",
    category=SAWarning,
)


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    database_module.Base.metadata.drop_all(bind=database_module.engine)
    database_module.init_db()
    monkeypatch.setattr(audit_module, "SessionLocal", database_module.SessionLocal)

    previous_overrides = dict(app.dependency_overrides)
    try:
        yield
    finally:
        app.dependency_overrides = previous_overrides


async def _auth_flow(client: httpx.AsyncClient) -> dict[str, object]:
    username = f"pytest_admin_{uuid4().hex[:8]}"
    password = "PytestAdmin123!"

    register_response = await client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "full_name": "Pytest Admin",
            "email": f"{username}@example.com",
            "company_name": f"Pytest Tenant {uuid4().hex[:6]}",
            "plan": "starter",
        },
    )
    assert register_response.status_code == 200, register_response.text

    login_response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert login_response.status_code == 200, login_response.text
    login_payload = login_response.json()

    access_token = login_payload.get("access_token")
    refresh_token = login_payload.get("refresh_token")
    assert access_token, login_response.text
    assert refresh_token, login_response.text

    return {
        "username": username,
        "password": password,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "headers": {"Authorization": f"Bearer {access_token}"},
    }


async def _create_camera(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, object]:
    response = await client.post(
        "/api/cameras",
        json={
            "name": "Pytest Camera",
            "description": "Created by integration test",
            "camera_type": "mix",
            "rtsp_url": "rtsp://127.0.0.1:8554/pytest",
            "is_enabled": True,
            "is_active": True,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    camera = payload.get("camera") or {}
    assert camera.get("id"), response.text
    return camera


def test_authentication_login_refresh_and_me() -> None:
    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            auth = await _auth_flow(client)
            headers = auth["headers"]

            me_response = await client.get("/api/auth/me", headers=headers)
            assert me_response.status_code == 200, me_response.text
            me_payload = me_response.json()
            assert (me_payload.get("user") or {}).get("sub") == auth["username"]

            refresh_response = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": auth["refresh_token"]},
            )
            assert refresh_response.status_code == 200, refresh_response.text
            refreshed = refresh_response.json()
            assert refreshed.get("access_token"), refresh_response.text
            assert refreshed.get("user", {}).get("username") == auth["username"]

    asyncio.run(_run())


def test_camera_crud_flow() -> None:
    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            auth = await _auth_flow(client)
            headers = auth["headers"]

            created_camera = await _create_camera(client, headers)
            camera_id = int(created_camera["id"])

            list_response = await client.get("/api/cameras", headers=headers)
            assert list_response.status_code == 200, list_response.text
            listed_ids = {int(item["id"]) for item in list_response.json().get("cameras", [])}
            assert camera_id in listed_ids

            get_response = await client.get(f"/api/cameras/{camera_id}", headers=headers)
            assert get_response.status_code == 200, get_response.text
            assert (get_response.json().get("camera") or {}).get("name") == "Pytest Camera"

            update_response = await client.put(
                f"/api/cameras/{camera_id}",
                json={"description": "Updated by integration test", "location": "North Gate"},
                headers=headers,
            )
            assert update_response.status_code == 200, update_response.text
            updated_camera = update_response.json().get("camera") or {}
            assert updated_camera.get("description") == "Updated by integration test"
            assert updated_camera.get("location") == "North Gate"

            delete_response = await client.delete(f"/api/cameras/{camera_id}", headers=headers)
            assert delete_response.status_code == 200, delete_response.text

            missing_response = await client.get(f"/api/cameras/{camera_id}", headers=headers)
            assert missing_response.status_code == 404, missing_response.text

    asyncio.run(_run())


def test_event_creation_and_readback() -> None:
    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            auth = await _auth_flow(client)
            headers = auth["headers"]
            camera = await _create_camera(client, headers)
            camera_id = int(camera["id"])

            create_event_response = await client.post(
                "/api/events",
                json={
                    "camera_id": camera_id,
                    "event_type": "person",
                    "severity": "warning",
                    "decision": "review",
                    "description": "Integration test event",
                    "confidence": 0.91,
                    "detected_objects": {"person": 1},
                },
                headers=headers,
            )
            assert create_event_response.status_code == 200, create_event_response.text
            created_event = create_event_response.json().get("event") or {}
            event_id = int(created_event["id"])

            list_events_response = await client.get(
                f"/api/events?camera_id={camera_id}",
                headers=headers,
            )
            assert list_events_response.status_code == 200, list_events_response.text
            events = list_events_response.json().get("events") or []
            event_ids = {int(row["id"]) for row in events}
            assert event_id in event_ids

            get_event_response = await client.get(f"/api/events/{event_id}", headers=headers)
            assert get_event_response.status_code == 200, get_event_response.text
            fetched_event = get_event_response.json().get("event") or {}
            assert int(fetched_event["camera_id"]) == camera_id
            assert fetched_event.get("description") == "Integration test event"

    asyncio.run(_run())


def test_ai_detections_endpoint_with_mocks(monkeypatch) -> None:
    def _fake_face_history(self, camera_id=None, skip=0, limit=50):
        del self, skip, limit
        return [
            {
                "id": 501,
                "camera_id": int(camera_id or 0),
                "personnel_name": "Jane Operator",
                "confidence": 0.97,
                "detected_at": "2026-04-18T10:00:00",
                "status": "matched",
            }
        ]

    def _fake_vehicle_history(self, license_plate=None, camera_id=None, limit=50):
        del self, license_plate, limit
        return [
            {
                "id": 601,
                "camera_id": int(camera_id or 0),
                "license_plate": "AA123BB",
                "confidence": 0.93,
                "created_at": "2026-04-18T10:00:01",
                "status": "detected",
            }
        ]

    monkeypatch.setattr(ai_services_router.FaceRecognitionPipeline, "get_history", _fake_face_history)
    monkeypatch.setattr(ai_services_router.VehicleService, "get_detection_history", _fake_vehicle_history)

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            auth = await _auth_flow(client)
            headers = auth["headers"]
            camera = await _create_camera(client, headers)
            camera_id = int(camera["id"])

            detections_response = await client.get(
                f"/api/ai/detections?camera_id={camera_id}&limit=10",
                headers=headers,
            )
            assert detections_response.status_code == 200, detections_response.text
            payload = detections_response.json()
            detections = payload.get("detections") or []

            assert payload.get("success") is True
            assert payload.get("partial") is False
            assert payload.get("total") == 2
            assert len(detections) == 2
            assert detections[0]["type"] == "vehicle"
            assert detections[0]["label"] == "AA123BB"
            assert detections[1]["type"] == "face"
            assert detections[1]["label"] == "Jane Operator"

    asyncio.run(_run())
