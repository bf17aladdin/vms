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
from vms.backend.models import (
    Base,
    Camera,
    UnknownDetection,
    User,
    VehicleAccessLog,
    VehicleEntry,
    VehicleRegistry,
)
from vms.backend.routers.vehicle_registry import router


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "vehicle_registry_delete.sqlite"
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

    app.dependency_overrides[get_db] = override_get_db
    return app


def test_delete_vehicle_registry_detaches_history_and_deletes_photo(app, db_session, monkeypatch, tmp_path: Path) -> None:
    _patch_testclient_httpx(monkeypatch)

    owner = User(
        username="vehicle-owner",
        email="vehicle-owner@example.com",
        hashed_password="hashed",
        is_active=True,
        role="operator",
    )
    db_session.add(owner)
    db_session.flush()

    camera = Camera(
        name="South Gate",
        owner_id=owner.id,
        connection_status="online",
        is_active=True,
    )
    db_session.add(camera)
    db_session.flush()

    photo_path = tmp_path / "vehicle_registry_photo.jpg"
    photo_path.write_bytes(b"vehicle-photo")

    registry = VehicleRegistry(
        matricule="123 TUNIS 4567",
        marque="Toyota",
        modele="Hilux",
        categorie="civil",
        statut="actif",
        photo_path=str(photo_path),
    )
    db_session.add(registry)
    db_session.flush()

    vehicle_entry = VehicleEntry(
        vehicle_registry_id=registry.id,
        license_plate=registry.matricule,
        entry_camera_id=camera.id,
        entry_time=datetime.now(timezone.utc),
        entry_confidence=0.97,
        status="active",
    )
    access_log = VehicleAccessLog(
        registry_vehicle_id=registry.id,
        camera_id=camera.id,
        timestamp=datetime.now(timezone.utc),
        direction="IN",
    )
    unknown = UnknownDetection(
        detection_type="vehicle",
        image_path="data/tests/unknown_vehicle.jpg",
        camera_id=camera.id,
        confidence=0.81,
        is_resolved=True,
        resolved_entity_type="vehicle_registry",
        resolved_entity_id=registry.id,
        resolved_label=registry.matricule,
    )
    db_session.add_all([vehicle_entry, access_log, unknown])
    db_session.commit()

    with TestClient(app) as client:
        response = client.delete(f"/api/vehicle-registry/{registry.id}")

    assert response.status_code == 204, response.text

    db_session.expire_all()

    assert db_session.query(VehicleRegistry).filter(VehicleRegistry.id == registry.id).count() == 0

    preserved_entry = db_session.query(VehicleEntry).one()
    preserved_access_log = db_session.query(VehicleAccessLog).one()
    preserved_unknown = db_session.query(UnknownDetection).one()

    assert preserved_entry.vehicle_registry_id is None
    assert preserved_access_log.registry_vehicle_id is None
    assert preserved_unknown.resolved_entity_type == "vehicle_registry"
    assert preserved_unknown.resolved_entity_id is None
    assert photo_path.exists() is False
