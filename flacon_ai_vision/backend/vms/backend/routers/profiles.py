from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_admin, get_current_user
from vms.backend.models import User, Tenant
from vms.backend.services.setup_config_service import DEFAULT_PROFILES, get_setup_config_service
from vms.backend.services.subscription_service import (
    SUBSCRIPTION_TIERS,
    TENANT_PLANS,
    get_tenant_plan_limits,
    normalize_tier,
    resolve_subscription_for_tenant,
    upsert_subscription_for_tenant,
)

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_list(values: object) -> List[str]:
    if not values:
        return []
    return [str(item).strip().lower() for item in list(values) if str(item).strip()]


def _usage_to_project_type(usage_type: str | None) -> str:
    normalized = str(usage_type or "").strip().lower()
    if normalized in {"maison"}:
        return "home"
    if normalized in {"magasin", "entreprise", "parking"}:
        return "business"
    if normalized in {"securite_avancee", "soc", "security", "security_ops"}:
        return "soc"
    return "business"


def _resolve_project_type(
    config: Dict[str, object],
    *,
    db=None,
    tenant_id: int | None = None,
) -> str:
    if db is not None and tenant_id:
        try:
            tenant = db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
            if tenant and getattr(tenant, "project_type", None):
                return str(tenant.project_type)
        except Exception:
            pass
    return str(config.get("project_type") or _usage_to_project_type(config.get("usage_type") or "maison"))


def _build_legacy_subscription_config(config: Dict[str, object]) -> Dict[str, object]:
    return {
        "subscription_active": _parse_bool(
            os.getenv("SUBSCRIPTION_ACTIVE"),
            bool(config.get("subscription_active", False)),
        ),
        "subscription_tier": str(
            os.getenv("SUBSCRIPTION_TIER") or config.get("subscription_tier") or "free"
        ).strip().lower(),
        "subscription_expires_at": os.getenv("SUBSCRIPTION_EXPIRES_AT")
        or config.get("subscription_expires_at"),
    }


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


class SubscriptionUpdateRequest(BaseModel):
    user_id: int = Field(..., ge=1)
    tier: str = Field(..., min_length=1)
    active: bool = True
    expires_at: Optional[str] = None


def resolve_profile_config(
    config: Dict[str, object] | None = None,
    *,
    db=None,
    tenant_id: int | None = None,
) -> Dict[str, object]:
    config = config or get_setup_config_service().get_config()
    usage_type = str(config.get("usage_type") or "maison").strip().lower()
    defaults = DEFAULT_PROFILES.get(usage_type, DEFAULT_PROFILES["maison"])

    alert_types = _normalize_list(config.get("alert_types") or defaults.get("alert_types"))
    if "system" not in alert_types:
        alert_types.append("system")

    subscription = resolve_subscription_for_tenant(
        db,
        tenant_id,
        legacy_config=_build_legacy_subscription_config(config),
    )
    plan_limits = get_tenant_plan_limits(subscription.get("tier") or "starter")
    project_type = _resolve_project_type(config, db=db, tenant_id=tenant_id)

    profile = {
        "usage_type": usage_type,
        "project_type": project_type,
        "camera_limit": int(plan_limits.get("camera_limit") or config.get("camera_limit") or defaults.get("camera_limit") or 1),
        "detection_types": _normalize_list(config.get("detection_types") or defaults.get("detection_types")),
        "alert_types": alert_types,
        "alert_channels": _normalize_list(config.get("alert_channels") or defaults.get("alert_channels")),
        "ui_preset": str(config.get("ui_preset") or defaults.get("ui_preset") or "default"),
        "personnel_custom_fields": list(config.get("personnel_custom_fields") or []),
        "configured": bool(config.get("configured", False)),
        "subscription": subscription,
        "plan_limits": plan_limits,
    }
    return profile


@router.get("/current", summary="Get current profile restrictions")
async def get_current_profile(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = current_user.get("tenant_id")
    profile = resolve_profile_config(db=db, tenant_id=tenant_id)
    return {"status": "success", "profile": profile}


@router.get("/limits", summary="Get profile limits")
async def get_profile_limits(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = current_user.get("tenant_id")
    profile = resolve_profile_config(db=db, tenant_id=tenant_id)
    return {
        "status": "success",
        "usage_type": profile.get("usage_type"),
        "camera_limit": profile.get("camera_limit"),
        "alert_types": profile.get("alert_types"),
        "detection_types": profile.get("detection_types"),
    }


@router.get("/subscription", summary="Get subscription status")
async def get_subscription_status(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = current_user.get("tenant_id")
    profile = resolve_profile_config(db=db, tenant_id=tenant_id)
    return {"status": "success", "subscription": profile.get("subscription")}


@router.get("", summary="List users and subscription status")
def list_profiles(
    search: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    tenant_id = current_user.get("tenant_id")
    if tenant_id is not None:
        query = query.filter(User.tenant_id == tenant_id)
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            (User.username.ilike(term)) | (User.email.ilike(term)) | (User.full_name.ilike(term))
        )

    users = query.order_by(User.id.asc()).offset(skip).limit(limit).all()
    legacy_config = _build_legacy_subscription_config(get_setup_config_service().get_config())
    subscription = resolve_subscription_for_tenant(db, tenant_id, legacy_config=legacy_config)
    items = []
    for user in users:
        if tier and normalize_tier(tier) != subscription.get("tier"):
            continue

        items.append(
            {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "is_active": bool(user.is_active),
                "subscription": subscription,
            }
        )

    return {
        "status": "success",
        "count": len(items),
        "tiers": sorted(SUBSCRIPTION_TIERS.keys()),
        "users": items,
    }


@router.post("/update", summary="Update user subscription")
def update_subscription(
    payload: SubscriptionUpdateRequest,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == int(payload.user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    tenant_id = user.tenant_id or current_user.get("tenant_id")
    if current_user.get("tenant_id") and tenant_id != current_user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Cross-tenant update forbidden")

    tier = normalize_tier(payload.tier)
    expires_at = _parse_dt(payload.expires_at)
    subscription = upsert_subscription_for_tenant(
        db,
        tenant_id=int(tenant_id),
        tier=tier,
        active=payload.active,
        expires_at=expires_at,
        actor_user_id=current_user.get("user_id"),
        payload=payload.model_dump(),
    )

    return {
        "status": "success",
        "tenant_id": int(tenant_id),
        "subscription": {
            "tier": subscription.tier,
            "active": bool(subscription.is_active),
            "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
        },
    }
