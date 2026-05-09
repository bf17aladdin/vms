from __future__ import annotations

import logging
import os
from typing import Any, Optional

from sqlalchemy.orm import Session

from vms.backend import crud, models
from vms.backend.core.config import settings
from vms.backend.core.database import SessionLocal
from vms.backend.core.security import hash_password

logger = logging.getLogger("falcon_ai_vision.bootstrap")


def seed_admin_user(db: Optional[Session] = None) -> dict[str, Any]:
    admin_username = settings.ADMIN_USERNAME
    admin_password = settings.ADMIN_PASSWORD or "admin123"
    if not admin_password.strip():
        raise ValueError("ADMIN_PASSWORD cannot be empty when seeding admin user")

    owns_session = db is None
    db_session = db or SessionLocal()
    try:
        existing_admin = crud.get_user_by_username(db_session, admin_username)
        if existing_admin:
            updated = False
            if not existing_admin.is_admin:
                existing_admin.is_admin = True
                updated = True
            if existing_admin.role != "admin":
                existing_admin.role = "admin"
                updated = True
            if not existing_admin.is_active:
                existing_admin.is_active = True
                updated = True
            if getattr(existing_admin, "tenant_id", None) is None:
                crud.ensure_user_tenant(db_session, existing_admin)
                updated = True
            elif updated:
                db_session.commit()
            logger.info("Admin bootstrap complete for '%s' (updated=%s)", admin_username, updated)
            return {
                "status": "updated" if updated else "verified",
                "username": admin_username,
                "user_id": int(existing_admin.id),
                "tenant_id": getattr(existing_admin, "tenant_id", None),
            }

        tenant = crud.ensure_default_tenant(db_session)
        admin_user = models.User(
            username=admin_username,
            email=os.getenv("ADMIN_EMAIL", "admin@falcon.local").strip() or None,
            hashed_password=hash_password(admin_password),
            role="admin",
            is_active=True,
            is_admin=True,
            tenant_id=int(tenant.id),
        )
        db_session.add(admin_user)
        db_session.commit()
        db_session.refresh(admin_user)
        logger.info("Admin bootstrap created '%s'", admin_username)
        return {
            "status": "created",
            "username": admin_username,
            "user_id": int(admin_user.id),
            "tenant_id": int(tenant.id),
        }
    except Exception:
        if owns_session:
            db_session.rollback()
        raise
    finally:
        if owns_session:
            db_session.close()
