from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..core.database import get_db
from ..core.security import get_current_admin, get_current_user
from ..models import Camera, SecurityRule, Site, Zone

router = APIRouter(prefix="/api/security-config", tags=["security-config"])

RULE_TYPES = {"zone", "line"}
DIRECTION_MODES = {"both", "entry_only", "exit_only"}
SCHEDULE_MODES = {"always", "night_only", "custom_window"}
OBJECT_TYPE_FILTERS = {"person", "vehicle", "both"}


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _require_admin(current_user: dict = Depends(get_current_admin)) -> dict:
    return current_user


def _format_rule(row: SecurityRule) -> dict:
    return {
        "id": row.id,
        "site_id": row.site_id,
        "camera_id": row.camera_id,
        "zone_id": row.zone_id,
        "name": row.name,
        "description": row.description,
        "rule_type": row.rule_type,
        "points": row.points or [],
        "direction_mode": row.direction_mode,
        "schedule_mode": row.schedule_mode,
        "active_from": row.active_from,
        "active_to": row.active_to,
        "sensitivity": row.sensitivity,
        "object_type_filter": row.object_type_filter,
        "is_active": bool(row.is_active),
        "site_name": row.site.name if row.site else None,
        "camera_name": row.camera.name if row.camera else None,
        "zone_name": row.zone.name if row.zone else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _validate_geometry(rule_type: str, points: list[list[float]]) -> None:
    if rule_type == "line" and len(points) < 2:
        raise HTTPException(status_code=400, detail="Line rules require at least 2 points")
    if rule_type == "zone" and len(points) < 3:
        raise HTTPException(status_code=400, detail="Zone rules require at least 3 points")


def _validate_and_resolve_links(
    db: Session,
    *,
    site_id: Optional[int],
    camera_id: Optional[int],
    zone_id: Optional[int],
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    site = None
    camera = None
    zone = None

    if site_id is not None:
        site = db.query(Site).filter(Site.id == site_id).first()
        if site is None:
            raise HTTPException(status_code=404, detail=f"Site {site_id} not found")

    if camera_id is not None:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if camera is None:
            raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    if zone_id is not None:
        zone = db.query(Zone).filter(Zone.id == zone_id).first()
        if zone is None:
            raise HTTPException(status_code=404, detail=f"Zone {zone_id} not found")

    resolved_site_id = site_id
    resolved_camera_id = camera_id

    if camera is not None:
        if site_id is not None and camera.site_id is not None and int(camera.site_id) != int(site_id):
            raise HTTPException(status_code=400, detail="camera.site_id does not match provided site_id")
        if resolved_site_id is None and camera.site_id is not None:
            resolved_site_id = int(camera.site_id)

    if zone is not None:
        if resolved_camera_id is not None and int(zone.camera_id) != int(resolved_camera_id):
            raise HTTPException(status_code=400, detail="zone.camera_id does not match provided camera_id")
        if resolved_camera_id is None:
            resolved_camera_id = int(zone.camera_id)
        if resolved_site_id is not None and zone.site_id is not None and int(zone.site_id) != int(resolved_site_id):
            raise HTTPException(status_code=400, detail="zone.site_id does not match provided site_id")
        if resolved_site_id is None and zone.site_id is not None:
            resolved_site_id = int(zone.site_id)

    return resolved_site_id, resolved_camera_id, zone_id


@router.get("/modules", response_model=dict)
def get_modules_topology(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sites_count = int(db.query(Site).count() or 0)
    cameras_count = int(db.query(Camera).count() or 0)
    zones_count = int(db.query(Zone).count() or 0)
    rules_count = int(db.query(SecurityRule).count() or 0)

    return {
        "separation": {
            "same_backend": True,
            "logical_modules": 3,
            "status": "active",
        },
        "modules": [
            {
                "id": "face_recognition",
                "name": "Backend IA Personne",
                "router_prefix": "/api/face",
                "pipeline": [
                    "camera_frame",
                    "face_detect",
                    "face_align",
                    "face_embed",
                    "db_match",
                    "event_history",
                ],
                "status": "active",
            },
            {
                "id": "vehicle_recognition",
                "name": "Backend IA Vehicule",
                "router_prefix": "/api/vehicle",
                "pipeline": [
                    "vehicle_detect",
                    "plate_crop",
                    "ocr",
                    "plate_normalize",
                    "plate_type_classify",
                    "decision_engine",
                    "event_history",
                ],
                "status": "active",
            },
            {
                "id": "zone_line_security",
                "name": "Backend IA Zone/Ligne",
                "router_prefix": "/api/security-config",
                "pipeline": [
                    "object_track",
                    "trajectory_eval",
                    "zone_or_line_rule",
                    "direction_filter",
                    "schedule_filter",
                    "event_history",
                ],
                "status": "active",
            },
        ],
        "config_options": {
            "rule_types": sorted(RULE_TYPES),
            "direction_modes": sorted(DIRECTION_MODES),
            "schedule_modes": sorted(SCHEDULE_MODES),
            "object_type_filters": sorted(OBJECT_TYPE_FILTERS),
        },
        "inventory": {
            "sites": sites_count,
            "cameras": cameras_count,
            "zones": zones_count,
            "rules": rules_count,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/rules", response_model=dict)
def list_security_rules(
    site_id: Optional[int] = Query(None),
    camera_id: Optional[int] = Query(None),
    zone_id: Optional[int] = Query(None),
    rule_type: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(SecurityRule)
    if site_id is not None:
        query = query.filter(SecurityRule.site_id == site_id)
    if camera_id is not None:
        query = query.filter(SecurityRule.camera_id == camera_id)
    if zone_id is not None:
        query = query.filter(SecurityRule.zone_id == zone_id)
    if rule_type is not None:
        normalized = rule_type.strip().lower()
        if normalized not in RULE_TYPES:
            raise HTTPException(status_code=400, detail="Invalid rule_type")
        query = query.filter(SecurityRule.rule_type == normalized)
    if is_active is not None:
        query = query.filter(SecurityRule.is_active == is_active)

    rows = query.order_by(SecurityRule.id.desc()).offset(skip).limit(limit).all()
    return {
        "count": len(rows),
        "rules": [_format_rule(row) for row in rows],
        "message": "Security rules retrieved successfully",
    }


@router.get("/rules/{rule_id}", response_model=dict)
def get_security_rule(
    rule_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(SecurityRule).filter(SecurityRule.id == rule_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Security rule not found")
    return {"rule": _format_rule(row), "message": "Security rule retrieved successfully"}


@router.post("/rules", response_model=dict)
def create_security_rule(
    payload: schemas.SecurityRuleCreate,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    rule_type = str(_enum_value(payload.rule_type)).lower().strip()
    if rule_type not in RULE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid rule_type")

    direction_mode = str(_enum_value(payload.direction_mode)).lower().strip()
    schedule_mode = str(_enum_value(payload.schedule_mode)).lower().strip()
    object_type_filter = str(_enum_value(payload.object_type_filter)).lower().strip()
    if direction_mode not in DIRECTION_MODES:
        raise HTTPException(status_code=400, detail="Invalid direction_mode")
    if schedule_mode not in SCHEDULE_MODES:
        raise HTTPException(status_code=400, detail="Invalid schedule_mode")
    if object_type_filter not in OBJECT_TYPE_FILTERS:
        raise HTTPException(status_code=400, detail="Invalid object_type_filter")

    points = [[float(p[0]), float(p[1])] for p in (payload.points or [])]
    _validate_geometry(rule_type, points)

    site_id, camera_id, zone_id = _validate_and_resolve_links(
        db,
        site_id=payload.site_id,
        camera_id=payload.camera_id,
        zone_id=payload.zone_id,
    )

    row = SecurityRule(
        site_id=site_id,
        camera_id=camera_id,
        zone_id=zone_id,
        name=payload.name.strip(),
        description=payload.description,
        rule_type=rule_type,
        points=points,
        direction_mode=direction_mode,
        schedule_mode=schedule_mode,
        active_from=payload.active_from,
        active_to=payload.active_to,
        sensitivity=int(payload.sensitivity),
        object_type_filter=object_type_filter,
        is_active=bool(payload.is_active),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"rule": _format_rule(row), "message": "Security rule created successfully"}


@router.put("/rules/{rule_id}", response_model=dict)
def update_security_rule(
    rule_id: int,
    payload: schemas.SecurityRuleUpdate,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(SecurityRule).filter(SecurityRule.id == rule_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Security rule not found")

    update_data = payload.model_dump(exclude_unset=True)

    next_rule_type = str(_enum_value(update_data.get("rule_type", row.rule_type))).lower().strip()
    if next_rule_type not in RULE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid rule_type")

    next_direction_mode = str(_enum_value(update_data.get("direction_mode", row.direction_mode))).lower().strip()
    if next_direction_mode not in DIRECTION_MODES:
        raise HTTPException(status_code=400, detail="Invalid direction_mode")

    next_schedule_mode = str(_enum_value(update_data.get("schedule_mode", row.schedule_mode))).lower().strip()
    if next_schedule_mode not in SCHEDULE_MODES:
        raise HTTPException(status_code=400, detail="Invalid schedule_mode")

    next_object_type_filter = str(
        _enum_value(update_data.get("object_type_filter", row.object_type_filter))
    ).lower().strip()
    if next_object_type_filter not in OBJECT_TYPE_FILTERS:
        raise HTTPException(status_code=400, detail="Invalid object_type_filter")

    next_points = update_data.get("points", row.points or [])
    next_points = [[float(p[0]), float(p[1])] for p in (next_points or [])]
    _validate_geometry(next_rule_type, next_points)

    next_site_id = update_data.get("site_id", row.site_id)
    next_camera_id = update_data.get("camera_id", row.camera_id)
    next_zone_id = update_data.get("zone_id", row.zone_id)
    resolved_site_id, resolved_camera_id, resolved_zone_id = _validate_and_resolve_links(
        db,
        site_id=next_site_id,
        camera_id=next_camera_id,
        zone_id=next_zone_id,
    )

    row.site_id = resolved_site_id
    row.camera_id = resolved_camera_id
    row.zone_id = resolved_zone_id
    row.rule_type = next_rule_type
    row.points = next_points
    row.direction_mode = next_direction_mode
    row.schedule_mode = next_schedule_mode
    row.object_type_filter = next_object_type_filter

    if "name" in update_data and update_data["name"] is not None:
        row.name = str(update_data["name"]).strip()
    if "description" in update_data:
        row.description = update_data["description"]
    if "active_from" in update_data:
        row.active_from = update_data["active_from"]
    if "active_to" in update_data:
        row.active_to = update_data["active_to"]
    if "sensitivity" in update_data and update_data["sensitivity"] is not None:
        row.sensitivity = int(update_data["sensitivity"])
    if "is_active" in update_data and update_data["is_active"] is not None:
        row.is_active = bool(update_data["is_active"])

    db.commit()
    db.refresh(row)
    return {"rule": _format_rule(row), "message": "Security rule updated successfully"}


@router.patch("/rules/{rule_id}/toggle", response_model=dict)
def toggle_security_rule(
    rule_id: int,
    payload: schemas.SecurityRuleToggleRequest,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(SecurityRule).filter(SecurityRule.id == rule_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Security rule not found")
    row.is_active = bool(payload.is_active)
    db.commit()
    db.refresh(row)
    return {"rule": _format_rule(row), "message": "Security rule status updated successfully"}


@router.delete("/rules/{rule_id}", response_model=dict)
def delete_security_rule(
    rule_id: int,
    current_user: dict = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    row = db.query(SecurityRule).filter(SecurityRule.id == rule_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Security rule not found")
    db.delete(row)
    db.commit()
    return {"rule_id": rule_id, "message": "Security rule deleted successfully"}
