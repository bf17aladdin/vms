from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vms.backend.models import Base, Personnel, PersonnelCategoryEnum, VehicleRegistry
from vms.backend.services.access_decision_service import AccessDecisionRequest, AccessDecisionService


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "access_decision_service.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_face_authorized_returns_allow_with_explanation(db_session) -> None:
    person = Personnel(
        nom="Diallo",
        prenom="Awa",
        full_name="Awa Diallo",
        cin="CIN-ACCESS-001",
        num_recrutement="REC-ACCESS-001",
        categorie=PersonnelCategoryEnum.CIVIL,
        grade="Agent",
        allowed_camera_ids=[12],
        authorized_hours_start="06:00",
        authorized_hours_end="22:00",
        is_active=True,
        is_blacklisted=False,
    )
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)

    result = AccessDecisionService(db_session).evaluate(
        AccessDecisionRequest(
            detection_type="face",
            confidence=0.97,
            personnel_id=int(person.id),
            camera_id=12,
            detected_at=datetime(2026, 4, 19, 10, 30, 0),
        )
    )

    assert result.decision == "allow"
    assert result.reason_code == "personnel_authorized"
    assert "autorise" in result.explanation.lower()
    assert result.unknown_queue_action == "not_needed"
    assert all(check.passed for check in result.checks)


def test_face_forbidden_returns_deny_with_reason(db_session) -> None:
    person = Personnel(
        nom="Sow",
        prenom="Moussa",
        full_name="Moussa Sow",
        cin="CIN-ACCESS-002",
        num_recrutement="REC-ACCESS-002",
        categorie=PersonnelCategoryEnum.SOLDAT,
        grade="Caporal",
        allowed_camera_ids=[8],
        authorized_hours_start="06:00",
        authorized_hours_end="22:00",
        is_active=True,
        is_blacklisted=True,
    )
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)

    result = AccessDecisionService(db_session).evaluate(
        AccessDecisionRequest(
            detection_type="face",
            confidence=0.94,
            personnel_id=int(person.id),
            camera_id=8,
            detected_at=datetime(2026, 4, 19, 11, 0, 0),
        )
    )

    assert result.decision == "deny"
    assert result.reason_code == "personnel_blacklisted"
    assert "blackliste" in result.explanation.lower()
    assert result.unknown_queue_action == "not_needed"
    assert any(check.code == "personnel_not_blacklisted" and not check.passed for check in result.checks)


def test_unknown_face_returns_unknown_and_requires_unknown_queue(db_session) -> None:
    result = AccessDecisionService(db_session).evaluate(
        AccessDecisionRequest(
            detection_type="face",
            confidence=0.71,
            personnel_id=None,
            camera_id=5,
            detected_at=datetime(2026, 4, 19, 12, 0, 0),
        )
    )

    assert result.decision == "unknown"
    assert result.reason_code == "personnel_unrecognized"
    assert "unknown queue" in result.explanation.lower()
    assert result.unknown_queue_action == "required"
    assert any(check.code == "identity_resolved" and not check.passed for check in result.checks)


def test_wrong_vehicle_returns_deny_and_keeps_unknown_queue_requirement(db_session) -> None:
    db_session.add(
        VehicleRegistry(
            matricule="123 TUNIS 4567",
            marque="Toyota",
            modele="Hilux",
            categorie="civil",
            statut="actif",
            is_blacklisted=False,
            is_flagged=False,
        )
    )
    db_session.commit()

    result = AccessDecisionService(db_session).evaluate(
        AccessDecisionRequest(
            detection_type="vehicle",
            confidence=0.88,
            plate_number="999 TUNIS 0000",
            detected_at=datetime(2026, 4, 19, 13, 0, 0),
        )
    )

    assert result.decision == "deny"
    assert result.reason_code == "vehicle_not_in_registry"
    assert "refuse" in result.explanation.lower()
    assert result.unknown_queue_action == "required"
    assert any(check.code == "vehicle_in_registry" and not check.passed for check in result.checks)
