from __future__ import annotations

from datetime import datetime, timezone
import inspect
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_user
from vms.backend.models import (
    Base,
    Camera,
    FaceDetection,
    FaceEncoding,
    FaceImage,
    Personnel,
    PersonnelCategoryEnum,
    PersonnelEvent,
    User,
    Zone,
    ZoneOccupancy,
)
from vms.backend.routers.personnel import router


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "personnel_delete.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
    app.include_router(router)

    def override_get_db():
        yield db_session

    def override_get_current_user():
        return {"sub": "tester@example.com", "user_id": 1, "is_admin": True}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return app


def test_delete_personnel_cleans_related_rows_and_returns_204(app, db_session, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    owner = User(
        username="personnel-owner",
        email="personnel-owner@example.com",
        hashed_password="hashed",
        is_active=True,
        is_admin=True,
    )
    db_session.add(owner)
    db_session.flush()

    camera = Camera(
        name="North Gate",
        owner_id=owner.id,
        connection_status="online",
        is_active=True,
    )
    db_session.add(camera)
    db_session.flush()

    zone = Zone(
        camera_id=camera.id,
        name="Restricted Zone",
        description="Delete personnel regression coverage",
        is_active=True,
    )
    db_session.add(zone)
    db_session.flush()

    personnel = Personnel(
        nom="Delete",
        prenom="Target",
        full_name="Target Delete",
        cin="CIN-DELETE-001",
        num_recrutement="REC-DELETE-001",
        categorie=PersonnelCategoryEnum.SOLDAT,
        grade="Soldat",
        is_active=True,
    )
    db_session.add(personnel)
    db_session.flush()

    face_image = FaceImage(
        personnel_id=personnel.id,
        image_path="data/known_faces/personnel_delete_001.jpg",
    )
    db_session.add(face_image)
    db_session.flush()

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            FaceEncoding(
                personnel_id=personnel.id,
                face_image_id=face_image.id,
                encoding_vector=[0.1, 0.2, 0.3],
                is_primary=True,
                is_active=True,
            ),
            FaceDetection(
                personnel_id=personnel.id,
                camera_id=camera.id,
                face_encoding=[0.3, 0.4, 0.5],
                detected_at=now,
                confidence=0.98,
            ),
            ZoneOccupancy(
                zone_id=zone.id,
                personnel_id=personnel.id,
                entry_time=now,
                is_active=True,
            ),
            PersonnelEvent(
                personnel_id=personnel.id,
                camera_id=camera.id,
                direction="entree",
                confidence=0.98,
                detected_at=now,
            ),
        ]
    )
    db_session.commit()

    with TestClient(app) as client:
        response = client.delete(f"/api/personnel/{personnel.id}")

    assert response.status_code == 204, response.text

    db_session.expire_all()

    assert db_session.query(Personnel).filter(Personnel.id == personnel.id).count() == 0
    assert db_session.query(FaceImage).filter(FaceImage.personnel_id == personnel.id).count() == 0
    assert db_session.query(FaceEncoding).filter(FaceEncoding.personnel_id == personnel.id).count() == 0
    assert db_session.query(PersonnelEvent).filter(PersonnelEvent.personnel_id == personnel.id).count() == 0

    detection = db_session.query(FaceDetection).one()
    occupancy = db_session.query(ZoneOccupancy).one()

    assert detection.personnel_id is None
    assert occupancy.personnel_id is None
    assert occupancy.is_active is False
    assert occupancy.exit_time is not None
