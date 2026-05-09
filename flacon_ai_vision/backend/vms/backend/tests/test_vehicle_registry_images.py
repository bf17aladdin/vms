from __future__ import annotations

import inspect
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from vms.backend.core.config import settings
from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_user
from vms.backend.models import Base, User, VehicleRegistry, VehicleRegistryImage
from vms.backend.routers.vehicle_registry import router


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "vehicle_registry_images.sqlite"
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
def app(db_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    app = FastAPI()
    app.include_router(router)

    storage_path = tmp_path / "storage"
    storage_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STORAGE_PATH", str(storage_path))

    def override_get_db():
        yield db_session

    def override_current_user():
        return {"user_id": 1, "sub": "test-user"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    return app


def test_vehicle_registry_images_follow_personnel_like_dataset_flow(
    app,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_testclient_httpx(monkeypatch)

    owner = User(
        username="vehicle-images-owner",
        email="vehicle-images-owner@example.com",
        hashed_password="hashed",
        is_active=True,
        role="operator",
    )
    db_session.add(owner)
    db_session.flush()

    legacy_photo_path = tmp_path / "legacy_vehicle_reference.jpg"
    legacy_photo_path.write_bytes(b"legacy-photo")

    registry = VehicleRegistry(
        matricule="123 TUNIS 4567",
        marque="Toyota",
        modele="Hilux",
        categorie="civil",
        statut="actif",
        photo_path=str(legacy_photo_path),
    )
    db_session.add(registry)
    db_session.commit()

    with TestClient(app) as client:
        list_response = client.get(f"/api/vehicle-registry/{registry.id}/images")
        assert list_response.status_code == 200, list_response.text

        list_payload = list_response.json()
        assert list_payload["count"] == 1
        assert list_payload["items"][0]["image_path"] == str(legacy_photo_path)
        assert list_payload["items"][0]["is_reference"] is True

        create_response = client.post(
            f"/api/vehicle-registry/{registry.id}/images",
            data={"view_label": "rear", "make_primary": "false"},
            files={"file": ("rear_view.jpg", b"rear-view", "image/jpeg")},
        )
        assert create_response.status_code == 201, create_response.text

        created_payload = create_response.json()
        created_image_id = int(created_payload["image"]["id"])
        created_image_path = str(created_payload["image"]["image_path"])
        created_image_url = str(created_payload["image"]["image_url"])
        assert created_payload["image"]["view_label"] == "rear"
        assert created_payload["image"]["is_reference"] is False
        assert created_image_url.startswith("/media-storage/uploads/vehicle_photos/")
        assert Path(created_image_path).exists() is True

        primary_response = client.patch(f"/api/vehicle-registry/{registry.id}/images/{created_image_id}/primary")
        assert primary_response.status_code == 200, primary_response.text

        db_session.expire_all()
        refreshed_registry = db_session.query(VehicleRegistry).filter(VehicleRegistry.id == registry.id).one()
        assert refreshed_registry.photo_path == created_image_path

        delete_response = client.delete(f"/api/vehicle-registry/{registry.id}/images/{created_image_id}")
        assert delete_response.status_code == 200, delete_response.text
        assert delete_response.json()["deleted_file"] is True

    db_session.expire_all()

    refreshed_registry = db_session.query(VehicleRegistry).filter(VehicleRegistry.id == registry.id).one()
    assert refreshed_registry.photo_path == str(legacy_photo_path)

    remaining_images = (
        db_session.query(VehicleRegistryImage)
        .filter(VehicleRegistryImage.vehicle_registry_id == registry.id)
        .order_by(VehicleRegistryImage.id.asc())
        .all()
    )
    assert len(remaining_images) == 1
    assert remaining_images[0].image_path == str(legacy_photo_path)
    assert remaining_images[0].is_reference is True
    assert Path(created_image_path).exists() is False
