from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from vms.backend.models import Subscription, SubscriptionHistory


SUBSCRIPTION_TIERS: Dict[str, Dict[str, object]] = {
    "free": {
        "label": "Free",
        "allowed_downloads": [],
        "default_period_days": 0,
    },
    "starter": {
        "label": "Starter",
        "allowed_downloads": ["windows"],
        "default_period_days": 30,
    },
    "business": {
        "label": "Business",
        "allowed_downloads": ["windows", "android"],
        "default_period_days": 30,
    },
    "professional": {
        "label": "Professional",
        "allowed_downloads": ["windows", "android"],
        "default_period_days": 30,
    },
    "enterprise": {
        "label": "Enterprise",
        "allowed_downloads": ["windows", "android"],
        "default_period_days": 30,
    },
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_tier(raw: Optional[str]) -> str:
    tier = str(raw or "").strip().lower()
    if not tier:
        return "free"
    if tier in SUBSCRIPTION_TIERS:
        return tier
    return "free"


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.astimezone(timezone.utc).isoformat()


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on", "y"}


def resolve_legacy_subscription(config: Dict[str, object] | None = None) -> Dict[str, object]:
    """Legacy fallback (env/json) for deployments not using DB subscriptions yet."""
    config = config or {}
    active = _parse_bool(config.get("subscription_active"), False)
    tier = normalize_tier(config.get("subscription_tier"))
    expires_at = config.get("subscription_expires_at")

    if active and tier == "free":
        tier = "starter"

    allowed = list(SUBSCRIPTION_TIERS.get(tier, {}).get("allowed_downloads", []))
    if not active:
        allowed = []

    return {
        "active": active,
        "tier": tier,
        "expires_at": expires_at,
        "renewal_at": None,
        "auto_renew": False,
        "allowed_downloads": allowed,
        "source": "legacy",
    }


def serialize_subscription(row: Subscription) -> Dict[str, object]:
    now = _now_utc()
    expires_at = _as_utc(row.expires_at)
    renewal_at = _as_utc(row.next_renewal_at)
    active = bool(row.is_active)
    status = "active" if active else "inactive"
    if active and expires_at and expires_at < now:
        active = False
        status = "expired"

    tier = normalize_tier(row.tier)
    if active and tier == "free":
        tier = "starter"

    allowed = list(SUBSCRIPTION_TIERS.get(tier, {}).get("allowed_downloads", []))
    if not active:
        allowed = []

    days_left = None
    if expires_at:
        delta = expires_at - now
        days_left = max(0, int(delta.total_seconds() // 86400))

    return {
        "active": active,
        "status": status,
        "tier": tier,
        "expires_at": _iso(expires_at),
        "renewal_at": _iso(renewal_at),
        "auto_renew": bool(row.auto_renew),
        "allowed_downloads": allowed,
        "provider": row.provider,
        "external_id": row.external_id,
        "days_left": days_left,
        "source": "db",
    }


def resolve_subscription_for_user(
    db: Optional[Session],
    user_id: Optional[int],
    *,
    legacy_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    if db is None or not user_id:
        return resolve_legacy_subscription(legacy_config)

    row = (
        db.query(Subscription)
        .filter(Subscription.user_id == int(user_id))
        .first()
    )
    if row is None:
        return resolve_legacy_subscription(legacy_config)
    return serialize_subscription(row)


def upsert_subscription(
    db: Session,
    *,
    user_id: int,
    tier: str,
    active: bool,
    expires_at: Optional[datetime],
    auto_renew: bool = False,
    renewal_at: Optional[datetime] = None,
    renewal_period_days: Optional[int] = None,
    provider: Optional[str] = None,
    external_id: Optional[str] = None,
    note: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    payload: Optional[Dict[str, object]] = None,
) -> Subscription:
    now = _now_utc()
    normalized_tier = normalize_tier(tier)
    subscription = db.query(Subscription).filter(Subscription.user_id == int(user_id)).first()

    created = False
    if subscription is None:
        subscription = Subscription(
            user_id=int(user_id),
            starts_at=now,
        )
        created = True

    previous_tier = subscription.tier
    previous_status = "active" if subscription.is_active else "inactive"
    previous_expires_at = _as_utc(subscription.expires_at)
    if previous_expires_at and subscription.is_active and previous_expires_at < now:
        previous_status = "expired"

    subscription.tier = normalized_tier
    subscription.is_active = bool(active)
    subscription.auto_renew = bool(auto_renew)
    subscription.provider = provider
    subscription.external_id = external_id
    subscription.renewal_period_days = (
        int(renewal_period_days)
        if renewal_period_days is not None
        else int(subscription.renewal_period_days or 30)
    )

    if expires_at is None and active:
        default_days = int(SUBSCRIPTION_TIERS.get(normalized_tier, {}).get("default_period_days", 30) or 30)
        expires_at = now + timedelta(days=max(1, default_days))

    subscription.expires_at = _as_utc(expires_at)
    if auto_renew:
        subscription.next_renewal_at = _as_utc(renewal_at or expires_at)
    else:
        subscription.next_renewal_at = _as_utc(renewal_at)

    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    new_status = "active" if subscription.is_active else "inactive"
    current_expires_at = _as_utc(subscription.expires_at)
    if current_expires_at and subscription.is_active and current_expires_at < now:
        new_status = "expired"

    history_action = "created" if created else "updated"
    history = SubscriptionHistory(
        subscription_id=int(subscription.id),
        user_id=int(user_id),
        action=history_action,
        previous_tier=str(previous_tier or ""),
        new_tier=str(subscription.tier or ""),
        previous_status=str(previous_status or ""),
        new_status=str(new_status or ""),
        note=note,
        payload=payload or {},
        created_by=int(actor_user_id) if actor_user_id else None,
    )
    db.add(history)
    db.commit()

    return subscription



TENANT_PLANS: Dict[str, Dict[str, object]] = {
    "starter": {
        "camera_limit": 4,
        "storage_gb": 250,
        "alerts_per_day": 1000,
        "ai_features": ["motion"],
    },
    "professional": {
        "camera_limit": 16,
        "storage_gb": 2000,
        "alerts_per_day": 10000,
        "ai_features": ["motion", "person", "vehicle", "face"],
    },
    "business": {
        "camera_limit": 16,
        "storage_gb": 2000,
        "alerts_per_day": 10000,
        "ai_features": ["motion", "person", "vehicle", "face"],
    },
    "enterprise": {
        "camera_limit": 9999,
        "storage_gb": 10000,
        "alerts_per_day": None,
        "ai_features": ["full"],
        "sla": "99.9%",
        "priority_support": True,
    },
}




def resolve_subscription_for_tenant(
    db: Optional[Session],
    tenant_id: Optional[int],
    *,
    legacy_config: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    if db is None or not tenant_id:
        return resolve_legacy_subscription(legacy_config)

    row = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == int(tenant_id))
        .order_by(Subscription.id.desc())
        .first()
    )
    if row is None:
        return resolve_legacy_subscription(legacy_config)
    return serialize_subscription(row)


def upsert_subscription_for_tenant(
    db: Session,
    *,
    tenant_id: int,
    tier: str,
    active: bool,
    expires_at: Optional[datetime],
    auto_renew: bool = False,
    renewal_at: Optional[datetime] = None,
    renewal_period_days: Optional[int] = None,
    provider: Optional[str] = None,
    external_id: Optional[str] = None,
    note: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    payload: Optional[Dict[str, object]] = None,
) -> Subscription:
    if not tenant_id:
        raise ValueError("tenant_id is required")

    user_id = int(actor_user_id or 0)
    if user_id <= 0:
        raise ValueError("actor_user_id is required to create tenant subscription")

    now = _now_utc()
    normalized_tier = normalize_tier(tier)
    subscription = (
        db.query(Subscription)
        .filter(Subscription.tenant_id == int(tenant_id))
        .order_by(Subscription.id.desc())
        .first()
    )

    created = False
    if subscription is None:
        subscription = Subscription(
            tenant_id=int(tenant_id),
            user_id=int(user_id),
            starts_at=now,
        )
        created = True

    previous_tier = subscription.tier
    previous_status = "active" if subscription.is_active else "inactive"
    previous_expires_at = _as_utc(subscription.expires_at)
    if previous_expires_at and subscription.is_active and previous_expires_at < now:
        previous_status = "expired"

    subscription.tier = normalized_tier
    subscription.is_active = bool(active)
    subscription.auto_renew = bool(auto_renew)
    subscription.provider = provider
    subscription.external_id = external_id
    subscription.renewal_period_days = (
        int(renewal_period_days)
        if renewal_period_days is not None
        else int(subscription.renewal_period_days or 30)
    )

    if expires_at is None and active:
        default_days = int(SUBSCRIPTION_TIERS.get(normalized_tier, {}).get("default_period_days", 30) or 30)
        expires_at = now + timedelta(days=max(1, default_days))

    subscription.expires_at = _as_utc(expires_at)
    if auto_renew:
        subscription.next_renewal_at = _as_utc(renewal_at or expires_at)
    else:
        subscription.next_renewal_at = _as_utc(renewal_at)

    subscription.user_id = int(user_id)
    db.add(subscription)
    db.commit()
    db.refresh(subscription)

    new_status = "active" if subscription.is_active else "inactive"
    current_expires_at = _as_utc(subscription.expires_at)
    if current_expires_at and subscription.is_active and current_expires_at < now:
        new_status = "expired"

    history_action = "created" if created else "updated"
    history = SubscriptionHistory(
        subscription_id=int(subscription.id),
        user_id=int(user_id),
        action=history_action,
        previous_tier=str(previous_tier or ""),
        new_tier=str(subscription.tier or ""),
        previous_status=str(previous_status or ""),
        new_status=str(new_status or ""),
        note=note,
        payload=payload or {},
        created_by=int(actor_user_id) if actor_user_id else None,
    )
    db.add(history)
    db.commit()

    return subscription


def get_tenant_plan_limits(tier: str) -> Dict[str, object]:
    normalized = normalize_tier(tier)
    return dict(TENANT_PLANS.get(normalized, TENANT_PLANS.get("starter", {})))

