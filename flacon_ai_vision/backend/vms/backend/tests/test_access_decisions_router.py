from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vms.backend.core.database import get_db
from vms.backend.models import Base, Personnel, PersonnelCategoryEnum
from vms.backend.routers import access_decisions


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "access_decisions_router.sqlite"
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
    app.include_router(access_decisions.router)

    def override_get_db():
        yield db_session

    def override_require_operator():
        return {"sub": "operator@example.com", "user_id": 7, "role": "operator"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[access_decisions.require_operator] = override_require_operator
    return app


def test_access_decision_route_returns_explained_allow_and_writes_audit(
    app,
    db_session,
    monkeypatch,
) -> None:
    _patch_testclient_httpx(monkeypatch)

    person = Personnel(
        nom="Diallo",
        prenom="Awa",
        full_name="Awa Diallo",
        cin="CIN-ROUTE-001",
        num_recrutement="REC-ROUTE-001",
        categorie=PersonnelCategoryEnum.CIVIL,
        grade="Agent",
        allowed_camera_ids=[4],
        authorized_hours_start="06:00",
        authorized_hours_end="22:00",
        is_active=True,
        is_blacklisted=False,
    )
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)

    audit_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        access_decisions,
        "write_audit_log",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/access-decisions/evaluate",
            json={
                "detection_type": "face",
                "confidence": 0.98,
                "personnel_id": int(person.id),
                "camera_id": 4,
                "detected_at": datetime(2026, 4, 19, 9, 15, 0).isoformat(),
            },
        )

    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["decision"] == "allow"
    assert payload["reason_code"] == "personnel_authorized"
    assert payload["explanation"]
    assert payload["unknown_queue_action"] == "not_needed"
    assert any(
        check["code"] == "identity_resolved" and check["passed"] is True
        for check in payload["checks"]
    )

    assert len(audit_calls) == 1
    assert audit_calls[0]["event_type"] == "access_decision"
    assert audit_calls[0]["action"] == "evaluate_face"
    assert audit_calls[0]["details"]["decision"] == "allow"


def test_access_decision_route_preserves_unknown_queue_requirement(
    app,
    monkeypatch,
) -> None:
    _patch_testclient_httpx(monkeypatch)

    monkeypatch.setattr(access_decisions, "write_audit_log", lambda **kwargs: None)

    with TestClient(app) as client:
        response = client.post(
            "/api/access-decisions/evaluate",
            json={
                "detection_type": "face",
                "confidence": 0.74,
                "camera_id": 11,
                "detected_at": datetime(2026, 4, 19, 21, 0, 0).isoformat(),
            },
        )

    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["decision"] == "unknown"
    assert payload["reason_code"] == "personnel_unrecognized"
    assert payload["unknown_queue_action"] == "required"
    assert "unknown queue" in payload["explanation"].lower()
