# vms/backend/routers/admin_router.py - Admin panel endpoints

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.rbac import Permission, Role, get_rbac_manager
from ..core.security import get_current_admin, get_current_user
from ..models import AuditLog, Camera, Event, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["Admin"])


class AssignRoleRequest(BaseModel):
    role: str = Field(..., description="admin|supervisor|operator|viewer")


def _normalize_role(raw_role: Optional[str], is_admin: bool = False) -> str:
    role = (raw_role or "").strip().lower()
    if is_admin:
        return "admin"
    if role in {"admin", "operator", "viewer", "supervisor"}:
        return role
    return "operator"


def _rbac_role_from_name(role_name: str) -> Role:
    role = role_name.strip().lower()
    if role == "admin":
        return Role.ADMIN
    if role == "supervisor":
        return Role.SUPERVISOR
    if role == "viewer":
        return Role.VIEWER
    return Role.OPERATOR


def _permissions_for_role_name(role_name: str) -> List[str]:
    rbac = get_rbac_manager()
    role_enum = _rbac_role_from_name(role_name)
    perms = rbac.ROLE_PERMISSIONS.get(role_enum, set())
    return sorted({p.value for p in perms})


def _user_profile_from_row(user: User) -> Dict[str, Any]:
    role = _normalize_role(user.role, bool(user.is_admin))
    return {
        "user_id": user.id,
        "username": user.username,
        "roles": [role],
        "permissions": _permissions_for_role_name(role),
        "is_admin": role == "admin",
        "is_active": bool(user.is_active),
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def require_admin(current_user: dict = Depends(get_current_admin)) -> dict:
    # JWT role check is authoritative for admin endpoints.
    return current_user


@router.get("/health", summary="Admin panel health check", tags=["Admin"])
async def admin_health(current_user: dict = Depends(require_admin)):
    return {
        "status": "healthy",
        "admin_user": current_user.get("sub") or current_user.get("username"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/users", summary="List all users and their roles")
async def list_users(
    current_user: dict = Depends(require_admin),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    try:
        rows = (
            db.query(User)
            .order_by(User.id.asc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        total = db.query(func.count(User.id)).scalar() or 0
        users = [_user_profile_from_row(row) for row in rows]
        return {
            "status": "success",
            "total_users": int(total),
            "returned": len(users),
            "users": users,
        }
    except Exception as e:
        logger.error("Error listing users: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.get("/users/{user_id}", summary="Get specific user profile")
async def get_user_profile(
    user_id: int,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        row = db.query(User).filter(User.id == user_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return {"status": "success", "user": _user_profile_from_row(row)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Failed to fetch user")


@router.post("/users/{user_id}/roles", summary="Assign role to user")
async def assign_role_to_user(
    user_id: int,
    data: AssignRoleRequest,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        role_name = (data.role or "").strip().lower()
        if role_name not in {"admin", "supervisor", "operator", "viewer"}:
            raise HTTPException(status_code=400, detail="Invalid role")

        row = db.query(User).filter(User.id == user_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        row.role = role_name
        row.is_admin = role_name == "admin"
        row.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)

        logger.info(
            "Role %s assigned to user %s by %s",
            role_name,
            user_id,
            current_user.get("sub") or current_user.get("username"),
        )

        return {
            "status": "success",
            "message": f"Role {role_name} assigned to user {user_id}",
            "stored_role": role_name,
            "user": _user_profile_from_row(row),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error assigning role: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to assign role")


@router.delete("/users/{user_id}/roles/{role}", summary="Remove role from user")
async def remove_role_from_user(
    user_id: int,
    role: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        role_name = (role or "").strip().lower()
        if role_name not in {"admin", "supervisor", "operator", "viewer"}:
            raise HTTPException(status_code=400, detail="Invalid role")

        row = db.query(User).filter(User.id == user_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        current_role = _normalize_role(row.role, bool(row.is_admin))
        if current_role == role_name:
            # Safe fallback role after removing current one.
            row.role = "operator"
            row.is_admin = False
            row.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(row)

        logger.info(
            "Role %s removed from user %s by %s",
            role_name,
            user_id,
            current_user.get("sub") or current_user.get("username"),
        )

        return {
            "status": "success",
            "message": f"Role {role_name} removed from user {user_id}",
            "user": _user_profile_from_row(row),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error removing role: %s", e)
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to remove role")


@router.get("/roles", summary="List all roles and permissions")
async def list_roles(current_user: dict = Depends(require_admin)):
    try:
        rbac = get_rbac_manager()
        roles_info: Dict[str, Dict[str, Any]] = {}
        for role in Role:
            perms = sorted({p.value for p in rbac.ROLE_PERMISSIONS.get(role, set())})
            roles_info[role.value] = {
                "role": role.value,
                "permissions": perms,
                "permission_count": len(perms),
            }
        return {"status": "success", "roles": roles_info}
    except Exception as e:
        logger.error("Error listing roles: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list roles")


@router.get("/permissions", summary="List all permissions")
async def list_permissions(current_user: dict = Depends(require_admin)):
    try:
        permissions_list = [
            {
                "permission": p.value,
                "category": p.value.split(":")[0],
            }
            for p in Permission
        ]
        return {
            "status": "success",
            "total": len(permissions_list),
            "permissions": permissions_list,
        }
    except Exception as e:
        logger.error("Error listing permissions: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list permissions")


@router.get("/current-user", summary="Get current user profile")
async def get_current_user_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        user_id = int(current_user.get("user_id") or 0)
        if user_id <= 0:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        row = db.query(User).filter(User.id == user_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        return {"status": "success", "user": _user_profile_from_row(row)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching current user: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch user")


@router.post("/users/{user_id}/permissions/check", summary="Check if user has permission")
async def check_user_permission(
    user_id: int,
    permission: str,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        row = db.query(User).filter(User.id == user_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        role_name = _normalize_role(row.role, bool(row.is_admin))
        has_perm = permission in _permissions_for_role_name(role_name)
        return {
            "status": "success",
            "user_id": user_id,
            "permission": permission,
            "has_permission": has_perm,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error checking permission: %s", e)
        raise HTTPException(status_code=500, detail="Failed to check permission")


@router.get("/audit-log", summary="Get admin audit log")
async def get_audit_log(
    current_user: dict = Depends(require_admin),
    limit: int = Query(100, ge=1, le=500),
    action: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    try:
        query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
        if action:
            query = query.filter(AuditLog.action.ilike(f"%{action}%"))
        rows = query.limit(limit).all()
        records = [
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
        return {
            "status": "success",
            "total_records": len(records),
            "records": records,
        }
    except Exception as e:
        logger.error("Error reading audit logs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read audit logs")


@router.post("/system/restart", summary="[CRITICAL] Restart system")
async def system_restart(current_user: dict = Depends(require_admin)):
    logger.critical(
        "System restart requested by %s",
        current_user.get("sub") or current_user.get("username"),
    )
    return {
        "status": "success",
        "message": "System restart scheduled",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/system/statistics", summary="Get system statistics")
async def get_system_statistics(
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        utc_now = datetime.now(timezone.utc)
        start_today = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)

        total_users = int(db.query(func.count(User.id)).scalar() or 0)
        active_users = int(db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0)
        total_cameras = int(db.query(func.count(Camera.id)).scalar() or 0)
        active_cameras = int(db.query(func.count(Camera.id)).filter(Camera.is_active == True).scalar() or 0)
        events_today = int(db.query(func.count(Event.id)).filter(Event.created_at >= start_today).scalar() or 0)

        role_counts = {
            "admin": int(
                db.query(func.count(User.id))
                .filter((User.role == "admin") | (User.is_admin == True))
                .scalar()
                or 0
            ),
            "operator": int(db.query(func.count(User.id)).filter(User.role == "operator").scalar() or 0),
            "viewer": int(db.query(func.count(User.id)).filter(User.role == "viewer").scalar() or 0),
        }

        top_actions_rows = (
            db.query(AuditLog.action, func.count(AuditLog.id).label("count"))
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc())
            .limit(5)
            .all()
        )
        top_actions = [
            {"action": str(row.action or ""), "count": int(row.count or 0)}
            for row in top_actions_rows
        ]

        return {
            "status": "success",
            "statistics": {
                "timestamp": utc_now.isoformat(),
                "total_users": total_users,
                "active_users": active_users,
                "roles_configured": role_counts,
                "total_cameras": total_cameras,
                "active_cameras": active_cameras,
                "total_events_today": events_today,
                "top_audit_actions": top_actions,
            },
        }
    except Exception as e:
        logger.error("Error fetching statistics: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch statistics")
