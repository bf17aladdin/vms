from __future__ import annotations

from pathlib import Path
from typing import Dict
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from vms.backend.core.config import settings
from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_user
from vms.backend.services.setup_config_service import get_setup_config_service
from vms.backend.services.subscription_service import resolve_subscription_for_tenant

router = APIRouter(prefix="/api", tags=["downloads"])

DOWNLOAD_CATALOG: Dict[str, Dict[str, object]] = {
    "windows": {
        "label": "Windows Desktop",
        "filename": "falcon-ai-vision-setup.exe",
        "version": "1.0.0",
        "release_date": "2026-03-14",
        "notes": [
            "Dashboard modernise",
            "Alertes IA optimisees",
            "Assistant de configuration",
        ],
        "requires_subscription": True,
        "media_type": "application/octet-stream",
    },
    "android": {
        "label": "Android Mobile",
        "filename": "falcon-ai-vision-mobile.apk",
        "version": "1.0.0-beta",
        "release_date": "2026-03-14",
        "notes": [
            "Alertes temps reel",
            "Suivi des cameras",
            "Mode supervision mobile",
        ],
        "requires_subscription": True,
        "media_type": "application/vnd.android.package-archive",
    },
}


def _download_root() -> Path:
    return Path(settings.FRONTEND_PATH) / "website" / "downloads"


def _resolve_platform(platform: str) -> str:
    slug = str(platform or "").strip().lower()
    aliases = {
        "win": "windows",
        "windows": "windows",
        "exe": "windows",
        "android": "android",
        "apk": "android",
        "mobile": "android",
    }
    return aliases.get(slug, slug)


def _serialize_downloads(subscription: Dict[str, object]) -> list[Dict[str, object]]:
    root = _download_root()
    allowed = set(subscription.get("allowed_downloads") or [])
    items: list[Dict[str, object]] = []
    for key, item in DOWNLOAD_CATALOG.items():
        path = root / str(item.get("filename"))
        exists = path.exists()
        requires_subscription = bool(item.get("requires_subscription", True))
        available = exists
        reason = None

        if requires_subscription:
            if not subscription.get("active"):
                available = False
                reason = "Abonnement requis"
            elif key not in allowed:
                available = False
                reason = "Plan non autorise"

        if not exists:
            available = False
            reason = reason or "Fichier indisponible"

        items.append(
            {
                "key": key,
                "label": item.get("label"),
                "filename": item.get("filename"),
                "version": item.get("version"),
                "release_date": item.get("release_date"),
                "notes": list(item.get("notes") or []),
                "requires_subscription": requires_subscription,
                "available": available,
                "reason": reason,
            }
        )
    return items


def _build_legacy_subscription_config() -> Dict[str, object]:
    config = get_setup_config_service().get_config()
    return {
        "subscription_active": str(os.getenv("SUBSCRIPTION_ACTIVE") or "").strip().lower() in {"1", "true", "yes", "on"}
        if os.getenv("SUBSCRIPTION_ACTIVE") is not None
        else bool(config.get("subscription_active", False)),
        "subscription_tier": str(
            os.getenv("SUBSCRIPTION_TIER") or config.get("subscription_tier") or "free"
        ).strip().lower(),
        "subscription_expires_at": os.getenv("SUBSCRIPTION_EXPIRES_AT")
        or config.get("subscription_expires_at"),
    }


@router.get("/download", summary="Validate download entitlement")
@router.get("/downloads/status", summary="Download catalog and entitlement")
async def get_download_status(
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = current_user.get("tenant_id")
    subscription = resolve_subscription_for_tenant(
        db,
        tenant_id,
        legacy_config=_build_legacy_subscription_config(),
    )
    downloads = _serialize_downloads(subscription)
    return {
        "status": "success",
        "subscription": subscription,
        "downloads": downloads,
    }


@router.get("/downloads/{platform}", summary="Download platform installer")
async def download_file(
    platform: str,
    current_user=Depends(get_current_user),
    db=Depends(get_db),
):
    tenant_id = current_user.get("tenant_id")
    subscription = resolve_subscription_for_tenant(
        db,
        tenant_id,
        legacy_config=_build_legacy_subscription_config(),
    )
    key = _resolve_platform(platform)
    if key not in DOWNLOAD_CATALOG:
        raise HTTPException(status_code=404, detail="Unknown download platform")

    allowed = set(subscription.get("allowed_downloads") or [])
    if DOWNLOAD_CATALOG[key].get("requires_subscription", True):
        if not subscription.get("active"):
            raise HTTPException(status_code=403, detail="Subscription required")
        if key not in allowed:
            raise HTTPException(status_code=403, detail="Plan not authorized for this download")

    root = _download_root()
    path = root / str(DOWNLOAD_CATALOG[key].get("filename"))
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not available")

    return FileResponse(
        path,
        filename=str(DOWNLOAD_CATALOG[key].get("filename")),
        media_type=str(DOWNLOAD_CATALOG[key].get("media_type") or "application/octet-stream"),
    )
