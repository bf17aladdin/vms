from __future__ import annotations

from datetime import datetime, timedelta
import inspect
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vms.backend.core.database import ensure_face_detection_appearance_schema, get_db
from vms.backend.core.security import create_access_token
from vms.backend.models import (
    Base,
    Camera,
    FaceDetection,
    Personnel,
    PersonnelCategoryEnum,
    User,
    VehicleDetection,
    VehicleEntry,
)
from vms.backend.routers.ai_services import router
from vms.backend.services import multi_cam_stream_hub as multi_cam_stream_hub_module
from vms.backend.services.multi_cam_stream_hub import (
    build_multi_cam_snapshot_diff,
    get_multi_cam_monitor_stream_hub,
    reset_multi_cam_monitor_stream_hub,
)
from vms.backend.services.person_appearance import build_appearance_embedding


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "multi_cam_monitor.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    ensure_face_detection_appearance_schema(engine)

    session = TestingSessionLocal()
    session.info["session_factory"] = TestingSessionLocal
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def reset_stream_hub(db_session):
    original_session_local = multi_cam_stream_hub_module.SessionLocal
    multi_cam_stream_hub_module.SessionLocal = db_session.info["session_factory"]
    reset_multi_cam_monitor_stream_hub()
    hub = get_multi_cam_monitor_stream_hub()
    hub._poll_interval_sec = 0.05
    try:
        yield
    finally:
        reset_multi_cam_monitor_stream_hub()
        multi_cam_stream_hub_module.SessionLocal = original_session_local


@pytest.fixture()
def app(db_session):
    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture()
def auth_token():
    return create_access_token(
        {
            "sub": "monitor@example.com",
            "username": "monitor",
            "user_id": 1,
            "role": "admin",
            "is_admin": True,
        }
    )


@pytest.fixture()
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


def _patch_testclient_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    if "app" in inspect.signature(httpx.Client.__init__).parameters:
        return

    original_init = httpx.Client.__init__

    def patched_init(self, *args, app=None, **kwargs):
        return original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)


@pytest.fixture()
def seeded_monitor_data(db_session):
    user = User(
        username="monitor",
        email="monitor@example.com",
        hashed_password="hashed",
        is_active=True,
        is_admin=True,
    )
    db_session.add(user)
    db_session.flush()

    camera_a = Camera(name="North Gate", owner_id=user.id, connection_status="online")
    camera_b = Camera(name="South Gate", owner_id=user.id, connection_status="online")
    db_session.add_all([camera_a, camera_b])
    db_session.flush()

    personnel = Personnel(
        nom="Monitor",
        prenom="Subject",
        full_name="Monitor Subject",
        cin="CIN-TRACK-001",
        num_recrutement="TRACK-001",
        categorie=PersonnelCategoryEnum.OFFICIER,
        grade="Captain",
        is_active=True,
    )
    db_session.add(personnel)
    db_session.flush()

    shared_embedding = build_appearance_embedding(
        top_color="red",
        bottom_color="black",
        has_backpack=True,
        has_hat=False,
    )
    alt_embedding = build_appearance_embedding(
        top_color="blue",
        bottom_color="gray",
        has_backpack=False,
        has_hat=False,
    )

    detections = [
        FaceDetection(
            personnel_id=personnel.id,
            camera_id=camera_a.id,
            face_encoding=[0.1] * 128,
            confidence=0.93,
            match_quality="high",
            appearance_top_color="red",
            appearance_bottom_color="black",
            has_backpack=True,
            has_hat=False,
            appearance_embedding=shared_embedding,
            detected_at=datetime.utcnow() - timedelta(minutes=4),
            is_authorized=True,
            notes="Primary sighting",
        ),
        FaceDetection(
            personnel_id=None,
            camera_id=camera_b.id,
            face_encoding=[0.2] * 128,
            confidence=0.61,
            match_quality="medium",
            appearance_top_color="red",
            appearance_bottom_color="black",
            has_backpack=True,
            has_hat=False,
            appearance_embedding=shared_embedding,
            detected_at=datetime.utcnow() - timedelta(minutes=2),
            is_authorized=None,
            notes="Cross camera match candidate",
        ),
        FaceDetection(
            personnel_id=None,
            camera_id=camera_b.id,
            face_encoding=[0.3] * 128,
            confidence=0.42,
            match_quality="low",
            appearance_top_color="blue",
            appearance_bottom_color="gray",
            has_backpack=False,
            has_hat=False,
            appearance_embedding=alt_embedding,
            detected_at=datetime.utcnow() - timedelta(minutes=1),
            is_authorized=None,
            notes="Unrelated track",
        ),
    ]
    db_session.add_all(detections)
    db_session.flush()

    vehicle_entry = VehicleEntry(
        license_plate="MC-100",
        vehicle_type="suv",
        brand="Toyota",
        model="RAV4",
        color="white",
        entry_camera_id=camera_a.id,
        entry_time=datetime.utcnow() - timedelta(minutes=6),
        entry_confidence=0.94,
        status="active",
    )
    db_session.add(vehicle_entry)
    db_session.flush()

    vehicle_detection = VehicleDetection(
        license_plate="MC-100",
        plate_confidence=0.94,
        vehicle_type="suv",
        color="white",
        vehicle_entry_id=vehicle_entry.id,
        camera_id=camera_b.id,
        detected_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db_session.add(vehicle_detection)
    db_session.commit()


@pytest.mark.anyio
async def test_multi_cam_snapshot_returns_cross_camera_person_track(
    app: FastAPI,
    auth_headers,
    seeded_monitor_data,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/ai/monitor/multi-cam", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["summary"]["active_person_tracks"] >= 2
    assert payload["summary"]["cross_camera_tracks"] >= 1

    lead_track = payload["persons"][0]
    assert set(lead_track["camera_ids"]) == {1, 2}
    assert lead_track["dominant_top_color"] == "red"
    assert lead_track["backpack"] == "yes"
    assert lead_track["cross_camera_matches"][0]["similarity"] > 0.95


@pytest.mark.anyio
async def test_multi_cam_snapshot_includes_vehicle_attributes(
    app: FastAPI,
    auth_headers,
    seeded_monitor_data,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/ai/monitor/multi-cam",
            params={"vehicle_limit": 5, "person_limit": 5},
            headers=auth_headers,
        )

    assert response.status_code == 200
    payload = response.json()
    vehicle = payload["vehicles"][0]
    assert vehicle["license_plate"] == "MC-100"
    assert vehicle["vehicle_type"] == "suv"
    assert vehicle["color"] == "white"
    assert vehicle["brand"] == "Toyota"
    assert vehicle["model"] == "RAV4"
    assert any(item["type"] == "vehicle_detection" for item in payload["timeline"])


@pytest.mark.anyio
async def test_multi_cam_snapshot_diff_reports_vehicle_upsert(
    app: FastAPI,
    auth_headers,
    db_session,
    seeded_monitor_data,
):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        before_response = await client.get(
            "/api/ai/monitor/multi-cam",
            params={"vehicle_limit": 5, "person_limit": 5, "force_refresh": True},
            headers=auth_headers,
        )

        vehicle_entry = VehicleEntry(
            license_plate="MC-200",
            vehicle_type="truck",
            brand="Ford",
            model="Ranger",
            color="blue",
            entry_camera_id=1,
            entry_time=datetime.utcnow() - timedelta(minutes=1),
            entry_confidence=0.91,
            status="active",
        )
        db_session.add(vehicle_entry)
        db_session.flush()
        db_session.add(
            VehicleDetection(
                license_plate="MC-200",
                plate_confidence=0.91,
                vehicle_type="truck",
                color="blue",
                vehicle_entry_id=vehicle_entry.id,
                camera_id=2,
                detected_at=datetime.utcnow(),
            )
        )
        db_session.commit()

        after_response = await client.get(
            "/api/ai/monitor/multi-cam",
            params={"vehicle_limit": 5, "person_limit": 5, "force_refresh": True},
            headers=auth_headers,
        )

    assert before_response.status_code == 200
    assert after_response.status_code == 200

    diff = build_multi_cam_snapshot_diff(before_response.json(), after_response.json())
    assert diff is not None
    assert diff["vehicles"]["remove"] == []
    assert any(vehicle["license_plate"] == "MC-200" for vehicle in diff["vehicles"]["upsert"])
    assert isinstance(diff["timeline"]["replace"], list)


def test_multi_cam_websocket_streams_vehicle_diff(
    app: FastAPI,
    auth_token,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    seeded_monitor_data,
):
    _patch_testclient_httpx(monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/ai/monitor/multi-cam/ws?vehicle_limit=5&person_limit=5&token={quote(auth_token, safe='')}"
        ) as websocket:
            snapshot_message = websocket.receive_json()
            assert snapshot_message["type"] == "multi_cam_snapshot"
            assert snapshot_message["data"]["stream_params"]["vehicle_limit"] == 5
            assert any(
                vehicle["license_plate"] == "MC-100"
                for vehicle in snapshot_message["data"]["vehicles"]
            )

            vehicle_entry = VehicleEntry(
                license_plate="MC-300",
                vehicle_type="sedan",
                brand="Honda",
                model="Accord",
                color="black",
                entry_camera_id=1,
                entry_time=datetime.utcnow() - timedelta(minutes=1),
                entry_confidence=0.9,
                status="active",
            )
            db_session.add(vehicle_entry)
            db_session.flush()
            db_session.add(
                VehicleDetection(
                    license_plate="MC-300",
                    plate_confidence=0.9,
                    vehicle_type="sedan",
                    color="black",
                    vehicle_entry_id=vehicle_entry.id,
                    camera_id=2,
                    detected_at=datetime.utcnow(),
                )
            )
            db_session.commit()

            diff_message = websocket.receive_json()
            assert diff_message["type"] == "multi_cam_diff"
            assert diff_message["data"]["stream_params"]["vehicle_limit"] == 5
            assert any(
                vehicle["license_plate"] == "MC-300"
                for vehicle in diff_message["data"]["vehicles"]["upsert"]
            )
