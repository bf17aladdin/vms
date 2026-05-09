# vms/backend/routers/users.py - User management routes

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.audit import write_audit_log
from ..core.database import get_db
from ..core.security import get_current_admin, get_current_user
from .. import crud, schemas
from ..models import AuditLog

router = APIRouter(prefix="/api/users", tags=["users"])
logger = logging.getLogger(__name__)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


class UserStatusRequest(BaseModel):
    is_active: bool


def _serialize_user(user) -> dict:
    role = (getattr(user, "role", None) or "").strip().lower()
    if not role:
        role = "admin" if bool(getattr(user, "is_admin", False)) else "operator"
    return {
        "id": user.id,
        "tenant_id": getattr(user, "tenant_id", None),
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": role,
        "is_admin": bool(user.is_admin),
        "is_active": bool(user.is_active),
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


@router.get("/audit/history", response_model=dict)
def get_user_audit_history(
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Historique des actions utilisateurs/admin (audit logs)."""
    try:
        query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
        if user_id is not None:
            query = query.filter(AuditLog.user_id == user_id)
        if action:
            query = query.filter(AuditLog.action.ilike(f"%{action}%"))

        rows = query.offset(skip).limit(limit).all()
        items = [
            {
                "id": row.id,
                "user_id": row.user_id,
                "username": row.username,
                "event_type": row.event_type,
                "action": row.action,
                "method": row.method,
                "path": row.path,
                "status_code": row.status_code,
                "ip_address": row.ip_address,
                "request_id": row.request_id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "details": row.details,
            }
            for row in rows
        ]
        return {"count": len(items), "logs": items, "message": "Audit history retrieved successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=dict)
def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List users (admin only)."""
    try:
        tenant_id = current_user.get("tenant_id")
        users = crud.get_all_users(db, skip=skip, limit=limit, tenant_id=tenant_id)
        return {
            "count": len(users),
            "users": [_serialize_user(u) for u in users],
            "message": "Users retrieved successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=dict)
def create_user(
    payload: schemas.UserCreate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Create a user (admin only)."""
    try:
        tenant_id = current_user.get("tenant_id")
        data = payload.model_dump()
        if tenant_id is not None:
            if data.get("tenant_id") and int(data.get("tenant_id")) != int(tenant_id):
                raise HTTPException(status_code=403, detail="Cross-tenant user creation forbidden")
            data["tenant_id"] = int(tenant_id)
        user = crud.create_user(db, schemas.UserCreate(**data))
        write_audit_log(
            event_type="admin_user",
            action="create_user",
            method="POST",
            path="/api/users",
            status_code=200,
            user_id=current_user.get("user_id"),
            username=current_user.get("sub"),
            details={"target_user_id": user.id, "target_username": user.username},
        )
        return {
            **_serialize_user(user),
            "message": "User created successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profile/me", response_model=dict)
def get_my_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Current authenticated profile."""
    try:
        user_id = current_user.get("user_id") or current_user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid authentication payload")
        user = crud.get_user_by_id(db, int(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            **_serialize_user(user),
            "message": "Profile retrieved successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{user_id}", response_model=dict)
def get_user(
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get one user."""
    try:
        user = crud.get_user_by_id(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        tenant_id = current_user.get("tenant_id")
        if tenant_id is not None and user.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Cross-tenant access forbidden")
        return {
            **_serialize_user(user),
            "message": "User retrieved successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{user_id}", response_model=dict)
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Update user."""
    try:
        existing = crud.get_user_by_id(db, user_id)
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")
        tenant_id = current_user.get("tenant_id")
        if tenant_id is not None and existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Cross-tenant update forbidden")
        user = crud.update_user(db, user_id, payload)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        write_audit_log(
            event_type="admin_user",
            action="update_user",
            method="PUT",
            path=f"/api/users/{user_id}",
            status_code=200,
            user_id=current_user.get("user_id"),
            username=current_user.get("sub"),
            details={"target_user_id": user_id},
        )
        return {
            **_serialize_user(user),
            "message": "User updated successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{user_id}/status", response_model=dict)
def set_user_status(
    user_id: int,
    payload: UserStatusRequest,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Enable/disable a user account."""
    try:
        user = crud.update_user(db, user_id, schemas.UserUpdate(is_active=payload.is_active))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        write_audit_log(
            event_type="admin_user",
            action="set_user_status",
            method="PATCH",
            path=f"/api/users/{user_id}/status",
            status_code=200,
            user_id=current_user.get("user_id"),
            username=current_user.get("sub"),
            details={"target_user_id": user_id, "is_active": payload.is_active},
        )
        return {
            **_serialize_user(user),
            "message": "User status updated successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{user_id}/reset-password", response_model=dict)
def reset_user_password(
    user_id: int,
    payload: ResetPasswordRequest,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Reset user password (admin only)."""
    try:
        user = crud.update_user(db, user_id, schemas.UserUpdate(password=payload.new_password))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        write_audit_log(
            event_type="admin_user",
            action="reset_password",
            method="POST",
            path=f"/api/users/{user_id}/reset-password",
            status_code=200,
            user_id=current_user.get("user_id"),
            username=current_user.get("sub"),
            details={"target_user_id": user_id},
        )
        return {"id": user.id, "message": "Password reset successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{user_id}", response_model=dict)
def delete_user(
    user_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Delete user."""
    try:
        current_user_id = current_user.get("user_id")
        if current_user_id is not None and int(current_user_id) == int(user_id):
            raise HTTPException(status_code=409, detail="Vous ne pouvez pas supprimer votre propre compte.")

        existing = crud.get_user_by_id(db, user_id)
        if not existing:
            raise HTTPException(status_code=404, detail="User not found")
        tenant_id = current_user.get("tenant_id")
        if tenant_id is not None and existing.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Cross-tenant delete forbidden")
        success = crud.delete_user(db, user_id)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        write_audit_log(
            event_type="admin_user",
            action="delete_user",
            method="DELETE",
            path=f"/api/users/{user_id}",
            status_code=200,
            user_id=current_user.get("user_id"),
            username=current_user.get("sub"),
            details={"target_user_id": user_id},
        )
        return {
            "id": user_id,
            "message": "User deleted successfully",
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception("delete_user failed user_id=%s actor=%s", user_id, current_user.get("user_id"))
        raise HTTPException(status_code=500, detail=str(e))
