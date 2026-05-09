from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vms.backend.models import Alert, Base, Camera, SecurityAlert, User, Zone
from vms.backend.services.vehicle_service import VehicleService


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


def _seed_camera(db_session) -> Camera:
    user = User(
        username="legacy_vehicle_admin",
        hashed_password="not-used-in-test",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    camera = Camera(
        name="Gate Camera",
        owner_id=int(user.id),
        rtsp_url="rtsp://127.0.0.1:8554/test-stream",
        is_active=True,
    )
    db_session.add(camera)
    db_session.commit()
    db_session.refresh(camera)
    return camera


def test_create_alert_zone_persists_and_reuses_existing_zone(db_session) -> None:
    camera = _seed_camera(db_session)

    created = VehicleService.create_alert_zone(db_session, int(camera.id), "Vehicle Gate")
    existing = VehicleService.create_alert_zone(db_session, int(camera.id), "Vehicle Gate")

    zones = db_session.query(Zone).filter(Zone.camera_id == int(camera.id)).all()

    assert created["existing"] is False
    assert existing["existing"] is True
    assert len(zones) == 1
    assert zones[0].name == "Vehicle Gate"


def test_get_alerts_merges_security_and_legacy_vehicle_alerts(db_session) -> None:
    camera = _seed_camera(db_session)
    older = datetime.now(timezone.utc) - timedelta(minutes=10)
    newer = datetime.now(timezone.utc)

    db_session.add(
        Alert(
            camera_id=int(camera.id),
            rule_type="vehicle",
            title="Legacy vehicle alert",
            message="Legacy alert payload",
            severity="warning",
            timestamp=older,
            is_acknowledged=False,
            is_resolved=False,
        )
    )
    db_session.add(
        SecurityAlert(
            type="unknown_plate",
            camera_id=int(camera.id),
            timestamp=newer,
            severity_level="high",
            resolution_status="open",
            message="Unknown plate at gate",
        )
    )
    db_session.commit()

    alerts = VehicleService.get_alerts(db_session, skip=0, limit=10)

    assert len(alerts) == 2
    assert alerts[0]["source"] == "security_alert"
    assert alerts[0]["type"] == "unknown_plate"
    assert alerts[1]["source"] == "alert"
    assert alerts[1]["type"] == "vehicle"


def test_detect_vehicles_in_stream_uses_pipeline_and_serializes_result(db_session, monkeypatch) -> None:
    camera = _seed_camera(db_session)

    class _FakePipeline:
        last_detector_conf = None
        last_stage_conf = None

        def __init__(self, _db):
            self.detector = type("Detector", (), {"min_conf": 0.25})()
            self.detection_module = type("DetectionModule", (), {"min_vehicle_conf": 0.30})()

        def recognize_from_frame(self, **kwargs):
            _FakePipeline.last_detector_conf = self.detector.min_conf
            _FakePipeline.last_stage_conf = self.detection_module.min_vehicle_conf
            assert kwargs["camera_id"] == int(camera.id)
            assert kwargs["persist"] is False
            assert kwargs["save_snapshot"] is False
            return {
                "success": True,
                "vehicle_detected": True,
                "plate_number": "123 TUNIS 4567",
                "plate_type": "civil",
                "confidence": 0.91,
                "dominant_color": "white",
                "decision": "allowed",
                "decision_reason": "registry_match",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "vehicle_profile": {
                    "vehicle_type": "passenger",
                    "body_style": "sedan_coupe",
                    "brand": "Toyota",
                    "model": "Corolla",
                },
                "vehicle_bbox": {"x": 1, "y": 2, "w": 100, "h": 50},
                "plate_bbox": {"x": 10, "y": 15, "w": 40, "h": 12},
                "pipeline": {"detector": "fake"},
            }

    monkeypatch.setattr(
        "vms.backend.services.stream_service.StreamService.get_camera_frame",
        lambda **_: np.zeros((64, 64, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(
        "vms.backend.services.vehicle_ai.vehicle_pipeline.VehicleRecognitionPipeline",
        _FakePipeline,
    )

    detections = VehicleService.detect_vehicles_in_stream(
        db_session,
        int(camera.id),
        confidence_threshold=0.77,
    )

    assert len(detections) == 1
    assert detections[0]["plate_number"] == "123 TUNIS 4567"
    assert detections[0]["vehicle_type"] == "passenger"
    assert detections[0]["brand"] == "Toyota"
    assert detections[0]["pipeline"] == {"detector": "fake"}
    assert _FakePipeline.last_detector_conf == pytest.approx(0.77)
    assert _FakePipeline.last_stage_conf == pytest.approx(0.77)
