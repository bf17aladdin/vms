from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Query as SAQuery
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_current_user
from ..models import Camera, Personnel, PersonnelEvent, User, Zone
from ..routers.runtime_guard import ensure_manual_inference_allowed
from ..services.camera_service import CameraService
from ..services.face_ai.face_pipeline import FaceRecognitionPipeline
from ..services.stream_service import StreamService

router = APIRouter(prefix="/api/personnel-entry-exit", tags=["Personnel Entry Exit"])


class ProcessCameraPayload(BaseModel):
    zone_id: Optional[int] = None
    direction: str = Field(default="auto", pattern="^(auto|entry|exit)$")
    persist_face_detection: bool = True
    top_k: int = Field(default=5, ge=1, le=20)


def _parse_iso_or_date(raw: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        if len(value) == 10:
            parsed_day = date.fromisoformat(value)
            if end_of_day:
                return (
                    datetime.combine(parsed_day, datetime.min.time())
                    + timedelta(days=1)
                    - timedelta(microseconds=1)
                )
            return datetime.combine(parsed_day, datetime.min.time())
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format '{value}'. Use YYYY-MM-DD or ISO datetime.",
        ) from exc


def _normalize_direction(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"entry", "in", "entree", "entrée"}:
        return "entry"
    if raw in {"exit", "out", "sortie"}:
        return "exit"
    return "unknown"


def _infer_direction(zone_name: Optional[str], override: str = "auto") -> str:
    norm_override = _normalize_direction(override)
    if norm_override in {"entry", "exit"}:
        return norm_override

    text = str(zone_name or "").strip().lower()
    if any(token in text for token in ("sortie", "exit", "out")):
        return "exit"
    if any(token in text for token in ("entree", "entrée", "entry", "in")):
        return "entry"
    return "entry"


def _inside_personnel_ids(db: Session) -> Set[int]:
    latest_subq = (
        db.query(
            PersonnelEvent.personnel_id.label("personnel_id"),
            func.max(PersonnelEvent.detected_at).label("last_seen"),
        )
        .group_by(PersonnelEvent.personnel_id)
        .subquery()
    )

    rows = (
        db.query(PersonnelEvent.personnel_id, PersonnelEvent.direction)
        .join(
            latest_subq,
            and_(
                PersonnelEvent.personnel_id == latest_subq.c.personnel_id,
                PersonnelEvent.detected_at == latest_subq.c.last_seen,
            ),
        )
        .all()
    )
    return {
        int(personnel_id)
        for personnel_id, direction in rows
        if _normalize_direction(direction) == "entry"
    }


def _build_history_query(
    db: Session,
    *,
    name: Optional[str] = None,
    cin: Optional[str] = None,
    camera_id: Optional[int] = None,
    zone_id: Optional[int] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    currently_inside: Optional[bool] = None,
) -> Tuple[SAQuery, Set[int]]:
    inside_ids = _inside_personnel_ids(db)

    query = (
        db.query(PersonnelEvent, Personnel, Camera, Zone)
        .join(Personnel, PersonnelEvent.personnel_id == Personnel.id)
        .join(Camera, PersonnelEvent.camera_id == Camera.id)
        .outerjoin(Zone, Camera.zone_id == Zone.id)
    )

    name_filter = str(name or "").strip()
    if name_filter:
        ilike = f"%{name_filter}%"
        query = query.filter(
            or_(
                Personnel.nom.ilike(ilike),
                Personnel.prenom.ilike(ilike),
                Personnel.full_name.ilike(ilike),
            )
        )

    cin_filter = str(cin or "").strip()
    if cin_filter:
        query = query.filter(Personnel.cin.ilike(f"%{cin_filter}%"))

    if camera_id is not None:
        query = query.filter(PersonnelEvent.camera_id == camera_id)

    if zone_id is not None:
        query = query.filter(Camera.zone_id == zone_id)

    if date_from is not None:
        query = query.filter(PersonnelEvent.detected_at >= date_from)
    if date_to is not None:
        query = query.filter(PersonnelEvent.detected_at <= date_to)

    if currently_inside is True:
        if inside_ids:
            query = query.filter(PersonnelEvent.personnel_id.in_(inside_ids))
        else:
            query = query.filter(PersonnelEvent.personnel_id == -1)
    elif currently_inside is False and inside_ids:
        query = query.filter(~PersonnelEvent.personnel_id.in_(inside_ids))

    return query, inside_ids


@router.post("/process-camera/{camera_id}", response_model=dict)
def process_camera_for_entry_exit(
    camera_id: int,
    payload: ProcessCameraPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_manual_inference_allowed("personnel_entry_exit.process_camera")
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    effective_zone_id = payload.zone_id if payload.zone_id is not None else camera.zone_id
    zone = db.query(Zone).filter(Zone.id == effective_zone_id).first() if effective_zone_id else None
    zone_name = zone.name if zone else (camera.zone_name or None)
    direction = _infer_direction(zone_name, payload.direction)

    stream_source = CameraService.resolve_camera_stream_source(db, camera_id)
    image_bytes = StreamService.get_camera_thumbnail(camera_id=camera_id, rtsp_url=stream_source)
    if not image_bytes:
        raise HTTPException(status_code=500, detail="Unable to capture frame from camera")

    pipeline = FaceRecognitionPipeline(db)
    recognition = pipeline.recognize_from_bytes(
        image_bytes=image_bytes,
        camera_id=camera_id,
        zone_id=effective_zone_id,
        persist=bool(payload.persist_face_detection),
        top_k=int(payload.top_k),
    )

    if not bool(recognition.get("success")):
        return {
            "success": False,
            "matched": False,
            "direction": direction,
            "camera_id": camera_id,
            "zone_id": effective_zone_id,
            "recognition": recognition,
            "message": str(recognition.get("message") or "Face recognition failed"),
        }

    personnel_id_raw = recognition.get("personnel_id")
    if recognition.get("status") != "matched" or personnel_id_raw is None:
        return {
            "success": True,
            "matched": False,
            "direction": direction,
            "camera_id": camera_id,
            "zone_id": effective_zone_id,
            "recognition": recognition,
            "message": "Unknown face - no personnel event created",
        }

    personnel_id = int(personnel_id_raw)
    personnel = db.query(Personnel).filter(Personnel.id == personnel_id).first()
    if personnel is None:
        raise HTTPException(status_code=404, detail="Matched personnel not found")

    now = datetime.utcnow()
    dedup_seconds = max(0, int(os.getenv("PERSONNEL_EVENT_DEDUP_SECONDS", "10")))
    if dedup_seconds > 0:
        recent = (
            db.query(PersonnelEvent)
            .filter(
                PersonnelEvent.personnel_id == personnel_id,
                PersonnelEvent.camera_id == camera_id,
                PersonnelEvent.direction == direction,
                PersonnelEvent.detected_at >= now - timedelta(seconds=dedup_seconds),
            )
            .order_by(PersonnelEvent.detected_at.desc())
            .first()
        )
        if recent is not None:
            return {
                "success": True,
                "matched": True,
                "deduplicated": True,
                "direction": direction,
                "camera_id": camera_id,
                "zone_id": effective_zone_id,
                "recognition": recognition,
                "personnel_event": {
                    "id": int(recent.id),
                    "personnel_id": int(recent.personnel_id),
                    "personnel_name": personnel.full_name,
                    "cin": personnel.cin,
                    "camera_id": int(recent.camera_id),
                    "zone_id": int(effective_zone_id) if effective_zone_id is not None else None,
                    "zone_name": zone_name,
                    "direction": _normalize_direction(recent.direction),
                    "confidence": float(recent.confidence or 0.0),
                    "detected_at": recent.detected_at.isoformat() if recent.detected_at else None,
                    "currently_inside": int(personnel_id) in _inside_personnel_ids(db),
                },
            }

    event = PersonnelEvent(
        personnel_id=personnel_id,
        camera_id=camera_id,
        direction=direction,
        confidence=float(recognition.get("confidence") or 0.0),
        method="face_ai",
        detected_at=now,
        notes=f"Auto {direction} via camera #{camera_id}",
    )
    db.add(event)

    if direction == "entry":
        personnel.last_entry = now
        personnel.total_entries_today = int(personnel.total_entries_today or 0) + 1
    elif direction == "exit":
        personnel.last_exit = now

    db.add(personnel)
    db.commit()
    db.refresh(event)

    inside_ids = _inside_personnel_ids(db)
    return {
        "success": True,
        "matched": True,
        "deduplicated": False,
        "direction": direction,
        "camera_id": camera_id,
        "zone_id": effective_zone_id,
        "recognition": recognition,
        "personnel_event": {
            "id": int(event.id),
            "personnel_id": int(event.personnel_id),
            "personnel_name": personnel.full_name,
            "cin": personnel.cin,
            "camera_id": int(event.camera_id),
            "camera_name": camera.name,
            "zone_id": int(effective_zone_id) if effective_zone_id is not None else None,
            "zone_name": zone_name,
            "direction": direction,
            "confidence": float(event.confidence or 0.0),
            "detected_at": event.detected_at.isoformat() if event.detected_at else None,
            "currently_inside": personnel_id in inside_ids,
        },
    }


@router.get("/history", response_model=dict)
def get_personnel_entry_exit_history(
    name: Optional[str] = Query(None),
    cin: Optional[str] = Query(None),
    camera_id: Optional[int] = Query(None),
    zone_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD or ISO datetime"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD or ISO datetime"),
    currently_inside: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query, inside_ids = _build_history_query(
        db,
        name=name,
        cin=cin,
        camera_id=camera_id,
        zone_id=zone_id,
        date_from=_parse_iso_or_date(date_from, end_of_day=False),
        date_to=_parse_iso_or_date(date_to, end_of_day=True),
        currently_inside=currently_inside,
    )
    total = int(query.count())
    rows = (
        query.order_by(PersonnelEvent.detected_at.desc())
        .offset(max(0, int(skip)))
        .limit(max(1, int(limit)))
        .all()
    )

    items = []
    for event, personnel, camera, zone in rows:
        category_value = (
            personnel.categorie.value
            if hasattr(personnel.categorie, "value")
            else str(personnel.categorie)
        )
        direction_norm = _normalize_direction(event.direction)
        items.append(
            {
                "id": int(event.id),
                "personnel_id": int(personnel.id),
                "personnel_name": personnel.full_name,
                "nom": personnel.nom,
                "prenom": personnel.prenom,
                "cin": personnel.cin,
                "num_recrutement": personnel.num_recrutement,
                "categorie": category_value,
                "grade": personnel.grade,
                "camera_id": int(camera.id),
                "camera_name": camera.name,
                "zone_id": int(camera.zone_id) if camera.zone_id is not None else None,
                "zone_name": zone.name if zone is not None else camera.zone_name,
                "direction": direction_norm,
                "confidence": float(event.confidence or 0.0),
                "method": event.method,
                "detected_at": event.detected_at.isoformat() if event.detected_at else None,
                "currently_inside": int(personnel.id) in inside_ids,
                "notes": event.notes,
            }
        )

    return {
        "status": "ok",
        "total": total,
        "items": items,
    }


@router.get("/stats/daily", response_model=dict)
def get_personnel_daily_summary(
    target_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    camera_id: Optional[int] = Query(None),
    zone_id: Optional[int] = Query(None),
    currently_inside: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    day = date.today()
    if target_date:
        try:
            day = date.fromisoformat(str(target_date))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="target_date must be YYYY-MM-DD") from exc
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1) - timedelta(microseconds=1)

    query, inside_ids = _build_history_query(
        db,
        camera_id=camera_id,
        zone_id=zone_id,
        date_from=start,
        date_to=end,
        currently_inside=currently_inside,
    )
    rows = query.all()

    entries = 0
    exits = 0
    unique_personnel: Set[int] = set()
    by_category: Dict[str, int] = {}
    for event, personnel, camera, zone in rows:
        direction_norm = _normalize_direction(event.direction)
        if direction_norm == "entry":
            entries += 1
        elif direction_norm == "exit":
            exits += 1
        unique_personnel.add(int(personnel.id))
        category_value = (
            personnel.categorie.value
            if hasattr(personnel.categorie, "value")
            else str(personnel.categorie)
        )
        by_category[category_value] = int(by_category.get(category_value, 0) + 1)

    currently_present = len({pid for pid in unique_personnel if pid in inside_ids})

    return {
        "date": day.isoformat(),
        "total_events": len(rows),
        "entries": entries,
        "exits": exits,
        "unique_personnel": len(unique_personnel),
        "currently_inside": currently_present,
        "by_category": by_category,
    }


@router.get("/export/csv")
def export_personnel_history_csv(
    name: Optional[str] = Query(None),
    cin: Optional[str] = Query(None),
    camera_id: Optional[int] = Query(None),
    zone_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    currently_inside: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query, inside_ids = _build_history_query(
        db,
        name=name,
        cin=cin,
        camera_id=camera_id,
        zone_id=zone_id,
        date_from=_parse_iso_or_date(date_from, end_of_day=False),
        date_to=_parse_iso_or_date(date_to, end_of_day=True),
        currently_inside=currently_inside,
    )
    rows = query.order_by(PersonnelEvent.detected_at.desc()).limit(100000).all()

    fieldnames = [
        "event_id",
        "detected_at",
        "direction",
        "confidence",
        "personnel_id",
        "personnel_name",
        "cin",
        "num_recrutement",
        "categorie",
        "grade",
        "camera_id",
        "camera_name",
        "zone_id",
        "zone_name",
        "currently_inside",
        "notes",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for event, personnel, camera, zone in rows:
        category_value = (
            personnel.categorie.value
            if hasattr(personnel.categorie, "value")
            else str(personnel.categorie)
        )
        writer.writerow(
            {
                "event_id": int(event.id),
                "detected_at": event.detected_at.isoformat() if event.detected_at else None,
                "direction": _normalize_direction(event.direction),
                "confidence": float(event.confidence or 0.0),
                "personnel_id": int(personnel.id),
                "personnel_name": personnel.full_name,
                "cin": personnel.cin,
                "num_recrutement": personnel.num_recrutement,
                "categorie": category_value,
                "grade": personnel.grade,
                "camera_id": int(camera.id),
                "camera_name": camera.name,
                "zone_id": int(camera.zone_id) if camera.zone_id is not None else None,
                "zone_name": zone.name if zone is not None else camera.zone_name,
                "currently_inside": int(personnel.id) in inside_ids,
                "notes": event.notes,
            }
        )

    filename = f"personnel_history_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
