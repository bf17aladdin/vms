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
from vms.backend.routers import ai_services


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
    app.include_router(ai_services.router)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app


def test_face_recognize_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)
    monkeypatch.setattr(ai_services, "ensure_manual_inference_allowed", lambda operation: None)

    expected_payload = {
        "success": True,
        "status": "processed",
        "camera_id": 9,
        "zone_id": 2,
        "faces_count": 1,
        "matched_count": 1,
        "unknown_count": 0,
        "error_count": 0,
        "faces": [{"personnel_id": 4, "full_name": "Awa Diallo"}],
        "message": "1 face(s) processed",
        "performance": {"detection_time_ms": 12.4, "total_time_ms": 18.9},
        "pipeline": {
            "detector_backend": "insightface",
            "embedder_backend": "arcface_onnx",
            "matcher": "cosine_numpy",
        },
    }

    class _FakeFacePipeline:
        def __init__(self, _db):
            pass

        def recognize_from_bytes(self, **kwargs):
            assert kwargs["camera_id"] == 9
            assert kwargs["zone_id"] == 2
            assert kwargs["persist"] is False
            assert kwargs["top_k"] == 3
            assert kwargs["image_bytes"] == b"fake-face-image"
            return expected_payload

    monkeypatch.setattr(ai_services, "FaceRecognitionPipeline", _FakeFacePipeline)

    with TestClient(app) as client:
        response = client.post(
            "/api/ai/face/recognize",
            data={
                "camera_id": "9",
                "zone_id": "2",
                "image_base64": "ZmFrZS1mYWNlLWltYWdl",
                "top_k": "3",
                "persist": "false",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == expected_payload


def test_face_history_alias_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    history_rows = [
        {
            "id": 51,
            "camera_id": 7,
            "personnel_name": "Alice Example",
            "top_color": "red",
            "backpack": "yes",
        }
    ]

    class _FakeFacePipeline:
        def __init__(self, _db):
            pass

        def get_history(self, **kwargs):
            assert kwargs["camera_id"] == 7
            assert kwargs["limit"] == 25
            return history_rows

    monkeypatch.setattr(ai_services, "FaceRecognitionPipeline", _FakeFacePipeline)

    with TestClient(app) as client:
        response = client.get("/api/ai/face/history?camera_id=7&limit=25&top_color=red&backpack=yes")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"success", "count", "detections"}
    assert payload["success"] is True
    assert payload["count"] == 1
    assert payload["detections"] == history_rows


def test_facial_statistics_route_keeps_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    stats_payload = {
        "total_detections": 14,
        "recognized": 9,
        "unknown": 5,
        "recognition_rate": 64.29,
        "pipeline": {
            "detector_backend": "insightface",
            "embedder_backend": "arcface_onnx",
            "matcher": "pgvector_cosine",
        },
    }

    class _FakeFacePipeline:
        def __init__(self, _db):
            pass

        def get_statistics(self):
            return stats_payload

    monkeypatch.setattr(ai_services, "FaceRecognitionPipeline", _FakeFacePipeline)

    with TestClient(app) as client:
        response = client.get("/api/ai/facial/statistics")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload.keys()) == {"success", "statistics"}
    assert payload["success"] is True
    assert payload["statistics"] == stats_payload


def test_facial_similar_not_found_contract(app, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    class _FakeFacePipeline:
        def __init__(self, _db):
            pass

        def find_similar_detections(self, **kwargs):
            assert kwargs["detection_id"] == 404
            raise ValueError("Face detection #404 not found")

    monkeypatch.setattr(ai_services, "FaceRecognitionPipeline", _FakeFacePipeline)

    with TestClient(app) as client:
        response = client.get("/api/ai/facial/similar/404?cross_camera_only=true&limit=5")

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Face detection #404 not found"}
