from __future__ import annotations

import inspect
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vms.backend.core.database import get_db
from vms.backend.models import Base, Camera
from vms.backend.routers import cameras


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "camera_discovery_router.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

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
    app.include_router(cameras.router)

    def override_get_db():
        yield db_session

    def override_require_operator():
        return {"sub": "operator@example.com", "user_id": 17, "role": "operator", "tenant_id": None}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[cameras.require_operator] = override_require_operator
    return app


def test_discovery_connect_route_creates_camera_without_manual_rtsp_entry(
    app,
    db_session,
    monkeypatch,
) -> None:
    _patch_testclient_httpx(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/cameras/discovery/connect",
            json={
                "items": [
                    {
                        "ip_address": "192.168.1.24",
                        "port": 554,
                        "connection_status": "connected",
                        "rtsp_working_url": "rtsp://192.168.1.24:554/Streaming/Channels/101",
                        "rtsp_candidates": [
                            "rtsp://192.168.1.24:554/Streaming/Channels/101",
                        ],
                        "onvif": {
                            "device": {
                                "manufacturer": "Hikvision",
                                "model": "DS-2CD2043G0",
                            }
                        },
                    }
                ],
                "streaming_enabled": True,
                "ai_enabled": True,
                "motion_detection_enabled": True,
                "object_detection_enabled": True,
                "auto_test": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["created"] == 1
    assert payload["updated"] == 0
    assert payload["connected"] == 1

    rows = db_session.query(Camera).all()
    assert len(rows) == 1
    camera = rows[0]
    assert camera.ip_address == "192.168.1.24"
    assert camera.port == 554
    assert camera.rtsp_url == "rtsp://192.168.1.24:554/Streaming/Channels/101"
    assert camera.connection_status == "connected"
    assert "Hikvision" in camera.name
    assert camera.ai_enabled is True


def test_discovery_connect_route_updates_existing_camera_instead_of_creating_duplicate(
    app,
    db_session,
    monkeypatch,
) -> None:
    _patch_testclient_httpx(monkeypatch)

    existing = Camera(
        name="Front Gate",
        owner_id=17,
        ip_address="192.168.1.30",
        port=8554,
        rtsp_url="rtsp://192.168.1.30:8554/legacy",
        location="Main entrance",
        connection_status="unknown",
        is_active=True,
        streaming_enabled=False,
        motion_detection_enabled=True,
        object_detection_enabled=True,
        detection_sensitivity=50,
        ai_enabled=False,
    )
    db_session.add(existing)
    db_session.commit()
    db_session.refresh(existing)

    with TestClient(app) as client:
        response = client.post(
            "/api/cameras/discovery/connect",
            json={
                "items": [
                    {
                        "known_camera_id": existing.id,
                        "ip_address": "192.168.1.30",
                        "port": 554,
                        "connection_status": "connected",
                        "rtsp_working_url": "rtsp://192.168.1.30:554/Streaming/Channels/101",
                        "rtsp_candidates": [
                            "rtsp://192.168.1.30:554/Streaming/Channels/101",
                        ],
                    }
                ],
                "streaming_enabled": True,
                "auto_test": False,
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["created"] == 0
    assert payload["updated"] == 1
    assert payload["connected"] == 1

    rows = db_session.query(Camera).order_by(Camera.id.asc()).all()
    assert len(rows) == 1
    camera = rows[0]
    assert camera.id == existing.id
    assert camera.name == "Front Gate"
    assert camera.port == 554
    assert camera.rtsp_url == "rtsp://192.168.1.30:554/Streaming/Channels/101"
    assert camera.streaming_enabled is True
    assert camera.connection_status == "connected"
