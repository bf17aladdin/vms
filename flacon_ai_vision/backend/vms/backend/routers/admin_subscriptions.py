# vms/backend/routers/admin_subscriptions.py - Admin subscription management

from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from vms.backend.core.audit import write_audit_log
from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_admin
from vms.backend.models import Subscription, SubscriptionHistory, SubscriptionPayment, User
from vms.backend.services.setup_config_service import get_setup_config_service
from vms.backend.services.subscription_service import (
    SUBSCRIPTION_TIERS,
    normalize_tier,
    resolve_subscription_for_user,
    serialize_subscription,
    upsert_subscription,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/subscriptions", tags=["Admin Subscriptions"])


class SubscriptionUpsertRequest(BaseModel):
    tier: str = Field(..., description="free|starter|business|enterprise")
    active: bool = True
    expires_at: Optional[str] = None
    renewal_at: Optional[str] = None
    auto_renew: bool = False
    renewal_period_days: Optional[int] = Field(None, ge=1, le=3650)
    provider: Optional[str] = None
    external_id: Optional[str] = None
    note: Optional[str] = None


class PaymentCreateRequest(BaseModel):
    provider: Optional[str] = Field(None, description="stripe|paypal|manual")
    amount: Optional[float] = Field(None, ge=0)
    currency: str = Field("USD", min_length=1, max_length=10)
    status: str = Field("paid", min_length=2, max_length=30)
    paid_at: Optional[str] = None
    reference_id: Optional[str] = None
    note: Optional[str] = None


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


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


def _build_legacy_subscription_config() -> Dict[str, object]:
    config = get_setup_config_service().get_config()
    raw_active = os.getenv("SUBSCRIPTION_ACTIVE")
    active = (
        str(raw_active).strip().lower() in {"1", "true", "yes", "on"}
        if raw_active is not None
        else bool(config.get("subscription_active", False))
    )
    return {
        "subscription_active": active,
        "subscription_tier": str(
            os.getenv("SUBSCRIPTION_TIER") or config.get("subscription_tier") or "free"
        ).strip().lower(),
        "subscription_expires_at": os.getenv("SUBSCRIPTION_EXPIRES_AT")
        or config.get("subscription_expires_at"),
    }


def _user_summary(user: User) -> Dict[str, object]:
    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": bool(user.is_active),
        "is_admin": bool(user.is_admin),
        "last_login": _iso(user.last_login),
    }


@router.get("", summary="List users and subscription status")
def list_subscriptions(
    request: Request,
    search: Optional[str] = Query(None),
    tier: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(active|inactive|expired)?$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    try:
        query = db.query(User)
        if search:
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(User.username.ilike(term), User.email.ilike(term), User.full_name.ilike(term))
            )

        users = query.order_by(User.id.asc()).offset(skip).limit(limit).all()
        items: List[Dict[str, object]] = []
        legacy_config = _build_legacy_subscription_config()

        for user in users:
            sub_row = (
                db.query(Subscription)
                .filter(Subscription.user_id == int(user.id))
                .first()
            )
            if sub_row is not None:
                subscription = serialize_subscription(sub_row)
            else:
                subscription = resolve_subscription_for_user(db, int(user.id), legacy_config=legacy_config)

            if tier and normalize_tier(tier) != subscription.get("tier"):
                continue
            if status and str(subscription.get("status", "")).lower() != status:
                continue

            items.append(
                {
                    **_user_summary(user),
                    "subscription": subscription,
                }
            )

        return {
            "status": "success",
            "count": len(items),
            "users": items,
            "tiers": sorted(SUBSCRIPTION_TIERS.keys()),
        }
    except Exception as exc:
        logger.error("Failed to list subscriptions: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list subscriptions")


@router.get("/{user_id}", summary="Get subscription details for a user")
def get_subscription(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub_row = db.query(Subscription).filter(Subscription.user_id == int(user_id)).first()
    if sub_row is None:
        subscription = resolve_subscription_for_user(db, int(user_id), legacy_config=_build_legacy_subscription_config())
    else:
        subscription = serialize_subscription(sub_row)

    return {
        "status": "success",
        "user": _user_summary(user),
        "subscription": subscription,
    }


@router.post("/{user_id}", summary="Create or update a subscription")
def upsert_user_subscription(
    user_id: int,
    payload: SubscriptionUpsertRequest,
    request: Request,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    expires_at = _parse_dt(payload.expires_at)
    renewal_at = _parse_dt(payload.renewal_at)

    subscription = upsert_subscription(
        db,
        user_id=int(user_id),
        tier=payload.tier,
        active=payload.active,
        expires_at=expires_at,
        auto_renew=payload.auto_renew,
        renewal_at=renewal_at,
        renewal_period_days=payload.renewal_period_days,
        provider=payload.provider,
        external_id=payload.external_id,
        note=payload.note,
        actor_user_id=current_user.get("user_id"),
        payload=payload.model_dump(),
    )

    write_audit_log(
        event_type="subscription",
        action="upsert",
        method=request.method,
        path=request.url.path,
        status_code=200,
        user_id=current_user.get("user_id"),
        username=current_user.get("sub"),
        ip_address=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
        details={
            "target_user_id": user_id,
            "tier": subscription.tier,
            "active": subscription.is_active,
            "expires_at": _iso(subscription.expires_at),
        },
    )

    return {
        "status": "success",
        "user": _user_summary(user),
        "subscription": serialize_subscription(subscription),
    }


@router.delete("/{user_id}", summary="Remove subscription record for a user")
def delete_subscription(
    user_id: int,
    request: Request,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    row = db.query(Subscription).filter(Subscription.user_id == int(user_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    db.delete(row)
    db.commit()

    write_audit_log(
        event_type="subscription",
        action="delete",
        method=request.method,
        path=request.url.path,
        status_code=200,
        user_id=current_user.get("user_id"),
        username=current_user.get("sub"),
        ip_address=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
        details={"target_user_id": user_id},
    )

    return {"status": "success", "message": "Subscription deleted"}


@router.get("/{user_id}/history", summary="Subscription change history")
def subscription_history(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SubscriptionHistory)
        .filter(SubscriptionHistory.user_id == int(user_id))
        .order_by(SubscriptionHistory.created_at.desc())
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": row.id,
            "action": row.action,
            "previous_tier": row.previous_tier,
            "new_tier": row.new_tier,
            "previous_status": row.previous_status,
            "new_status": row.new_status,
            "note": row.note,
            "created_at": _iso(row.created_at),
            "created_by": row.created_by,
        }
        for row in rows
    ]
    return {"status": "success", "count": len(items), "history": items}


@router.get("/{user_id}/payments", summary="List subscription payments")
def subscription_payments(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SubscriptionPayment)
        .filter(SubscriptionPayment.user_id == int(user_id))
        .order_by(SubscriptionPayment.created_at.desc())
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": row.id,
            "provider": row.provider,
            "amount": row.amount,
            "currency": row.currency,
            "status": row.status,
            "paid_at": _iso(row.paid_at),
            "reference_id": row.reference_id,
            "note": row.note,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]
    return {"status": "success", "count": len(items), "payments": items}


@router.post("/{user_id}/payments", summary="Add a manual payment entry")
def create_payment(
    user_id: int,
    payload: PaymentCreateRequest,
    request: Request,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    subscription = db.query(Subscription).filter(Subscription.user_id == int(user_id)).first()
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")

    paid_at = _parse_dt(payload.paid_at)
    row = SubscriptionPayment(
        subscription_id=int(subscription.id),
        user_id=int(user_id),
        provider=payload.provider,
        amount=payload.amount,
        currency=payload.currency or "USD",
        status=payload.status,
        paid_at=paid_at,
        reference_id=payload.reference_id,
        note=payload.note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    write_audit_log(
        event_type="subscription",
        action="payment",
        method=request.method,
        path=request.url.path,
        status_code=200,
        user_id=current_user.get("user_id"),
        username=current_user.get("sub"),
        ip_address=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
        details={
            "target_user_id": user_id,
            "amount": payload.amount,
            "currency": payload.currency,
            "status": payload.status,
        },
    )

    return {
        "status": "success",
        "payment": {
            "id": row.id,
            "provider": row.provider,
            "amount": row.amount,
            "currency": row.currency,
            "status": row.status,
            "paid_at": _iso(row.paid_at),
            "reference_id": row.reference_id,
            "note": row.note,
            "created_at": _iso(row.created_at),
        },
    }

