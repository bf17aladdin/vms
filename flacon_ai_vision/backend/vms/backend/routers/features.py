from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_user
from vms.backend.services.features_service import build_feature_payload
from vms.backend.services.setup_config_service import get_setup_config_service
from vms.backend.services.subscription_service import resolve_subscription_for_tenant, resolve_subscription_for_user

router = APIRouter(prefix="/api/features", tags=["Features"])


@router.get("", summary="Get feature flags and operation mode")
def get_features(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    config = get_setup_config_service().get_config()
    tenant_id = current_user.get("tenant_id")
    user_id = current_user.get("user_id")

    subscription = resolve_subscription_for_tenant(db, tenant_id, legacy_config=config)
    if subscription.get("source") == "legacy" and user_id:
        subscription = resolve_subscription_for_user(db, user_id, legacy_config=config)

    payload = build_feature_payload(config=config, subscription=subscription)
    return {"success": True, **payload}
