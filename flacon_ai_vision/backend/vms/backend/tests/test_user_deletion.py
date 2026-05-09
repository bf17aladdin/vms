from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from vms.backend import crud
from vms.backend.models import (
    AuditLog,
    Base,
    Camera,
    Notification,
    RefreshToken,
    SecurityAlert,
    UnknownDetection,
    User,
    VehicleAccessLog,
    VehicleEvent,
    Event,
)


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "user_delete.sqlite"
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


def test_delete_user_cleans_ancillary_references(db_session) -> None:
    target_user = User(
        username="target-user",
        email="target@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    owner_user = User(
        username="owner-user",
        email="owner@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    db_session.add_all([target_user, owner_user])
    db_session.flush()

    camera = Camera(
        name="North Gate",
        owner_id=owner_user.id,
        connection_status="online",
        is_active=True,
    )
    db_session.add(camera)
    db_session.flush()

    vehicle_event = VehicleEvent(
        camera_id=camera.id,
        timestamp=datetime.now(timezone.utc),
        plate_type="unknown",
    )
    db_session.add(vehicle_event)
    db_session.flush()

    db_session.add_all(
        [
            RefreshToken(
                user_id=target_user.id,
                token_hash="refresh-token-hash",
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            ),
            AuditLog(
                user_id=target_user.id,
                username=target_user.username,
                event_type="auth",
                action="login",
                method="POST",
                path="/api/auth/login",
                status_code=200,
            ),
            Notification(
                user_id=target_user.id,
                title="Test notification",
                message="Delete me with the user",
                notification_type="info",
            ),
            UnknownDetection(
                detection_type="face",
                image_path="snapshots/unknown-face.jpg",
                camera_id=camera.id,
                resolved_by_user_id=target_user.id,
            ),
            VehicleAccessLog(
                event_id=vehicle_event.id,
                camera_id=camera.id,
                timestamp=datetime.now(timezone.utc),
                direction="IN",
                operator_id=target_user.id,
            ),
            SecurityAlert(
                type="blacklist",
                timestamp=datetime.now(timezone.utc),
                handled_by=target_user.id,
            ),
        ]
    )
    db_session.commit()

    assert crud.delete_user(db_session, target_user.id) is True

    assert crud.get_user_by_id(db_session, target_user.id) is None
    assert db_session.query(RefreshToken).filter(RefreshToken.user_id == target_user.id).count() == 0
    assert db_session.query(Notification).filter(Notification.user_id == target_user.id).count() == 0

    audit_log = db_session.query(AuditLog).one()
    assert audit_log.user_id is None
    assert audit_log.username == "target-user"

    unknown_detection = db_session.query(UnknownDetection).one()
    assert unknown_detection.resolved_by_user_id is None

    access_log = db_session.query(VehicleAccessLog).one()
    assert access_log.operator_id is None

    security_alert = db_session.query(SecurityAlert).one()
    assert security_alert.handled_by is None


def test_delete_user_rejects_business_owned_records(db_session) -> None:
    target_user = User(
        username="blocked-user",
        email="blocked@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    owner_user = User(
        username="other-owner",
        email="other-owner@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    db_session.add_all([target_user, owner_user])
    db_session.flush()

    owned_camera = Camera(
        name="South Gate",
        owner_id=target_user.id,
        connection_status="online",
        is_active=True,
    )
    foreign_camera = Camera(
        name="East Gate",
        owner_id=owner_user.id,
        connection_status="online",
        is_active=True,
    )
    db_session.add_all([owned_camera, foreign_camera])
    db_session.flush()

    created_event = Event(
        camera_id=foreign_camera.id,
        creator_id=target_user.id,
        event_type="motion",
        severity="info",
        detected_at=datetime.now(timezone.utc),
    )
    db_session.add(created_event)
    db_session.commit()

    with pytest.raises(ValueError, match="caméra\\(s\\).*événement\\(s\\)"):
        crud.delete_user(db_session, target_user.id)

    assert crud.get_user_by_id(db_session, target_user.id) is not None
    assert db_session.query(Camera).filter(Camera.owner_id == target_user.id).count() == 1
    assert db_session.query(Event).filter(Event.creator_id == target_user.id).count() == 1
