from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import crud, schemas
from ..core.database import get_db
from ..core.media_paths import to_public_media_path
from ..core.security import get_current_admin, get_current_user
from ..models import Camera, Event, SecurityAlert, Site, Zone
from ..services.camera_service import CameraService

router = APIRouter(prefix="/api/sites", tags=["sites"])

VALID_DECISIONS = {"allowed", "denied", "review", "review_required", "manual_override"}


class ZoneBlockRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=255)


class EventDecisionUpdateRequest(BaseModel):
    decision: str = Field(..., min_length=3, max_length=30)


def _require_admin(current_user: dict = Depends(get_current_admin)) -> dict:
    return current_user


def _format_site(site: Site) -> dict:
    return {
        "id": site.id,
        "name": site.name,
        "code": site.code,
        "description": site.description,
        "is_active": bool(site.is_active),
        "created_at": site.created_at.isoformat() if site.created_at else None,
        "updated_at": site.updated_at.isoformat() if site.updated_at else None,
    }


def _format_zone(zone: Zone) -> dict:
    return {
        "id": zone.id,
        "site_id": zone.site_id,
        "camera_id": zone.camera_id,
        "name": zone.name,
        "description": zone.description,
        "zone_type": zone.zone_type or "custom",
        "is_active": bool(zone.is_active),
        "is_blocked": bool(zone.is_blocked),
        "block_reason": zone.block_reason,
        "sensitivity": zone.sensitivity,
        "created_at": zone.created_at.isoformat() if zone.created_at else None,
        "updated_at": zone.updated_at.isoformat() if zone.updated_at else None,
    }


def _format_camera(camera: Camera) -> dict:
    return {
        "id": camera.id,
        "site_id": camera.site_id,
        "zone_id": camera.zone_id,
        "name": camera.name,
        "description": camera.description,
        "camera_type": camera.camera_type or "mix",
        "is_enabled": bool(getattr(camera, "is_enabled", True)),
        "is_active": bool(camera.is_active),
        "connection_status": camera.connection_status,
        "rtsp_url": CameraService._mask_rtsp_url(camera.rtsp_url),
        "ip_address": camera.ip_address,
        "location": camera.location,
        "zone_name": camera.zone_name,
        "latitude": camera.latitude,
        "longitude": camera.longitude,
        "created_at": camera.created_at.isoformat() if camera.created_at else None,
        "updated_at": camera.updated_at.isoformat() if camera.updated_at else None,
    }


def _format_event(event: Event) -> dict:
    return {
        "id": event.id,
        "site_id": event.site_id,
        "zone_id": event.zone_id,
        "camera_id": event.camera_id,
        "event_type": event.event_type,
        "severity": event.severity,
        "decision": event.decision or "review",
        "confidence": event.confidence,
        "description": event.description,
        "detected_objects": event.detected_objects,
        "snapshot_path": to_public_media_path(event.snapshot_path),
        "detected_at": event.detected_at.isoformat() if event.detected_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _format_alert(alert: SecurityAlert) -> dict:
    return {
        "id": alert.id,
        "site_id": alert.site_id,
        "camera_id": alert.camera_id,
        "type": alert.type,
        "severity_level": alert.severity_level,
        "resolution_status": alert.resolution_status,
        "plate_number": alert.plate_number,
        "message": alert.message,
        "timestamp": alert.timestamp.isoformat() if alert.timestamp else None,
        "snapshot_path": to_public_media_path(alert.snapshot_path),
        "details": alert.details,
    }


def _ensure_site(db: Session, site_id: int) -> Site:
    site = crud.get_site_by_id(db, site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.get("", response_model=dict)
def list_sites(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sites = crud.get_all_sites(db, skip=skip, limit=limit)
    return {
        "count": len(sites),
        "sites": [_format_site(site) for site in sites],
        "message": "Sites retrieved successfully",
    }


@router.post("", response_model=dict)
def create_site(
    payload: schemas.SiteCreate,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    try:
        site = crud.create_site(db, payload)
        return {"site": _format_site(site), "message": "Site created successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{site_id}", response_model=dict)
def get_site(
    site_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    site = _ensure_site(db, site_id)
    return {"site": _format_site(site), "message": "Site retrieved successfully"}


@router.put("/{site_id}", response_model=dict)
def update_site(
    site_id: int,
    payload: schemas.SiteUpdate,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    try:
        site = crud.update_site(db, site_id, payload)
        if not site:
            raise HTTPException(status_code=404, detail="Site not found")
        return {"site": _format_site(site), "message": "Site updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{site_id}", response_model=dict)
def delete_site(
    site_id: int,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    if not crud.delete_site(db, site_id):
        raise HTTPException(status_code=404, detail="Site not found")
    return {"site_id": site_id, "message": "Site deleted successfully"}


@router.get("/{site_id}/zones", response_model=dict)
def list_site_zones(
    site_id: int,
    active_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_site(db, site_id)
    zones = crud.get_zones_by_site(db, site_id=site_id, active_only=active_only)
    return {
        "site_id": site_id,
        "count": len(zones),
        "zones": [_format_zone(zone) for zone in zones],
        "message": "Site zones retrieved successfully",
    }


@router.get("/{site_id}/cameras", response_model=dict)
def list_site_cameras(
    site_id: int,
    active_only: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_site(db, site_id)
    cameras = crud.get_cameras_by_site(db, site_id=site_id, active_only=active_only)
    return {
        "site_id": site_id,
        "count": len(cameras),
        "cameras": [_format_camera(camera) for camera in cameras],
        "message": "Site cameras retrieved successfully",
    }


@router.get("/{site_id}/events", response_model=dict)
def list_site_events(
    site_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_site(db, site_id)
    events = crud.get_events_by_site(db, site_id=site_id, skip=skip, limit=limit)
    return {
        "site_id": site_id,
        "count": len(events),
        "events": [_format_event(event) for event in events],
        "message": "Site events retrieved successfully",
    }


@router.get("/{site_id}/alerts", response_model=dict)
def list_site_alerts(
    site_id: int,
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_site(db, site_id)
    query = db.query(SecurityAlert).filter(
        or_(SecurityAlert.site_id == site_id, SecurityAlert.camera.has(Camera.site_id == site_id))
    )
    if status:
        query = query.filter(SecurityAlert.resolution_status == status)
    alerts = query.order_by(SecurityAlert.timestamp.desc()).limit(limit).all()
    return {
        "site_id": site_id,
        "count": len(alerts),
        "alerts": [_format_alert(alert) for alert in alerts],
        "message": "Site alerts retrieved successfully",
    }


@router.get("/{site_id}/stats", response_model=dict)
def get_site_stats(
    site_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_site(db, site_id)
    utc_now = datetime.now(timezone.utc)
    start_today = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)

    zones_total = int(db.query(func.count(Zone.id)).filter(Zone.site_id == site_id).scalar() or 0)
    zones_blocked = int(
        db.query(func.count(Zone.id))
        .filter(Zone.site_id == site_id, Zone.is_blocked == True)
        .scalar()
        or 0
    )
    cameras_total = int(db.query(func.count(Camera.id)).filter(Camera.site_id == site_id).scalar() or 0)
    cameras_enabled = int(
        db.query(func.count(Camera.id))
        .filter(Camera.site_id == site_id, Camera.is_enabled == True)
        .scalar()
        or 0
    )
    cameras_online = int(
        db.query(func.count(Camera.id))
        .filter(Camera.site_id == site_id, Camera.connection_status.in_(["connected", "online"]))
        .scalar()
        or 0
    )
    events_today = int(
        db.query(func.count(Event.id))
        .filter(Event.site_id == site_id, Event.detected_at >= start_today)
        .scalar()
        or 0
    )
    alerts_open = int(
        db.query(func.count(SecurityAlert.id))
        .filter(
            or_(SecurityAlert.site_id == site_id, SecurityAlert.camera.has(Camera.site_id == site_id)),
            SecurityAlert.resolution_status.in_(["open", "in_review"]),
        )
        .scalar()
        or 0
    )

    return {
        "site_id": site_id,
        "timestamp": utc_now.isoformat(),
        "stats": {
            "zones_total": zones_total,
            "zones_blocked": zones_blocked,
            "cameras_total": cameras_total,
            "cameras_enabled": cameras_enabled,
            "cameras_online": cameras_online,
            "events_today": events_today,
            "alerts_open": alerts_open,
        },
    }


@router.post("/zones/{zone_id}/block", response_model=dict)
def block_zone(
    zone_id: int,
    payload: ZoneBlockRequest,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    zone = crud.get_zone_by_id(db, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    zone.is_blocked = True
    zone.block_reason = payload.reason
    db.commit()
    db.refresh(zone)
    return {"zone": _format_zone(zone), "message": "Zone blocked successfully"}


@router.post("/zones/{zone_id}/unblock", response_model=dict)
def unblock_zone(
    zone_id: int,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    zone = crud.get_zone_by_id(db, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    zone.is_blocked = False
    zone.block_reason = None
    db.commit()
    db.refresh(zone)
    return {"zone": _format_zone(zone), "message": "Zone unblocked successfully"}


@router.post("/cameras/{camera_id}/disable", response_model=dict)
def disable_camera(
    camera_id: int,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    camera = crud.get_camera_by_id(db, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    camera.is_enabled = False
    db.commit()
    db.refresh(camera)
    return {"camera": _format_camera(camera), "message": "Camera disabled successfully"}


@router.post("/cameras/{camera_id}/enable", response_model=dict)
def enable_camera(
    camera_id: int,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    camera = crud.get_camera_by_id(db, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    camera.is_enabled = True
    db.commit()
    db.refresh(camera)
    return {"camera": _format_camera(camera), "message": "Camera enabled successfully"}


@router.patch("/events/{event_id}/decision", response_model=dict)
def update_event_decision(
    event_id: int,
    payload: EventDecisionUpdateRequest,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    event = crud.get_event_by_id(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    decision = payload.decision.strip().lower()
    if decision not in VALID_DECISIONS:
        raise HTTPException(status_code=400, detail="Invalid decision")
    event.decision = decision
    db.commit()
    db.refresh(event)
    return {"event": _format_event(event), "message": "Event decision updated successfully"}
