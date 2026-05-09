from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from vms.backend.core.database import ensure_face_detection_appearance_schema, get_db
from vms.backend.models import (
    Base,
    Camera,
    FaceDetection,
    Personnel,
    PersonnelCategoryEnum,
    User,
)
from vms.backend.routers.ai_services import router


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "person_appearance.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    ensure_face_detection_appearance_schema(engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def app(db_session):
    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture()
def seeded_history(db_session):
    user = User(
        username="tester",
        email="tester@example.com",
        hashed_password="hashed",
        is_active=True,
        is_admin=True,
    )
    db_session.add(user)
    db_session.flush()

    camera_one = Camera(
        name="Gate A",
        owner_id=user.id,
        is_active=True,
        connection_status="online",
    )
    camera_two = Camera(
        name="Gate B",
        owner_id=user.id,
        is_active=True,
        connection_status="online",
    )
    db_session.add_all([camera_one, camera_two])
    db_session.flush()

    alice = Personnel(
        nom="Alice",
        prenom="Example",
        full_name="Alice Example",
        cin="CIN-001",
        num_recrutement="REC-001",
        categorie=PersonnelCategoryEnum.OFFICIER,
        grade="Lieutenant",
        is_active=True,
        is_blacklisted=False,
    )
    db_session.add(alice)
    db_session.flush()

    detections = [
        FaceDetection(
            personnel_id=alice.id,
            camera_id=camera_one.id,
            face_encoding=[0.1] * 128,
            confidence=0.92,
            match_quality="high",
            face_bbox={"x": 10, "y": 10, "w": 30, "h": 30},
            person_bbox={"x": 0, "y": 25, "w": 80, "h": 140},
            appearance_top_color="red",
            appearance_bottom_color="black",
            has_backpack=True,
            has_hat=False,
            appearance_embedding=[0.9] * 34,
            detected_at=datetime.utcnow() - timedelta(minutes=5),
            is_authorized=True,
            notes="Matched Alice Example",
        ),
        FaceDetection(
            personnel_id=None,
            camera_id=camera_one.id,
            face_encoding=[0.2] * 128,
            confidence=0.31,
            match_quality="low",
            face_bbox={"x": 40, "y": 15, "w": 28, "h": 28},
            person_bbox={"x": 25, "y": 30, "w": 90, "h": 145},
            appearance_top_color="blue",
            appearance_bottom_color="gray",
            has_backpack=False,
            has_hat=None,
            appearance_embedding=[0.2] * 34,
            detected_at=datetime.utcnow() - timedelta(minutes=3),
            is_authorized=None,
            notes="Face not recognized",
        ),
        FaceDetection(
            personnel_id=None,
            camera_id=camera_two.id,
            face_encoding=[0.3] * 128,
            confidence=0.15,
            match_quality="low",
            face_bbox={"x": 60, "y": 18, "w": 26, "h": 26},
            person_bbox=None,
            appearance_top_color=None,
            appearance_bottom_color=None,
            has_backpack=None,
            has_hat=None,
            detected_at=datetime.utcnow() - timedelta(minutes=1),
            is_authorized=None,
            notes="No registered faces",
        ),
        FaceDetection(
            personnel_id=None,
            camera_id=camera_two.id,
            face_encoding=[0.4] * 128,
            confidence=0.55,
            match_quality="medium",
            face_bbox={"x": 22, "y": 20, "w": 30, "h": 30},
            person_bbox={"x": 5, "y": 32, "w": 82, "h": 138},
            appearance_top_color="red",
            appearance_bottom_color="black",
            has_backpack=True,
            has_hat=False,
            appearance_embedding=[0.9] * 34,
            detected_at=datetime.utcnow() - timedelta(minutes=2),
            is_authorized=None,
            notes="Appearance match candidate",
        ),
    ]
    db_session.add_all(detections)
    db_session.commit()
    return {
        "camera_one": camera_one.id,
        "camera_two": camera_two.id,
        "source_detection": detections[0].id,
        "similar_detection": detections[3].id,
    }


def test_face_detection_migration_adds_person_appearance_columns(tmp_path: Path):
    db_path = tmp_path / "legacy_face_detection.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE face_detections (
                    id INTEGER PRIMARY KEY,
                    personnel_id INTEGER,
                    camera_id INTEGER NOT NULL,
                    zone_id INTEGER,
                    face_encoding JSON NOT NULL,
                    confidence FLOAT,
                    match_quality VARCHAR(20),
                    image_path VARCHAR(255),
                    thumbnail_path VARCHAR(255),
                    face_bbox JSON,
                    detected_at DATETIME NOT NULL,
                    created_at DATETIME,
                    is_authorized BOOLEAN,
                    is_blacklisted BOOLEAN,
                    latitude FLOAT,
                    longitude FLOAT,
                    notes TEXT
                )
                """
            )
        )

    ensure_face_detection_appearance_schema(engine)

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("face_detections")}
    indexes = {index["name"] for index in inspector.get_indexes("face_detections")}

    assert {
        "person_bbox",
        "appearance_top_color",
        "appearance_bottom_color",
        "has_backpack",
        "has_hat",
        "appearance_embedding",
    }.issubset(columns)
    assert "ix_face_detections_appearance_top_color" in indexes
    assert "ix_face_detections_has_backpack" in indexes


@pytest.mark.anyio
async def test_facial_history_filters_by_person_appearance(app: FastAPI, seeded_history):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/ai/facial/history",
            params={
                "camera_id": seeded_history["camera_one"],
                "top_color": "red",
                "backpack": "yes",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    detection = payload["detections"][0]
    assert detection["personnel_name"] == "Alice Example"
    assert detection["top_color"] == "red"
    assert detection["backpack"] == "yes"


@pytest.mark.anyio
async def test_facial_history_supports_unknown_filters(app: FastAPI, seeded_history):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/ai/facial/history",
            params={
                "camera_id": seeded_history["camera_two"],
                "top_color": "unknown",
                "hat": "unknown",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    detection = payload["detections"][0]
    assert detection["camera_id"] == seeded_history["camera_two"]
    assert detection["top_color"] == "unknown"
    assert detection["hat"] == "unknown"


@pytest.mark.anyio
async def test_facial_history_rejects_invalid_color_filter(app: FastAPI, seeded_history):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/ai/facial/history",
            params={"top_color": "ultraviolet"},
        )

    assert response.status_code == 422
    assert "Invalid color" in response.json()["detail"]


@pytest.mark.anyio
async def test_facial_history_rejects_invalid_accessory_filter(app: FastAPI, seeded_history):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/ai/facial/history",
            params={"backpack": "maybe"},
        )

    assert response.status_code == 422
    assert "Invalid accessory state" in response.json()["detail"]


@pytest.mark.anyio
async def test_facial_statistics_include_appearance_breakdown(app: FastAPI, seeded_history):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/ai/facial/statistics")

    assert response.status_code == 200
    payload = response.json()
    stats = payload["statistics"]
    assert stats["total_detections"] == 4
    assert stats["recognized"] == 1
    assert stats["backpack_detected"] == 2
    assert stats["appearance_top_colors"]["red"] == 2


@pytest.mark.anyio
async def test_facial_similarity_returns_best_cross_camera_match(
    app: FastAPI,
    seeded_history,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/ai/facial/similar/{seeded_history['source_detection']}",
            params={"cross_camera_only": "true", "limit": 5},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"]["id"] == seeded_history["source_detection"]
    assert payload["matches"][0]["id"] == seeded_history["similar_detection"]
    assert payload["matches"][0]["same_camera"] is False
    assert payload["matches"][0]["similarity"] > 0.9
