from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx

from vms.backend.core.database import SessionLocal
from vms.backend.core.security import create_access_token, hash_password
from vms.backend.main import app
from vms.backend.models import User

ADMIN_USERNAME = "pytest_admin_api"
ADMIN_PASSWORD = "PytestAdminApi123!"


def _ensure_admin_user() -> int:
    with SessionLocal() as db:
        row = db.query(User).filter(User.username == ADMIN_USERNAME).first()
        if row is None:
            row = User(
                username=ADMIN_USERNAME,
                email=None,
                hashed_password=hash_password(ADMIN_PASSWORD),
                full_name="Pytest Admin API",
                role="admin",
                is_admin=True,
                is_active=True,
            )
            db.add(row)
        else:
            row.hashed_password = hash_password(ADMIN_PASSWORD)
            row.role = "admin"
            row.is_admin = True
            row.is_active = True
            if not row.full_name:
                row.full_name = "Pytest Admin API"
        db.commit()
        db.refresh(row)
        return int(row.id)


def _auth_headers(user_id: int) -> dict[str, str]:
    token = create_access_token(
        data={"sub": ADMIN_USERNAME, "user_id": int(user_id), "role": "admin"}
    )
    return {"Authorization": f"Bearer {token}"}


def test_security_module_authenticated_crud() -> None:
    admin_user_id = _ensure_admin_user()
    
    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = _auth_headers(admin_user_id)

            no_auth_resp = await client.get("/api/security-config/rules")
            assert no_auth_resp.status_code in {401, 403}

            list_resp = await client.get("/api/security-config/rules", headers=headers)
            assert list_resp.status_code == 200, list_resp.text

            create_payload = {
                "name": f"pytest-security-rule-{uuid4().hex[:8]}",
                "description": "created by authenticated CRUD test",
                "rule_type": "zone",
                "points": [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2]],
                "direction_mode": "both",
                "schedule_mode": "always",
                "sensitivity": 55,
                "object_type_filter": "both",
                "is_active": True,
            }
            create_resp = await client.post("/api/security-config/rules", json=create_payload, headers=headers)
            assert create_resp.status_code == 200, create_resp.text
            created_rule = create_resp.json().get("rule") or {}
            rule_id = created_rule.get("id")
            assert rule_id, create_resp.text

            try:
                update_resp = await client.put(
                    f"/api/security-config/rules/{rule_id}",
                    json={
                        "name": f"pytest-security-rule-updated-{uuid4().hex[:6]}",
                        "sensitivity": 70,
                    },
                    headers=headers,
                )
                assert update_resp.status_code == 200, update_resp.text
                updated = update_resp.json().get("rule") or {}
                assert int(updated.get("sensitivity", -1)) == 70
            finally:
                delete_resp = await client.delete(f"/api/security-config/rules/{rule_id}", headers=headers)
                assert delete_resp.status_code == 200, delete_resp.text

    asyncio.run(_run())


def test_admin_module_authenticated_crud() -> None:
    admin_user_id = _ensure_admin_user()

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = _auth_headers(admin_user_id)

            list_resp = await client.get("/api/users", headers=headers)
            assert list_resp.status_code == 200, list_resp.text

            username = f"pytest_user_{uuid4().hex[:10]}"
            create_resp = await client.post(
                "/api/users",
                json={
                    "username": username,
                    "password": "PytestUser123!",
                    "email": f"{username}@example.com",
                    "full_name": "Pytest Managed User",
                    "role": "viewer",
                    "is_active": True,
                },
                headers=headers,
            )
            assert create_resp.status_code == 200, create_resp.text
            user_id = create_resp.json().get("id")
            assert user_id, create_resp.text

            try:
                update_resp = await client.put(
                    f"/api/users/{user_id}",
                    json={"full_name": "Pytest Updated User", "role": "operator"},
                    headers=headers,
                )
                assert update_resp.status_code == 200, update_resp.text
                assert update_resp.json().get("full_name") == "Pytest Updated User"
            finally:
                delete_resp = await client.delete(f"/api/users/{user_id}", headers=headers)
                assert delete_resp.status_code == 200, delete_resp.text

    asyncio.run(_run())


def test_reporting_module_authenticated_routes() -> None:
    admin_user_id = _ensure_admin_user()

    async def _run() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = _auth_headers(admin_user_id)

            templates_resp = await client.get("/api/reporting/templates", headers=headers)
            assert templates_resp.status_code == 200, templates_resp.text

            schedule_resp = await client.post(
                "/api/reporting/schedule",
                json={
                    "report_type": "detection_log",
                    "format": "json",
                    "frequency": "daily",
                    "time_of_day": "00:10",
                },
                headers=headers,
            )
            assert schedule_resp.status_code == 200, schedule_resp.text
            job_id = schedule_resp.json().get("job_id")
            assert job_id, schedule_resp.text

            scheduled_resp = await client.get("/api/reporting/scheduled", headers=headers)
            assert scheduled_resp.status_code == 200, scheduled_resp.text

            delete_resp = await client.delete(f"/api/reporting/scheduled/{job_id}", headers=headers)
            assert delete_resp.status_code == 200, delete_resp.text

            # Reporting module currently exposes no PUT endpoints; validate this contract explicitly.
            put_resp = await client.put("/api/reporting/health", headers=headers)
            assert put_resp.status_code in {404, 405}

    asyncio.run(_run())
