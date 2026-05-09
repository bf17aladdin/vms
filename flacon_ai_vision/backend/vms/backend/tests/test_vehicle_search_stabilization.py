from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

import vms.backend.core.audit as audit_module
import vms.backend.core.database as database_module
from vms.backend.main import app
from vms.backend.models import Base, Camera, User, VehicleEvent, VehicleEventFrame, VehicleRegistry
from vms.backend.routers import gallery as gallery_router
from vms.backend.routers import vehicle_recognition as vehicle_recognition_router


def _fake_user() -> dict[str, object]:
    return {"sub": "pytest_admin", "user_id": 1, "role": "admin"}


def _make_sqlite_engine(db_path: Path):
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )


def _override_get_db(session_factory):
    def _dependency():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    return _dependency


def _seed_vehicle_search_dataset(session_factory) -> dict[str, int]:
    with session_factory() as db:
        owner = User(
            username="vehicle_search_owner",
            hashed_password="not-used-in-tests",
            full_name="Vehicle Search Owner",
            role="admin",
            is_admin=True,
            is_active=True,
        )
        db.add(owner)
        db.flush()

        camera_1 = Camera(
            name="North Gate",
            owner_id=int(owner.id),
            camera_type="vehicle",
            is_active=True,
            is_enabled=True,
            connection_status="connected",
        )
        camera_2 = Camera(
            name="South Gate",
            owner_id=int(owner.id),
            camera_type="vehicle",
            is_active=True,
            is_enabled=True,
            connection_status="connected",
        )
        db.add_all([camera_1, camera_2])
        db.flush()

        registry_row = VehicleRegistry(
            matricule="AA 123 BB",
            marque="Toyota",
            modele="RAV4",
            couleur="white",
            categorie="civil",
            statut="actif",
        )
        db.add(registry_row)

        db.add_all(
            [
                VehicleEvent(
                    plate_number="AA 123 BB",
                    plate_type="civil",
                    confidence=0.96,
                    vehicle_detected=True,
                    vehicle_type="car",
                    body_style="suv_crossover",
                    dominant_color="white",
                    brand="Toyota",
                    model="RAV4",
                    vehicle_confidence=0.91,
                    plate_confidence=0.94,
                    normalized_plate="AA123BB",
                    camera_id=int(camera_1.id),
                    timestamp=datetime(2026, 3, 1, 10, 0, 0),
                    snapshot_path="data/tests/vehicle_a_1.jpg",
                    pipeline_meta={
                        "vehicle_profile": {
                            "dominant_color": "white",
                            "brand": "Toyota",
                            "model": "RAV4",
                            "body_style": "suv_crossover",
                        }
                    },
                ),
                VehicleEvent(
                    plate_number="AA 123 BB",
                    plate_type="civil",
                    confidence=0.93,
                    vehicle_detected=True,
                    vehicle_type="car",
                    body_style="suv_crossover",
                    dominant_color="white",
                    brand="Toyota",
                    model="RAV4",
                    vehicle_confidence=0.89,
                    plate_confidence=0.92,
                    normalized_plate="AA123BB",
                    camera_id=int(camera_2.id),
                    timestamp=datetime(2026, 3, 1, 16, 30, 0),
                    snapshot_path="data/tests/vehicle_a_2.jpg",
                ),
                VehicleEvent(
                    plate_number="MIL 001",
                    plate_type="military",
                    confidence=0.82,
                    vehicle_detected=True,
                    vehicle_type=None,
                    body_style=None,
                    dominant_color=None,
                    brand=None,
                    model=None,
                    vehicle_confidence=0.78,
                    plate_confidence=0.81,
                    normalized_plate="MIL001",
                    camera_id=int(camera_1.id),
                    timestamp=datetime(2026, 3, 2, 9, 15, 0),
                    snapshot_path="data/tests/vehicle_b_1.jpg",
                ),
                VehicleEvent(
                    plate_number="BUS 777",
                    plate_type="civil",
                    confidence=0.88,
                    vehicle_detected=True,
                    vehicle_type="bus",
                    body_style="bus",
                    dominant_color="maroon",
                    brand="Mercedes-Benz",
                    model="Sprinter",
                    vehicle_confidence=0.85,
                    plate_confidence=0.86,
                    normalized_plate="BUS777",
                    camera_id=int(camera_2.id),
                    timestamp=datetime(2026, 3, 3, 14, 0, 0),
                    snapshot_path="data/tests/vehicle_c_1.jpg",
                ),
            ]
        )
        db.commit()

        return {
            "camera_1": int(camera_1.id),
            "camera_2": int(camera_2.id),
        }


@pytest.fixture()
def vehicle_search_app_env(tmp_path, monkeypatch):
    engine = _make_sqlite_engine(tmp_path / "vehicle_search_api.db")
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(audit_module, "SessionLocal", session_factory)

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[gallery_router.get_db] = _override_get_db(session_factory)
    app.dependency_overrides[vehicle_recognition_router.get_db] = _override_get_db(session_factory)
    app.dependency_overrides[gallery_router.require_viewer] = _fake_user
    app.dependency_overrides[vehicle_recognition_router.get_current_user] = _fake_user

    try:
        yield {
            "engine": engine,
            "session_factory": session_factory,
        }
    finally:
        app.dependency_overrides = previous_overrides
        engine.dispose()


def test_vehicle_history_filters_use_canonical_aliases(vehicle_search_app_env) -> None:
    ids = _seed_vehicle_search_dataset(vehicle_search_app_env["session_factory"])

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/vehicle/history",
                params={
                    "camera_id": ids["camera_2"],
                    "color": "blanc",
                    "brand": "toyota",
                    "body_style": "SUV",
                    "vehicle_type": "passenger",
                },
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["count"] == 1
        assert payload["events"][0]["plate_number"] == "AA 123 BB"
        assert payload["events"][0]["camera_id"] == ids["camera_2"]
        assert payload["events"][0]["dominant_color"] == "white"
        assert payload["events"][0]["body_style"] == "suv_crossover"
        assert payload["events"][0]["vehicle_type"] == "car"

    asyncio.run(_run())


def test_vehicle_history_unknown_and_invalid_color_filters(vehicle_search_app_env) -> None:
    _seed_vehicle_search_dataset(vehicle_search_app_env["session_factory"])

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            unknown_response = await client.get("/api/vehicle/history", params={"color": "unknown"})
            assert unknown_response.status_code == 200, unknown_response.text
            unknown_payload = unknown_response.json()
            assert unknown_payload["count"] == 1
            assert unknown_payload["events"][0]["plate_number"] == "MIL 001"

            invalid_response = await client.get("/api/vehicle/history", params={"color": "pink"})
            assert invalid_response.status_code == 422
            assert "Unsupported color" in invalid_response.json()["detail"]

    asyncio.run(_run())


def test_gallery_vehicle_filters_group_results_and_support_unknown(vehicle_search_app_env) -> None:
    ids = _seed_vehicle_search_dataset(vehicle_search_app_env["session_factory"])

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/gallery/vehicles",
                params={
                    "brand": "toyota",
                    "color": "white",
                    "body_style": "suv",
                    "vehicle_type": "car",
                    "date_from": "2026-03-01",
                    "date_to": "2026-03-01",
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["total"] == 1
            assert payload["count"] == 1
            item = payload["items"][0]
            assert item["plate"] == "AA 123 BB"
            assert item["brand"] == "Toyota"
            assert item["color"] == "white"
            assert item["body_style"] == "suv_crossover"
            assert item["vehicle_type"] == "car"
            assert item["camera_count"] == 2
            assert item["cameras_seen"] == [ids["camera_1"], ids["camera_2"]]

            unknown_response = await client.get(
                "/api/gallery/vehicles",
                params={"body_style": "unknown"},
            )
            assert unknown_response.status_code == 200, unknown_response.text
            unknown_payload = unknown_response.json()
            assert unknown_payload["count"] == 1
            assert unknown_payload["items"][0]["plate_key"] == "MIL001"

    asyncio.run(_run())


def test_gallery_vehicle_includes_entries_without_snapshot_when_deletable(vehicle_search_app_env) -> None:
    ids = _seed_vehicle_search_dataset(vehicle_search_app_env["session_factory"])

    with vehicle_search_app_env["session_factory"]() as db:
        with_frame = VehicleEvent(
            plate_number="SIM-01-013414",
            plate_type="civil",
            confidence=0.92,
            vehicle_detected=True,
            vehicle_type="car",
            body_style="sedan_coupe",
            dominant_color=None,
            brand=None,
            model=None,
            vehicle_confidence=0.90,
            plate_confidence=0.91,
            normalized_plate="SIM01013414",
            camera_id=ids["camera_1"],
            timestamp=datetime(2026, 3, 1, 6, 6, 40),
            snapshot_path=None,
        )
        without_media = VehicleEvent(
            plate_number="SIM-01-013413",
            plate_type="civil",
            confidence=0.92,
            vehicle_detected=True,
            vehicle_type="car",
            body_style="sedan_coupe",
            dominant_color=None,
            brand=None,
            model=None,
            vehicle_confidence=0.90,
            plate_confidence=0.91,
            normalized_plate="SIM01013413",
            camera_id=ids["camera_1"],
            timestamp=datetime(2026, 3, 1, 6, 6, 39),
            snapshot_path=None,
        )
        db.add_all([with_frame, without_media])
        db.flush()
        db.add(
            VehicleEventFrame(
                event_id=int(with_frame.id),
                frame_path="data/tests/sim_vehicle_frame.jpg",
                timestamp=datetime(2026, 3, 1, 6, 6, 40),
                stage="full_frame",
            )
        )
        db.commit()

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(
                "/api/gallery/vehicles",
                params={
                    "q": "SIM-01-0134",
                    "date_from": "2026-03-01",
                    "date_to": "2026-03-01",
                },
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["count"] == 2
        items = {item["plate_key"]: item for item in payload["items"]}

        with_frame_item = items["SIM01013414"]
        assert with_frame_item["photo_url"] == "/media/tests/sim_vehicle_frame.jpg"
        assert len(with_frame_item["recent_photos"]) == 1
        assert with_frame_item["recent_photos"][0]["event_id"] == int(with_frame.id)
        assert with_frame_item["recent_photos"][0]["image_url"] == "/media/tests/sim_vehicle_frame.jpg"

        without_media_item = items["SIM01013413"]
        assert without_media_item["photo_url"] is None
        assert len(without_media_item["recent_photos"]) == 1
        assert without_media_item["recent_photos"][0]["event_id"] == int(without_media.id)
        assert without_media_item["recent_photos"][0]["image_url"] is None

    asyncio.run(_run())


def test_gallery_vehicle_validation_errors_are_explicit(vehicle_search_app_env) -> None:
    _seed_vehicle_search_dataset(vehicle_search_app_env["session_factory"])

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            invalid_body_style = await client.get(
                "/api/gallery/vehicles",
                params={"body_style": "spaceship"},
            )
            assert invalid_body_style.status_code == 422
            assert "Unsupported body_style" in invalid_body_style.json()["detail"]

            invalid_date_window = await client.get(
                "/api/gallery/vehicles",
                params={"date_from": "2026-03-04", "date_to": "2026-03-01"},
            )
            assert invalid_date_window.status_code == 422
            assert invalid_date_window.json()["detail"] == "date_from must be <= date_to"

    asyncio.run(_run())


def _configure_database_module_for_test(monkeypatch, engine, database_url: str) -> None:
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database_module.settings, "DATABASE_URL", database_url, raising=False)
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", session_factory)


def test_init_db_adds_vehicle_event_attribute_columns_and_indexes(tmp_path, monkeypatch) -> None:
    engine = _make_sqlite_engine(tmp_path / "legacy_vehicle_events_columns.db")
    database_url = str(engine.url)

    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE vehicle_events (
                    id INTEGER PRIMARY KEY,
                    plate_number VARCHAR(50),
                    plate_type VARCHAR(20) DEFAULT 'unknown',
                    camera_id INTEGER NOT NULL,
                    timestamp DATETIME NOT NULL,
                    pipeline_meta TEXT
                )
                """
            )

        _configure_database_module_for_test(monkeypatch, engine, database_url)
        database_module.init_db()

        inspector = inspect(engine)
        column_names = {column["name"] for column in inspector.get_columns("vehicle_events")}
        assert {"dominant_color", "brand", "model", "body_style"} <= column_names

        index_names = {index["name"] for index in inspector.get_indexes("vehicle_events")}
        assert {
            "ix_vehicle_events_color_timestamp",
            "ix_vehicle_events_brand_timestamp",
            "ix_vehicle_events_model_timestamp",
            "ix_vehicle_events_body_style_timestamp",
        } <= index_names
    finally:
        engine.dispose()


def test_init_db_normalizes_and_backfills_vehicle_event_attributes(tmp_path, monkeypatch) -> None:
    engine = _make_sqlite_engine(tmp_path / "legacy_vehicle_events_backfill.db")
    database_url = str(engine.url)

    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE vehicle_events (
                    id INTEGER PRIMARY KEY,
                    plate_number VARCHAR(50),
                    plate_type VARCHAR(20) DEFAULT 'unknown',
                    camera_id INTEGER NOT NULL,
                    timestamp DATETIME NOT NULL,
                    pipeline_meta TEXT,
                    dominant_color VARCHAR(30),
                    brand VARCHAR(100),
                    model VARCHAR(100),
                    body_style VARCHAR(50)
                )
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO vehicle_events (
                    id,
                    plate_number,
                    camera_id,
                    timestamp,
                    pipeline_meta,
                    dominant_color,
                    brand,
                    model,
                    body_style
                ) VALUES (
                    1,
                    'AA 123 BB',
                    1,
                    '2026-03-01 10:00:00',
                    :pipeline_meta,
                    'Bleu',
                    ' mercedes benz ',
                    '  GLC 300  ',
                    'SUV'
                )
                """,
                {
                    "pipeline_meta": json.dumps(
                        {
                            "vehicle_profile": {
                                "dominant_color": "white",
                                "brand": "Toyota",
                                "model": "RAV4",
                                "body_style": "sedan",
                            }
                        }
                    )
                },
            )
            conn.exec_driver_sql(
                """
                INSERT INTO vehicle_events (
                    id,
                    plate_number,
                    camera_id,
                    timestamp,
                    pipeline_meta,
                    dominant_color,
                    brand,
                    model,
                    body_style
                ) VALUES (
                    2,
                    'CC 456 DD',
                    2,
                    '2026-03-02 11:30:00',
                    :pipeline_meta,
                    NULL,
                    NULL,
                    NULL,
                    NULL
                )
                """,
                {
                    "pipeline_meta": json.dumps(
                        {
                            "vehicle_profile": {
                                "dominant_color": "blanc",
                                "make": "toyota",
                                "model": "Corolla Cross",
                                "body_style": "suv",
                            }
                        }
                    )
                },
            )

        _configure_database_module_for_test(monkeypatch, engine, database_url)
        database_module.init_db()

        with engine.begin() as conn:
            rows = conn.exec_driver_sql(
                """
                SELECT id, dominant_color, brand, model, body_style
                FROM vehicle_events
                ORDER BY id ASC
                """
            ).fetchall()

        assert rows[0] == (1, "blue", "Mercedes-Benz", "GLC 300", "suv_crossover")
        assert rows[1] == (2, "white", "Toyota", "Corolla Cross", "suv_crossover")
    finally:
        engine.dispose()
