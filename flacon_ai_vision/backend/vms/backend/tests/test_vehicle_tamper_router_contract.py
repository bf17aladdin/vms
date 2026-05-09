from __future__ import annotations

import inspect
from datetime import datetime

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vms.backend.core.database import get_db
from vms.backend.models import Base, Camera, SecurityAlert, User
from vms.backend.routers import vehicle_recognition
from vms.backend.services.vehicle_ai.tamper_detector import TamperDetectionResult


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


def _seed_camera(db_session) -> Camera:
    user = User(
        username="tamper_test_operator",
        hashed_password="not-used-in-test",
        role="operator",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    camera = Camera(
        name="Tamper Camera",
        owner_id=int(user.id),
        rtsp_url="rtsp://127.0.0.1:8554/tamper-stream",
        is_active=True,
    )
    db_session.add(camera)
    db_session.commit()
    db_session.refresh(camera)
    return camera


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


def test_vehicle_camera_recognize_signal_loss_keeps_contract(app, db_session, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)
    camera = _seed_camera(db_session)

    monkeypatch.setattr(vehicle_recognition, "ensure_manual_inference_allowed", lambda operation: None)
    monkeypatch.setattr(
        vehicle_recognition.StreamService,
        "get_camera_frame",
        staticmethod(lambda **kwargs: None),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/vehicle/recognize/camera/{camera.id}",
            json={"zone_id": 4, "gate_id": "gate-1", "direction": "out"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {
        "success",
        "status",
        "vehicle_detected",
        "plate_number",
        "plate_type",
        "confidence",
        "camera_id",
        "zone_id",
        "gate_id",
        "direction",
        "timestamp",
        "event_id",
        "access_log_id",
        "security_alert_ids",
        "snapshot_path",
        "security_tag",
        "priority",
        "decision",
        "decision_reason",
        "requires_manual_review",
        "alert_type",
        "tamper",
        "pipeline",
    }
    assert payload["success"] is True
    assert payload["status"] == "camera_tamper"
    assert payload["camera_id"] == int(camera.id)
    assert payload["zone_id"] == 4
    assert payload["gate_id"] == "gate-1"
    assert payload["direction"] == "OUT"
    assert payload["decision"] == "denied"
    assert payload["decision_reason"] == "signal_loss"
    assert payload["alert_type"] == "camera_tamper"
    assert payload["tamper"]["tamper_detected"] is True
    assert payload["tamper"]["tamper_type"] == "signal_loss"
    assert payload["tamper"]["reason"] == "no_frame_from_stream"
    assert isinstance(payload["security_alert_ids"], list)
    assert len(payload["security_alert_ids"]) == 1
    _assert_legacy_naive_isoformat(payload["timestamp"])

    rows = db_session.query(SecurityAlert).all()
    assert len(rows) == 1
    assert rows[0].type == "camera_tamper"


def test_vehicle_camera_recognize_tamper_result_keeps_contract(app, db_session, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)
    camera = _seed_camera(db_session)

    monkeypatch.setattr(vehicle_recognition, "ensure_manual_inference_allowed", lambda operation: None)
    monkeypatch.setattr(
        vehicle_recognition.StreamService,
        "get_camera_frame",
        staticmethod(lambda **kwargs: np.full((32, 32, 3), 180, dtype=np.uint8)),
    )
    monkeypatch.setattr(
        vehicle_recognition,
        "_tamper_detector",
        type(
            "TamperStub",
            (),
            {
                "detect": staticmethod(
                    lambda frame: TamperDetectionResult(
                        tamper_detected=True,
                        tamper_type="camera_covered",
                        severity="critical",
                        confidence=0.87,
                        metrics={
                            "brightness": 180.0,
                            "black_ratio": 0.0,
                            "std_dev": 0.0,
                            "edge_density": 0.0,
                        },
                        reason="low_texture_low_edges",
                    )
                )
            },
        )(),
    )
    monkeypatch.setattr(
        vehicle_recognition,
        "_save_tamper_snapshot",
        lambda frame, camera_id, tamper_type: "data/camera_tamper/fake_snapshot.jpg",
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/vehicle/recognize/camera/{camera.id}",
            json={"gate_id": "gate-2", "direction": "IN"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "camera_tamper"
    assert payload["camera_id"] == int(camera.id)
    assert payload["gate_id"] == "gate-2"
    assert payload["direction"] == "IN"
    assert payload["snapshot_path"] == "data/camera_tamper/fake_snapshot.jpg"
    assert payload["tamper"]["tamper_detected"] is True
    assert payload["tamper"]["tamper_type"] == "camera_covered"
    assert payload["tamper"]["confidence"] == 0.87
    assert payload["tamper"]["reason"] == "low_texture_low_edges"
    assert payload["tamper"]["metrics"]["brightness"] == 180.0
    assert payload["pipeline"]["detector"] == "tamper_guard"
    assert isinstance(payload["security_alert_ids"], list)
    assert len(payload["security_alert_ids"]) == 1
    _assert_legacy_naive_isoformat(payload["timestamp"])
