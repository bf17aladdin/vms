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
    SecurityAlert,
    User,
    VehicleAccessLog,
    VehicleEvent,
    VehicleEventFrame,
)
from vms.backend.routers import ai_services


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "vehicle_history_delete.sqlite"
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
    app.include_router(ai_services.router)

    def override_get_db():
        yield db_session

    def override_require_operator():
        return {"sub": "operator@example.com", "user_id": 1, "role": "operator", "is_admin": False}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[ai_services.require_operator] = override_require_operator
    return app


def test_delete_vehicle_history_cleans_related_rows(app, db_session, monkeypatch) -> None:
    _patch_testclient_httpx(monkeypatch)

    owner = User(
        username="vehicle-operator",
        email="vehicle-operator@example.com",
        hashed_password="hashed",
        is_active=True,
        role="operator",
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

    vehicle_event = VehicleEvent(
        camera_id=camera.id,
        timestamp=datetime.now(timezone.utc),
        plate_type="unknown",
        snapshot_path="data/tests/vehicle_delete.jpg",
    )
    db_session.add(vehicle_event)
    db_session.flush()

    db_session.add_all(
        [
            VehicleEventFrame(
                event_id=vehicle_event.id,
                frame_path="data/tests/vehicle_delete_frame.jpg",
                timestamp=datetime.now(timezone.utc),
                stage="full_frame",
            ),
            VehicleAccessLog(
                event_id=vehicle_event.id,
                camera_id=camera.id,
                timestamp=datetime.now(timezone.utc),
                direction="IN",
            ),
            SecurityAlert(
                type="unknown_plate",
                timestamp=datetime.now(timezone.utc),
                event_id=vehicle_event.id,
            ),
        ]
    )
    db_session.commit()

    with TestClient(app) as client:
        response = client.delete(f"/api/ai/vehicles/history/{vehicle_event.id}?delete_image=true")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert int(payload["deleted_id"]) == int(vehicle_event.id)
    assert int(payload["deleted_frames"]) == 1
    assert int(payload["detached_access_logs"]) == 1
    assert int(payload["detached_alerts"]) == 1

    db_session.expire_all()

    assert db_session.query(VehicleEvent).filter(VehicleEvent.id == vehicle_event.id).count() == 0
    assert db_session.query(VehicleEventFrame).filter(VehicleEventFrame.event_id == vehicle_event.id).count() == 0

    access_log = db_session.query(VehicleAccessLog).one()
    security_alert = db_session.query(SecurityAlert).one()

    assert access_log.event_id is None
    assert security_alert.event_id is None
