# vms/backend/routers/auth.py - Authentication routes

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import os
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..core.audit import write_audit_log
from ..core.config import settings
from ..core.database import get_db
from ..core.security import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_token,
    verify_refresh_token,
)
from ..models import RefreshToken, User
from ..services.subscription_service import normalize_tier, upsert_subscription_for_tenant

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("falcon_ai_vision.auth")

_LOGIN_RATE_LOCK = threading.Lock()
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}


def _effective_user_role(user: User) -> str:
    role = str(getattr(user, "role", "") or "").strip().lower()
    if role not in {"admin", "supervisor", "operator", "viewer"}:
        role = "admin" if bool(user.is_admin) else "operator"
    if bool(user.is_admin):
        role = "admin"
    return role


def _check_login_rate_limit(request: Request) -> None:
    ip = (request.client.host if request.client else "unknown") or "unknown"
    now = time.time()
    max_attempts = max(3, int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "15")))
    window_sec = max(10, int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SEC", "60")))

    with _LOGIN_RATE_LOCK:
        previous = _LOGIN_ATTEMPTS.get(ip, [])
        active = [ts for ts in previous if now - ts <= window_sec]
        if len(active) >= max_attempts:
            raise HTTPException(
                status_code=429,
                detail=f"Too many login attempts. Retry in {window_sec} seconds.",
            )
        active.append(now)
        _LOGIN_ATTEMPTS[ip] = active


def _clear_login_rate_limit(request: Request) -> None:
    ip = (request.client.host if request.client else "unknown") or "unknown"
    with _LOGIN_RATE_LOCK:
        _LOGIN_ATTEMPTS.pop(ip, None)


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str | None = None
    email: str | None = None
    company_name: str | None = None
    plan: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None
    revoke_all: bool = False


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    refresh_expires_in: int
    user: dict


def _user_payload(user: User) -> dict:
    role = _effective_user_role(user)
    return {
        "id": user.id,
        "tenant_id": getattr(user, "tenant_id", None),
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "role": role,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "redirect_url": "/dashboard.html",
    }


def _issue_tokens(user: User, db: Session, request: Request) -> tuple[str, str]:
    role = _effective_user_role(user)
    access_token = create_access_token(
        data={"sub": user.username, "user_id": user.id, "role": role, "tenant_id": getattr(user, "tenant_id", None)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    refresh_token = create_refresh_token(
        data={"sub": user.username, "user_id": user.id, "role": role, "tenant_id": getattr(user, "tenant_id", None)},
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(
        RefreshToken(
            user_id=int(user.id),
            token_hash=hash_token(refresh_token),
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            is_revoked=False,
            created_by_ip=(request.client.host if request.client else None),
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        )
    )
    db.commit()
    return access_token, refresh_token


def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    try:
        _check_login_rate_limit(request)
        user = crud.authenticate_user(db, payload.username, payload.password)
        if not user:
            write_audit_log(
                event_type="auth",
                action="login_failed",
                method=request.method,
                path=str(request.url.path),
                status_code=401,
                username=payload.username,
                ip_address=(request.client.host if request.client else None),
                user_agent=request.headers.get("user-agent"),
            )
            raise HTTPException(status_code=401, detail="Invalid username or password")
        user = crud.ensure_user_tenant(db, user)
        if not user.is_active:
            write_audit_log(
                event_type="auth",
                action="login_blocked",
                method=request.method,
                path=str(request.url.path),
                status_code=403,
                user_id=user.id,
                username=user.username,
                ip_address=(request.client.host if request.client else None),
                user_agent=request.headers.get("user-agent"),
            )
            raise HTTPException(status_code=403, detail="User account is disabled")

        user.last_login = datetime.utcnow()
        access_token, refresh_token = _issue_tokens(user, db, request)
        _clear_login_rate_limit(request)
        write_audit_log(
            event_type="auth",
            action="login_success",
            method=request.method,
            path=str(request.url.path),
            status_code=200,
            user_id=user.id,
            username=user.username,
            ip_address=(request.client.host if request.client else None),
            user_agent=request.headers.get("user-agent"),
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
            "refresh_expires_in": int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600),
            "user": _user_payload(user),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Login failed for username=%s", payload.username)
        detail = str(e).strip() or repr(e)
        raise HTTPException(status_code=500, detail=detail)


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    parsed = verify_refresh_token(payload.refresh_token)
    if not parsed:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    token_hash = hash_token(payload.refresh_token)
    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash)
        .filter(RefreshToken.is_revoked == False)  # noqa: E712
        .first()
    )
    if row is None:
        raise HTTPException(status_code=401, detail="Refresh token revoked")
    if row.expires_at and _to_utc_naive(row.expires_at) < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        raise HTTPException(status_code=403, detail="User account is disabled")
    user = crud.ensure_user_tenant(db, user)
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")

    role = _effective_user_role(user)
    access_token = create_access_token(
        data={"sub": user.username, "user_id": user.id, "role": role, "tenant_id": getattr(user, "tenant_id", None)},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    if settings.REFRESH_TOKEN_ROTATE:
        row.is_revoked = True
        row.revoked_at = datetime.utcnow()
        new_refresh = create_refresh_token(
            data={"sub": user.username, "user_id": user.id, "role": role, "tenant_id": getattr(user, "tenant_id", None)},
            expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        new_hash = hash_token(new_refresh)
        row.replaced_by_token_hash = new_hash
        db.add(
            RefreshToken(
                user_id=int(user.id),
                token_hash=new_hash,
                expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
                is_revoked=False,
                created_by_ip=(request.client.host if request.client else None),
                user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            )
        )
        refresh_token_value = new_refresh
    else:
        refresh_token_value = payload.refresh_token

    db.commit()
    write_audit_log(
        event_type="auth",
        action="refresh_success",
        method=request.method,
        path=str(request.url.path),
        status_code=200,
        user_id=user.id,
        username=user.username,
        ip_address=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token_value,
        "token_type": "bearer",
        "expires_in": int(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60),
        "refresh_expires_in": int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600),
        "user": _user_payload(user),
    }


@router.post("/register", response_model=dict)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    try:
        company_name = (payload.company_name or "").strip() or f"{payload.username} Company"
        plan = normalize_tier(payload.plan or "starter")

        tenant = crud.create_tenant(db, name=company_name, plan=plan)

        user_create = schemas.UserCreate(
            username=payload.username,
            password=payload.password,
            full_name=payload.full_name,
            email=payload.email,
            role="admin",
            is_admin=True,
            tenant_id=int(tenant.id),
        )
        user = crud.create_user(db, user_create)

        try:
            upsert_subscription_for_tenant(
                db,
                tenant_id=int(tenant.id),
                tier=plan,
                active=True,
                expires_at=None,
                actor_user_id=user.id,
                payload={"plan": plan, "company": company_name},
            )
        except Exception:
            pass

        return {
            "id": user.id,
            "tenant_id": tenant.id,
            "tenant_name": tenant.name,
            "plan": plan,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "message": "User created successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/signup", response_model=dict)
def signup(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Alias endpoint for register (public website)."""
    return register(payload, db)


@router.post("/logout", response_model=dict)
def logout(
    request: Request,
    payload: LogoutRequest | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload = payload or LogoutRequest()
    revoked = 0
    if payload.revoke_all:
        revoked = (
            db.query(RefreshToken)
            .filter(RefreshToken.user_id == int(current_user.get("user_id", 0)))
            .filter(RefreshToken.is_revoked == False)  # noqa: E712
            .update(
                {
                    RefreshToken.is_revoked: True,
                    RefreshToken.revoked_at: datetime.utcnow(),
                },
                synchronize_session=False,
            )
        )
    elif payload.refresh_token:
        token_hash = hash_token(payload.refresh_token)
        row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
        if row and not row.is_revoked:
            row.is_revoked = True
            row.revoked_at = datetime.utcnow()
            revoked = 1
    db.commit()

    write_audit_log(
        event_type="auth",
        action="logout",
        method=request.method,
        path=str(request.url.path),
        status_code=200,
        user_id=current_user.get("user_id"),
        username=current_user.get("sub"),
        ip_address=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
        details={"revoked_tokens": revoked, "revoke_all": payload.revoke_all},
    )
    return {"message": "Logged out successfully", "revoked_tokens": revoked}


@router.get("/me", response_model=dict)
def get_current_user_info(current_user: dict = Depends(get_current_user)):
    return {"user": current_user, "message": "User info retrieved successfully"}
