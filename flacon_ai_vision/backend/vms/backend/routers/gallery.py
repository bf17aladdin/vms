from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from vms.backend.core.database import get_db
from vms.backend.core.media_paths import to_public_media_path
from vms.backend.core.security import require_operator, require_viewer
from vms.backend.models import (
    FaceDetection,
    FaceImage,
    Personnel,
    UnknownDetection,
    VehicleEvent,
    VehicleEventFrame,
    VehicleRegistry,
)
from vms.backend.routers import unknown_detections as unknown_router
from vms.backend.services.vehicle_ai.vehicle_search_contract import (
    UNKNOWN_ATTRIBUTE_FILTER,
    normalize_vehicle_body_style_filter,
    normalize_vehicle_color_filter,
    normalize_vehicle_type_filter,
)
from vms.backend.services.vehicle_ai.vehicle_taxonomy import (
    normalize_vehicle_body_style,
    normalize_vehicle_brand,
    normalize_vehicle_color,
    normalize_vehicle_model,
)

router = APIRouter(prefix="/api", tags=["gallery"])
PHOTO_PREVIEW_LIMIT = 8


def _to_media_url(path: Optional[str]) -> Optional[str]:
    return to_public_media_path(path)


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _confidence_badge(value: float) -> str:
    score = float(value or 0.0)
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def _parse_datetime_param(value: Optional[str], field_name: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None

    try:
        parsed_date = date.fromisoformat(text)
        return datetime.combine(parsed_date, time.min)
    except ValueError:
        pass

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name}: {value}") from exc


def _is_recent(value: Optional[datetime], *, hours: int = 24) -> bool:
    if value is None:
        return False
    threshold = datetime.utcnow() - timedelta(hours=max(1, int(hours)))
    try:
        return value >= threshold
    except TypeError:
        try:
            return value.replace(tzinfo=None) >= threshold
        except Exception:
            return False


def _compact_plate(value: Optional[str]) -> str:
    raw = str(value or "").upper()
    return "".join(ch for ch in raw if ch.isalnum())


def _coalesce_text(*values: Optional[str]) -> Optional[str]:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _decode_json_maybe(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            decoded = json.loads(text)
        except Exception:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _apply_unknown_text_filter(query, column):
    normalized = func.trim(func.lower(func.coalesce(column, "")))
    return query.filter(or_(column.is_(None), normalized == "", normalized == "unknown"))


def _event_vehicle_profile(row: VehicleEvent) -> Dict[str, Any]:
    payload = _decode_json_maybe(getattr(row, "pipeline_meta", None))
    profile = payload.get("vehicle_profile")
    if isinstance(profile, dict):
        return profile
    return _decode_json_maybe(profile)


def _event_vehicle_brand(row: VehicleEvent) -> Optional[str]:
    profile = _event_vehicle_profile(row)
    return normalize_vehicle_brand(
        _coalesce_text(
            getattr(row, "brand", None),
            profile.get("brand"),
            profile.get("make"),
        )
    )


def _event_vehicle_model(row: VehicleEvent) -> Optional[str]:
    profile = _event_vehicle_profile(row)
    return normalize_vehicle_model(
        _coalesce_text(
            getattr(row, "model", None),
            profile.get("model"),
        )
    )


def _event_vehicle_color(row: VehicleEvent) -> Optional[str]:
    profile = _event_vehicle_profile(row)
    normalized = normalize_vehicle_color(
        _coalesce_text(
            getattr(row, "dominant_color", None),
            profile.get("dominant_color"),
        )
    )
    return None if normalized == "unknown" else normalized


def _event_vehicle_body_style(row: VehicleEvent) -> Optional[str]:
    profile = _event_vehicle_profile(row)
    return normalize_vehicle_body_style(
        _coalesce_text(
            getattr(row, "body_style", None),
            profile.get("body_style"),
        )
    )


def _apply_face_filters(
    query,
    *,
    camera_id: Optional[int],
    dt_from: Optional[datetime],
    dt_to: Optional[datetime],
    search: Optional[str],
):
    query = query.filter(FaceDetection.personnel_id.isnot(None))
    if camera_id is not None:
        query = query.filter(FaceDetection.camera_id == int(camera_id))
    if dt_from is not None:
        query = query.filter(FaceDetection.detected_at >= dt_from)
    if dt_to is not None:
        query = query.filter(FaceDetection.detected_at <= dt_to)
    if search:
        term = f"%{str(search).strip().lower()}%"
        query = query.join(Personnel, Personnel.id == FaceDetection.personnel_id).filter(
            or_(
                func.lower(Personnel.full_name).like(term),
                func.lower(Personnel.nom).like(term),
                func.lower(Personnel.prenom).like(term),
                func.lower(Personnel.cin).like(term),
                func.lower(Personnel.num_recrutement).like(term),
            )
        )
    return query


def _apply_vehicle_filters(
    query,
    *,
    camera_id: Optional[int],
    dt_from: Optional[datetime],
    dt_to: Optional[datetime],
    search: Optional[str],
    brand: Optional[str],
    model: Optional[str],
    color: Optional[str],
    body_style: Optional[str],
    vehicle_type: Optional[str],
    plate_type: Optional[str],
):
    query = query.filter(VehicleEvent.plate_number.isnot(None), func.length(func.trim(VehicleEvent.plate_number)) > 0)
    if camera_id is not None:
        query = query.filter(VehicleEvent.camera_id == int(camera_id))
    if dt_from is not None:
        query = query.filter(VehicleEvent.timestamp >= dt_from)
    if dt_to is not None:
        query = query.filter(VehicleEvent.timestamp <= dt_to)
    if brand:
        query = query.filter(func.lower(func.coalesce(VehicleEvent.brand, "")).like(f"%{str(brand).strip().lower()}%"))
    if model:
        query = query.filter(func.lower(func.coalesce(VehicleEvent.model, "")).like(f"%{str(model).strip().lower()}%"))
    if color:
        if color == UNKNOWN_ATTRIBUTE_FILTER:
            query = _apply_unknown_text_filter(query, VehicleEvent.dominant_color)
        else:
            query = query.filter(func.lower(func.coalesce(VehicleEvent.dominant_color, "")) == str(color).strip().lower())
    if body_style:
        if body_style == UNKNOWN_ATTRIBUTE_FILTER:
            query = _apply_unknown_text_filter(query, VehicleEvent.body_style)
        else:
            query = query.filter(func.lower(func.coalesce(VehicleEvent.body_style, "")) == str(body_style).strip().lower())
    if vehicle_type:
        if vehicle_type == UNKNOWN_ATTRIBUTE_FILTER:
            query = _apply_unknown_text_filter(query, VehicleEvent.vehicle_type)
        else:
            query = query.filter(func.lower(func.coalesce(VehicleEvent.vehicle_type, "")) == str(vehicle_type).strip().lower())
    if plate_type:
        query = query.filter(func.lower(func.coalesce(VehicleEvent.plate_type, "")) == str(plate_type).strip().lower())
    if search:
        term = f"%{str(search).strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(VehicleEvent.plate_number).like(term),
                func.lower(VehicleEvent.normalized_plate).like(term),
                func.lower(VehicleEvent.vehicle_type).like(term),
                func.lower(func.coalesce(VehicleEvent.brand, "")).like(term),
                func.lower(func.coalesce(VehicleEvent.model, "")).like(term),
                func.lower(func.coalesce(VehicleEvent.dominant_color, "")).like(term),
                func.lower(func.coalesce(VehicleEvent.body_style, "")).like(term),
                func.lower(func.coalesce(VehicleEvent.plate_type, "")).like(term),
                func.lower(VehicleEvent.security_tag).like(term),
            )
        )
    return query


@router.get("/gallery/persons")
def get_gallery_persons(
    q: Optional[str] = Query(None),
    camera_id: Optional[int] = Query(None, ge=1),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    photo_limit: int = Query(PHOTO_PREVIEW_LIMIT, ge=1, le=24),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    del current_user

    dt_from = _parse_datetime_param(date_from, "date_from")
    dt_to = _parse_datetime_param(date_to, "date_to")
    if dt_to is not None and len(str(date_to or "").strip()) == 10:
        dt_to = dt_to + timedelta(days=1)
    if dt_from and dt_to and dt_from > dt_to:
        raise HTTPException(status_code=422, detail="date_from must be <= date_to")

    base = _apply_face_filters(
        db.query(FaceDetection),
        camera_id=camera_id,
        dt_from=dt_from,
        dt_to=dt_to,
        search=q,
    )
    total = int(base.with_entities(func.count(func.distinct(FaceDetection.personnel_id))).scalar() or 0)

    grouped = (
        _apply_face_filters(
            db.query(
                FaceDetection.personnel_id.label("personnel_id"),
                func.count(FaceDetection.id).label("total_detections"),
                func.avg(FaceDetection.confidence).label("avg_confidence"),
                func.max(FaceDetection.detected_at).label("last_detected_at"),
            ),
            camera_id=camera_id,
            dt_from=dt_from,
            dt_to=dt_to,
            search=q,
        )
        .group_by(FaceDetection.personnel_id)
        .order_by(func.max(FaceDetection.detected_at).desc())
        .offset(int(skip))
        .limit(int(limit))
        .all()
    )

    person_ids = [int(row.personnel_id) for row in grouped if row.personnel_id is not None]
    if not person_ids:
        return {"success": True, "total": total, "count": 0, "items": []}

    personnel_rows = db.query(Personnel).filter(Personnel.id.in_(person_ids)).all()
    personnel_map = {int(row.id): row for row in personnel_rows}

    image_count_rows = (
        db.query(FaceImage.personnel_id, func.count(FaceImage.id))
        .filter(FaceImage.personnel_id.in_(person_ids))
        .group_by(FaceImage.personnel_id)
        .all()
    )
    image_counts = {int(row[0]): int(row[1]) for row in image_count_rows}

    detail_rows = _apply_face_filters(
        db.query(FaceDetection).filter(FaceDetection.personnel_id.in_(person_ids)),
        camera_id=camera_id,
        dt_from=dt_from,
        dt_to=dt_to,
        search=None,
    ).order_by(FaceDetection.detected_at.desc()).all()

    detail_map: Dict[int, Dict[str, Any]] = {}
    for row in detail_rows:
        person_id = int(row.personnel_id or 0)
        if person_id <= 0:
            continue
        entry = detail_map.setdefault(
            person_id,
            {
                "camera_ids": set(),
                "latest_image_path": None,
                "latest_confidence": 0.0,
                "recent_photos": [],
            },
        )
        entry["camera_ids"].add(int(row.camera_id))
        if entry["latest_image_path"] is None:
            entry["latest_image_path"] = str(row.image_path or "") or None
            entry["latest_confidence"] = float(row.confidence or 0.0)
        if row.image_path and len(entry["recent_photos"]) < int(photo_limit):
            entry["recent_photos"].append(
                {
                    "detection_id": int(row.id),
                    "image_url": _to_media_url(row.image_path),
                    "detected_at": _to_iso(row.detected_at),
                    "camera_id": int(row.camera_id),
                    "confidence": round(float(row.confidence or 0.0), 4),
                    "track_id": int(row.track_id) if row.track_id is not None else None,
                }
            )

    items: List[Dict[str, Any]] = []
    for row in grouped:
        person_id = int(row.personnel_id or 0)
        if person_id <= 0:
            continue
        person = personnel_map.get(person_id)
        if person is None:
            continue

        details = detail_map.get(person_id, {})
        last_detected = row.last_detected_at
        avg_conf = float(row.avg_confidence or 0.0)
        latest_image = details.get("latest_image_path") or str(person.photo_path or "")
        category = person.categorie.value if hasattr(person.categorie, "value") else person.categorie
        camera_ids = sorted(int(cid) for cid in list(details.get("camera_ids", set())))

        items.append(
            {
                "id": person_id,
                "name": str(person.full_name or f"{person.prenom} {person.nom}").strip(),
                "nom": str(person.nom),
                "prenom": str(person.prenom),
                "cin": str(person.cin),
                "grade": str(person.grade),
                "category": str(category or ""),
                "unit": str(person.unite or ""),
                "is_active": bool(person.is_active),
                "is_blacklisted": bool(person.is_blacklisted),
                "photo_url": _to_media_url(latest_image),
                "total_photos": int(image_counts.get(person_id, 0)),
                "total_detections": int(row.total_detections or 0),
                "last_detected_at": _to_iso(last_detected),
                "cameras_seen": camera_ids,
                "camera_count": len(camera_ids),
                "avg_confidence": round(avg_conf, 4),
                "confidence_badge": _confidence_badge(avg_conf),
                "is_new": _is_recent(last_detected, hours=24),
                "recent_photos": list(details.get("recent_photos", [])),
            }
        )

    return {
        "success": True,
        "total": total,
        "count": len(items),
        "items": items,
    }


@router.get("/gallery/vehicles")
def get_gallery_vehicles(
    q: Optional[str] = Query(None),
    camera_id: Optional[int] = Query(None, ge=1),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    color: Optional[str] = Query(None),
    body_style: Optional[str] = Query(None),
    vehicle_type: Optional[str] = Query(None),
    plate_type: Optional[str] = Query(None, pattern="^(civil|military|unknown)?$"),
    photo_limit: int = Query(PHOTO_PREVIEW_LIMIT, ge=1, le=24),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    del current_user

    dt_from = _parse_datetime_param(date_from, "date_from")
    dt_to = _parse_datetime_param(date_to, "date_to")
    if dt_to is not None and len(str(date_to or "").strip()) == 10:
        dt_to = dt_to + timedelta(days=1)
    if dt_from and dt_to and dt_from > dt_to:
        raise HTTPException(status_code=422, detail="date_from must be <= date_to")

    normalized_brand = normalize_vehicle_brand(brand)
    normalized_model = normalize_vehicle_model(model)
    try:
        normalized_color = normalize_vehicle_color_filter(color)
        normalized_body_style = normalize_vehicle_body_style_filter(body_style)
        normalized_vehicle_type = normalize_vehicle_type_filter(vehicle_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    normalized_plate_type = str(plate_type or "").strip().lower() or None

    plate_expr = func.upper(func.coalesce(VehicleEvent.normalized_plate, VehicleEvent.plate_number))

    grouped_query = (
        _apply_vehicle_filters(
            db.query(
                plate_expr.label("plate_key"),
                func.count(VehicleEvent.id).label("total_detections"),
                func.avg(VehicleEvent.confidence).label("avg_confidence"),
                func.max(VehicleEvent.timestamp).label("last_detected_at"),
            ),
            camera_id=camera_id,
            dt_from=dt_from,
            dt_to=dt_to,
            search=q,
            brand=normalized_brand,
            model=normalized_model,
            color=normalized_color,
            body_style=normalized_body_style,
            vehicle_type=normalized_vehicle_type,
            plate_type=normalized_plate_type,
        )
        .group_by(plate_expr)
        .order_by(func.max(VehicleEvent.timestamp).desc())
    )
    grouped_rows = grouped_query.offset(int(skip)).limit(int(limit)).all()

    total_subquery = grouped_query.with_entities(plate_expr.label("plate_key")).subquery()
    total = int(db.query(func.count()).select_from(total_subquery).scalar() or 0)

    raw_plate_keys = [str(row.plate_key or "").strip().upper() for row in grouped_rows if row.plate_key]
    if not raw_plate_keys:
        return {"success": True, "total": total, "count": 0, "items": []}

    detail_rows = _apply_vehicle_filters(
        db.query(VehicleEvent).filter(plate_expr.in_(raw_plate_keys)),
        camera_id=camera_id,
        dt_from=dt_from,
        dt_to=dt_to,
        search=None,
        brand=normalized_brand,
        model=normalized_model,
        color=normalized_color,
        body_style=normalized_body_style,
        vehicle_type=normalized_vehicle_type,
        plate_type=normalized_plate_type,
    ).order_by(VehicleEvent.timestamp.desc()).all()

    event_ids = [int(row.id) for row in detail_rows if int(getattr(row, "id", 0) or 0) > 0]
    frame_rows = (
        db.query(VehicleEventFrame)
        .filter(VehicleEventFrame.event_id.in_(event_ids))
        .order_by(VehicleEventFrame.event_id.asc(), VehicleEventFrame.timestamp.desc(), VehicleEventFrame.id.desc())
        .all()
        if event_ids
        else []
    )
    frame_stage_priority = {
        "full_frame": 0,
        "plate_crop": 1,
        "tamper": 2,
    }
    frame_path_by_event: Dict[int, Optional[str]] = {}
    frame_priority_by_event: Dict[int, int] = {}
    for frame in frame_rows:
        event_id = int(frame.event_id or 0)
        if event_id <= 0:
            continue
        frame_path = str(frame.frame_path or "").strip()
        if not frame_path:
            continue
        priority = frame_stage_priority.get(str(frame.stage or "").strip().lower(), 99)
        current_priority = frame_priority_by_event.get(event_id)
        if current_priority is None or priority < current_priority:
            frame_priority_by_event[event_id] = priority
            frame_path_by_event[event_id] = frame_path

    detail_map: Dict[str, Dict[str, Any]] = {}
    for row in detail_rows:
        compact_key = _compact_plate(row.normalized_plate or row.plate_number)
        if not compact_key:
            continue
        resolved_snapshot_path = str(row.snapshot_path or "").strip() or frame_path_by_event.get(int(row.id or 0))
        entry = detail_map.setdefault(
            compact_key,
            {
                "camera_ids": set(),
                "latest_snapshot_path": None,
                "latest_confidence": 0.0,
                "latest_plate": None,
                "latest_plate_type": None,
                "latest_vehicle_type": None,
                "latest_body_style": None,
                "latest_color": None,
                "latest_brand": None,
                "latest_model": None,
                "recent_photos": [],
            },
        )
        entry["camera_ids"].add(int(row.camera_id))
        if entry["latest_snapshot_path"] is None:
            entry["latest_snapshot_path"] = resolved_snapshot_path or None
            entry["latest_confidence"] = float(row.confidence or 0.0)
            entry["latest_plate"] = str(row.plate_number or "").strip().upper()
            entry["latest_plate_type"] = str(row.plate_type or "").strip().lower() or None
            entry["latest_vehicle_type"] = str(row.vehicle_type or "").strip().lower() or None
            entry["latest_body_style"] = _event_vehicle_body_style(row)
            entry["latest_color"] = _event_vehicle_color(row)
            entry["latest_brand"] = _event_vehicle_brand(row)
            entry["latest_model"] = _event_vehicle_model(row)
        if len(entry["recent_photos"]) < int(photo_limit):
            entry["recent_photos"].append(
                {
                    "event_id": int(row.id),
                    "image_url": _to_media_url(resolved_snapshot_path),
                    "detected_at": _to_iso(row.timestamp),
                    "camera_id": int(row.camera_id),
                    "confidence": round(float(row.confidence or 0.0), 4),
                    "plate": str(row.plate_number or "").strip().upper(),
                    "plate_type": str(row.plate_type or "").strip().lower(),
                }
            )

    registry_rows = db.query(VehicleRegistry).all()
    registry_by_compact = { _compact_plate(row.matricule): row for row in registry_rows if _compact_plate(row.matricule) }

    items: List[Dict[str, Any]] = []
    for row in grouped_rows:
        raw_key = str(row.plate_key or "").strip().upper()
        compact_key = _compact_plate(raw_key)
        if not compact_key:
            continue

        details = detail_map.get(compact_key, {})
        registry = registry_by_compact.get(compact_key)
        avg_conf = float(row.avg_confidence or 0.0)
        last_detected = row.last_detected_at
        camera_ids = sorted(int(cid) for cid in list(details.get("camera_ids", set())))
        snapshot = str(registry.photo_path or "").strip() if registry is not None else ""
        if not snapshot:
            snapshot = details.get("latest_snapshot_path")

        plate_label = (
            str(registry.matricule).upper()
            if registry is not None
            else str(details.get("latest_plate") or raw_key).upper()
        )

        items.append(
            {
                "plate_key": compact_key,
                "plate": plate_label,
                "vehicle_id": int(registry.id) if registry is not None else None,
                "brand": details.get("latest_brand") or (str(registry.marque) if registry is not None else ""),
                "model": details.get("latest_model") or (str(registry.modele) if registry is not None else ""),
                "color": details.get("latest_color") or (str(registry.couleur or "") if registry is not None else ""),
                "body_style": details.get("latest_body_style") or "",
                "vehicle_type": details.get("latest_vehicle_type") or "",
                "plate_type": str(details.get("latest_plate_type") or ""),
                "category": str(registry.categorie or "") if registry is not None else str(details.get("latest_plate_type") or ""),
                "status": str(registry.statut or "") if registry is not None else "",
                "unit": str(registry.unite or "") if registry is not None else "",
                "photo_url": _to_media_url(snapshot),
                "total_detections": int(row.total_detections or 0),
                "last_detected_at": _to_iso(last_detected),
                "cameras_seen": camera_ids,
                "camera_count": len(camera_ids),
                "avg_confidence": round(avg_conf, 4),
                "confidence_badge": _confidence_badge(avg_conf),
                "is_new": _is_recent(last_detected, hours=24),
                "recent_photos": list(details.get("recent_photos", [])),
            }
        )

    return {
        "success": True,
        "total": total,
        "count": len(items),
        "items": items,
    }


@router.get("/unknown")
def get_unknown_alias(
    detection_type: Optional[str] = Query(None, pattern="^(face|vehicle)?$"),
    status: str = Query("open", pattern="^(open|resolved|ignored|all)$"),
    camera_id: Optional[int] = Query(None, ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    return unknown_router.list_unknown_detections(
        detection_type=detection_type,
        status=status,
        camera_id=camera_id,
        skip=skip,
        limit=limit,
        current_user=current_user,
        db=db,
    )


class ResolvePersonAliasPayload(BaseModel):
    personnel_id: Optional[int] = Field(default=None, ge=1)
    nom: Optional[str] = Field(default=None, min_length=2, max_length=50)
    prenom: Optional[str] = Field(default=None, min_length=2, max_length=50)
    cin: Optional[str] = Field(default=None, min_length=5, max_length=20)
    num_recrutement: Optional[str] = Field(default=None, min_length=5, max_length=20)
    categorie: Optional[str] = Field(default=None, min_length=3, max_length=30)
    grade: Optional[str] = Field(default=None, min_length=2, max_length=50)
    unite: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=100)
    telephone: Optional[str] = Field(default=None, max_length=20)
    notes: Optional[str] = None
    pose_label: str = Field(default="front", min_length=2, max_length=20)
    make_primary: bool = True
    allow_conflict: bool = True


@router.post("/unknown/{unknown_id}/resolve-person")
def resolve_unknown_person_alias(
    unknown_id: int,
    payload: ResolvePersonAliasPayload,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = db.query(UnknownDetection).filter(UnknownDetection.id == int(unknown_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown detection #{unknown_id} not found")
    if str(row.detection_type) != "face":
        raise HTTPException(status_code=400, detail="Unknown detection is not a face")

    if payload.personnel_id is not None:
        return unknown_router.resolve_face_unknown_existing(
            unknown_id=unknown_id,
            payload=unknown_router.ResolveFaceExistingPayload(
                personnel_id=int(payload.personnel_id),
                pose_label=str(payload.pose_label or "front"),
                make_primary=bool(payload.make_primary),
                allow_conflict=bool(payload.allow_conflict),
            ),
            request=request,
            current_user=current_user,
            db=db,
        )

    role = str(current_user.get("role") or "").strip().lower()
    if role not in {"admin", "supervisor"}:
        raise HTTPException(status_code=403, detail="Supervisor role required to create a new personnel")

    required_fields = {
        "nom": payload.nom,
        "prenom": payload.prenom,
        "cin": payload.cin,
        "num_recrutement": payload.num_recrutement,
        "categorie": payload.categorie,
        "grade": payload.grade,
    }
    missing = [name for name, value in required_fields.items() if not str(value or "").strip()]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required fields: {', '.join(missing)}")

    return unknown_router.resolve_face_unknown_new_person(
        unknown_id=unknown_id,
        payload=unknown_router.ResolveFaceNewPayload(
            nom=str(payload.nom).strip(),
            prenom=str(payload.prenom).strip(),
            cin=str(payload.cin).strip(),
            num_recrutement=str(payload.num_recrutement).strip(),
            categorie=str(payload.categorie).strip(),
            grade=str(payload.grade).strip(),
            unite=(payload.unite or "").strip() or None,
            email=(payload.email or "").strip() or None,
            telephone=(payload.telephone or "").strip() or None,
            notes=(payload.notes or "").strip() or None,
            pose_label=str(payload.pose_label or "front").strip(),
            make_primary=bool(payload.make_primary),
            allow_conflict=bool(payload.allow_conflict),
        ),
        request=request,
        current_user=current_user,
        db=db,
    )


@router.post("/unknown/{unknown_id}/resolve-vehicle")
def resolve_unknown_vehicle_alias(
    unknown_id: int,
    payload: unknown_router.ResolveVehiclePayload,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    return unknown_router.resolve_vehicle_unknown(
        unknown_id=unknown_id,
        payload=payload,
        request=request,
        current_user=current_user,
        db=db,
    )
