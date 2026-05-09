from __future__ import annotations

import inspect
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vms.backend.core.database import get_db
from vms.backend.models import Base, Camera, FaceDetection, FaceImage, Personnel, User
from vms.backend.routers import facial


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


def _make_personnel(**overrides) -> Personnel:
    data = {
        "nom": "Example",
        "prenom": "Alice",
        "full_name": "Alice Example",
        "cin": "CIN-ALICE-001",
        "num_recrutement": "REC-ALICE-001",
        "grade": "sergeant",
    }
    data.update(overrides)
    return Personnel(**data)


def _seed_user_and_camera(db_session) -> Camera:
    user = User(
        username="facial_contract_operator",
        hashed_password="not-used-in-test",
        role="operator",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    camera = Camera(
        name="Facial Camera",
        owner_id=int(user.id),
        rtsp_url="rtsp://127.0.0.1:8554/facial-stream",
        is_active=True,
    )
    db_session.add(camera)
    db_session.commit()
    db_session.refresh(camera)
    return camera


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


@pytest.fixture()
def app(db_session):
    app = FastAPI()
    app.include_router(facial.router)

    def override_get_db():
        yield db_session

    def override_current_user():
        return {"sub": "operator@example.com", "user_id": 17, "role": "operator"}

    def override_current_admin():
        return {"sub": "admin@example.com", "user_id": 1, "role": "admin"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[facial.get_current_user] = override_current_user
    app.dependency_overrides[facial.get_current_admin] = override_current_admin
    return app


def test_facial_known_faces_route_keeps_contract(app, db_session, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    person = _make_personnel()
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)

    created_at = datetime(2026, 5, 8, 9, 30, 0)
    face_image = FaceImage(
        personnel_id=int(person.id),
        image_path="data/faces/alice.jpg",
        pose_label="front",
        quality_score=0.91,
        is_reference=True,
        created_at=created_at,
    )
    db_session.add(face_image)
    db_session.commit()

    with TestClient(app) as client:
        response = client.get("/api/facial/known-faces?skip=0&limit=25")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"count", "faces", "message", "pipeline"}
    assert payload["count"] == 1
    assert payload["message"] == "Known faces retrieved successfully"
    assert payload["pipeline"] == "FaceRecognitionPipeline"
    assert payload["faces"] == [
        {
            "id": 1,
            "face_image_id": 1,
            "personnel_id": int(person.id),
            "name": "Alice Example",
            "path": "/media/faces/alice.jpg",
            "image_url": "/media/faces/alice.jpg",
            "pose_label": "front",
            "is_reference": True,
            "quality_score": 0.91,
            "created_at": created_at.isoformat(),
        }
    ]


def test_facial_detect_faces_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)
    monkeypatch.setattr(facial, "ensure_manual_inference_allowed", lambda operation: None)
    monkeypatch.setattr(facial.CameraService, "get_camera", staticmethod(lambda db, camera_id: {"id": camera_id}))
    monkeypatch.setattr(
        facial.CameraService,
        "resolve_camera_stream_source",
        staticmethod(lambda db, camera_id: f"rtsp://camera/{camera_id}"),
    )
    monkeypatch.setattr(
        facial.StreamService,
        "get_camera_thumbnail",
        staticmethod(lambda camera_id, rtsp_url=None: b"fake-camera-thumbnail"),
    )

    expected_faces = [
        {
            "detection_id": 41,
            "bbox": {"x": 10, "y": 12, "w": 40, "h": 40},
            "person_bbox": {"x": 5, "y": 5, "w": 100, "h": 180},
            "status": "matched",
            "personnel_id": 7,
            "personnel_name": "Alice Example",
            "confidence": 0.97,
            "match_quality": "high",
            "top_color": "navy",
            "bottom_color": "black",
            "backpack": "no",
            "hat": "yes",
            "detected_at": "2026-05-08T10:15:00+00:00",
        }
    ]

    class _FakeFacePipeline:
        def __init__(self, _db):
            pass

        def recognize_many_from_bytes(self, **kwargs):
            assert kwargs["camera_id"] == 7
            assert kwargs["persist"] is False
            assert kwargs["top_k"] == 6
            assert kwargs["image_bytes"] == b"fake-camera-thumbnail"
            return {"faces": expected_faces, "message": "1 face(s) processed"}

    monkeypatch.setattr(facial, "FaceRecognitionPipeline", _FakeFacePipeline)

    with TestClient(app) as client:
        response = client.get("/api/facial/detect-faces/7?confidence=0.61")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"camera_id", "detections_count", "detections", "timestamp", "message"}
    assert payload["camera_id"] == 7
    assert payload["detections_count"] == 1
    assert payload["message"] == "1 face(s) processed"
    assert payload["detections"] == [
        {
            "detection_id": 41,
            "bbox": {"x": 10, "y": 12, "w": 40, "h": 40},
            "person_bbox": {"x": 5, "y": 5, "w": 100, "h": 180},
            "is_known": True,
            "person_id": 7,
            "name": "Alice Example",
            "status": "matched",
            "confidence": 0.97,
            "match_quality": "high",
            "processing_time": 0.0,
            "top_color": "navy",
            "bottom_color": "black",
            "backpack": "no",
            "hat": "yes",
            "detected_at": "2026-05-08T10:15:00+00:00",
        }
    ]
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_facial_recognize_image_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)
    monkeypatch.setattr(facial, "ensure_manual_inference_allowed", lambda operation: None)

    expected_faces = [
        {
            "detection_id": 52,
            "bbox": {"x": 18, "y": 24, "w": 44, "h": 44},
            "person_bbox": None,
            "status": "unknown",
            "personnel_id": None,
            "label": "UNKNOWN",
            "confidence": 0.38,
            "match_quality": None,
            "top_color": "white",
            "bottom_color": "blue",
            "backpack": "unknown",
            "hat": "unknown",
            "detected_at": "2026-05-08T11:00:00+00:00",
        }
    ]

    class _FakeFacePipeline:
        def __init__(self, _db):
            pass

        def recognize_many_from_bytes(self, **kwargs):
            assert kwargs["camera_id"] == 0
            assert kwargs["persist"] is False
            assert kwargs["top_k"] == 8
            assert kwargs["image_bytes"] == b"fake-upload-image"
            return {"faces": expected_faces, "message": "1 face(s) processed"}

    monkeypatch.setattr(facial, "FaceRecognitionPipeline", _FakeFacePipeline)

    with TestClient(app) as client:
        response = client.post(
            "/api/facial/recognize-image?confidence=0.84",
            files={"file": ("face.jpg", b"fake-upload-image", "image/jpeg")},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"detections_count", "detections", "timestamp", "message"}
    assert payload["detections_count"] == 1
    assert payload["message"] == "1 face(s) processed"
    assert payload["detections"] == [
        {
            "detection_id": 52,
            "bbox": {"x": 18, "y": 24, "w": 44, "h": 44},
            "person_bbox": None,
            "is_known": False,
            "person_id": None,
            "name": "UNKNOWN",
            "status": "unknown",
            "confidence": 0.38,
            "match_quality": None,
            "processing_time": 0.0,
            "top_color": "white",
            "bottom_color": "blue",
            "backpack": "unknown",
            "hat": "unknown",
            "detected_at": "2026-05-08T11:00:00+00:00",
        }
    ]
    _assert_legacy_naive_isoformat(payload["timestamp"])


def test_facial_events_route_keeps_contract(app, db_session, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    person = _make_personnel(cin="CIN-ALICE-002", num_recrutement="REC-ALICE-002")
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)
    camera = _seed_user_and_camera(db_session)

    detected_at = datetime(2026, 5, 8, 12, 45, 0)
    row = FaceDetection(
        personnel_id=int(person.id),
        camera_id=int(camera.id),
        zone_id=None,
        face_encoding=[],
        confidence=0.93,
        match_quality="high",
        image_path="data/facial/events/detection_1.jpg",
        detected_at=detected_at,
    )
    db_session.add(row)
    db_session.commit()

    with TestClient(app) as client:
        response = client.get("/api/facial/events?skip=0&limit=25")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"count", "events", "message", "pipeline"}
    assert payload["count"] == 1
    assert payload["message"] == "Facial events retrieved successfully"
    assert payload["pipeline"] == "FaceRecognitionPipeline"
    assert payload["events"] == [
        {
            "id": 1,
            "detection_id": 1,
            "personnel_id": int(person.id),
            "name": "Alice Example",
            "status": "matched",
            "camera_id": int(camera.id),
            "zone_id": None,
            "confidence": 0.93,
            "match_quality": "high",
            "image_url": "/media/facial/events/detection_1.jpg",
            "detected_at": detected_at.isoformat(),
        }
    ]
