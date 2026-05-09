from __future__ import annotations

from datetime import date, datetime, time, timedelta
import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import func

from vms.backend.core.audit import write_audit_log
from vms.backend.core.database import get_db
from vms.backend.core.media_paths import to_public_media_path
from vms.backend.core.security import require_operator, require_supervisor, require_viewer
from vms.backend.models import (
    FaceDetection,
    Personnel,
    PersonnelCategoryEnum,
    Tenant,
    UnknownDetection,
    User,
    VehicleEvent,
    VehicleRegistry,
)
from vms.backend.services.setup_config_service import get_setup_config_service
from vms.backend.schemas import validate_personnel_grade_for_category
from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline
from vms.backend.routers.ws import broadcast_api_event_sync

router = APIRouter(prefix="/api/unknown-detections", tags=["unknown-detections"])


class IgnoreUnknownPayload(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=255)


class ResolveFaceExistingPayload(BaseModel):
    personnel_id: int = Field(..., ge=1)
    pose_label: str = Field(default="front", min_length=2, max_length=20)
    make_primary: bool = False
    allow_conflict: bool = True


class ResolveFaceNewPayload(BaseModel):
    nom: str = Field(..., min_length=2, max_length=50)
    prenom: str = Field(..., min_length=2, max_length=50)
    cin: Optional[str] = Field(default=None, max_length=20)
    num_recrutement: Optional[str] = Field(default=None, max_length=20)
    categorie: Optional[str] = Field(default=None, min_length=3, max_length=30)
    grade: Optional[str] = Field(default=None, max_length=50)
    unite: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=100)
    telephone: Optional[str] = Field(default=None, max_length=20)
    notes: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None
    pose_label: str = Field(default="front", min_length=2, max_length=20)
    make_primary: bool = True
    allow_conflict: bool = True

    @field_validator("categorie")
    @classmethod
    def normalize_categorie(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text.lower() if text else None


def _resolve_project_type(db: Session, current_user: Dict[str, Any]) -> str:
    tenant_id = current_user.get("tenant_id") or current_user.get("tenant")
    if tenant_id:
        try:
            tenant = db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
            if tenant and getattr(tenant, "project_type", None):
                return str(tenant.project_type)
        except Exception:
            pass
    config = get_setup_config_service().get_config()
    return str(config.get("project_type") or "soc")


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _generate_unique_identifier(db: Session, column, prefix: str) -> str:
    for _ in range(5):
        candidate = f"{prefix}-{uuid.uuid4().hex[:8]}"
        if not db.query(Personnel).filter(column == candidate).first():
            return candidate
    return f"{prefix}-{uuid.uuid4().hex}"


class ResolveVehiclePayload(BaseModel):
    matricule: str = Field(..., min_length=3, max_length=20)
    marque: str = Field(default="UNKNOWN", min_length=2, max_length=50)
    modele: str = Field(default="UNKNOWN", min_length=2, max_length=50)
    couleur: Optional[str] = Field(default=None, max_length=30)
    categorie: str = Field(default="civil", pattern="^(civil|militaire)$")
    unite: Optional[str] = Field(default=None, max_length=100)
    sous_categorie_militaire: Optional[str] = Field(default=None, pattern="^(operationnel|personnel)$")
    statut: str = Field(default="actif", pattern="^(actif|hors_service|maintenance)$")

    @field_validator("matricule")
    @classmethod
    def normalize_plate(cls, value: str) -> str:
        return str(value).strip().upper()


def _coerce_user_id(current_user: Dict[str, Any]) -> Optional[int]:
    raw = current_user.get("user_id")
    if raw is None:
        return None
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        return None
    return uid if uid > 0 else None


def _coerce_username(current_user: Dict[str, Any]) -> Optional[str]:
    text = str(current_user.get("sub") or current_user.get("username") or "").strip()
    return text or None


def _audit_unknown_action(
    *,
    request: Request,
    current_user: Dict[str, Any],
    action: str,
    status_code: int = 200,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    write_audit_log(
        event_type="unknown_detection",
        action=action,
        method=request.method,
        path=request.url.path,
        status_code=int(status_code),
        user_id=_coerce_user_id(current_user),
        username=_coerce_username(current_user),
        ip_address=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
        details=details or {},
    )


def _to_media_url(path: Optional[str]) -> Optional[str]:
    return to_public_media_path(path)


def _resolve_image_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (Path.cwd() / candidate).resolve()


def _read_unknown_image(path: str) -> bytes:
    disk_path = _resolve_image_path(path)
    if not disk_path.exists() or not disk_path.is_file():
        raise HTTPException(status_code=404, detail=f"Unknown image not found: {path}")
    return disk_path.read_bytes()


def _build_face_image_candidates(row: UnknownDetection, detection: Optional[FaceDetection]) -> List[str]:
    candidates: List[str] = []
    primary = str(row.image_path or "").strip()
    if primary:
        candidates.append(primary)

    if detection is not None:
        fallback = str(getattr(detection, "image_path", "") or "").strip()
        if fallback and fallback not in candidates:
            candidates.append(fallback)

    return candidates


def _parse_bbox(value: Any) -> Optional[Tuple[int, int, int, int]]:
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None

    def _num(key: str, fallback: Optional[str] = None) -> Optional[float]:
        candidate = raw.get(key)
        if candidate is None and fallback:
            candidate = raw.get(fallback)
        try:
            return float(candidate)
        except Exception:
            return None

    x = _num("x")
    y = _num("y")
    w = _num("w", "width")
    h = _num("h", "height")
    if x is None or y is None or w is None or h is None:
        return None

    x_i, y_i = int(round(x)), int(round(y))
    w_i, h_i = int(round(w)), int(round(h))
    if w_i <= 2 or h_i <= 2:
        return None
    return x_i, y_i, w_i, h_i


def _crop_image_bytes_by_bbox(image_bytes: bytes, bbox: Tuple[int, int, int, int], *, margin_ratio: float = 0.2) -> Optional[bytes]:
    try:
        from PIL import Image
    except Exception:
        return None

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            frame = img.convert("RGB")
            width, height = frame.size
            x, y, w, h = bbox
            pad_x = max(2, int(w * float(margin_ratio)))
            pad_y = max(2, int(h * float(margin_ratio)))
            left = max(0, x - pad_x)
            top = max(0, y - pad_y)
            right = min(width, x + w + pad_x)
            bottom = min(height, y + h + pad_y)
            if right - left <= 8 or bottom - top <= 8:
                return None
            cropped = frame.crop((left, top, right, bottom))
            out = io.BytesIO()
            cropped.save(out, format="JPEG", quality=95)
            return out.getvalue()
    except Exception:
        return None


def _build_face_enrollment_variants(
    *,
    row: UnknownDetection,
    detection: Optional[FaceDetection],
    image_bytes: bytes,
) -> List[Tuple[str, bytes]]:
    variants: List[Tuple[str, bytes]] = []
    seen_hashes: set[int] = set()

    def _push(label: str, data: Optional[bytes]) -> None:
        if not data:
            return
        digest = hash(data)
        if digest in seen_hashes:
            return
        seen_hashes.add(digest)
        variants.append((label, data))

    row_bbox = _parse_bbox(row.bbox)
    if row_bbox is not None:
        _push("crop_unknown_bbox", _crop_image_bytes_by_bbox(image_bytes, row_bbox))
    if detection is not None:
        det_bbox = _parse_bbox(getattr(detection, "face_bbox", None))
        if det_bbox is not None:
            _push("crop_face_detection_bbox", _crop_image_bytes_by_bbox(image_bytes, det_bbox))
    _push("full", image_bytes)
    return variants


def _to_dict(row: UnknownDetection) -> Dict[str, Any]:
    public_image_path = _to_media_url(str(row.image_path or ""))
    return {
        "id": int(row.id),
        "detection_type": str(row.detection_type),
        "image_path": public_image_path,
        "image_url": public_image_path,
        "image_hash": str(row.image_hash or ""),
        "camera_id": int(row.camera_id),
        "zone_id": int(row.zone_id) if row.zone_id is not None else None,
        "source_table": str(row.source_table or ""),
        "source_detection_id": int(row.source_detection_id) if row.source_detection_id is not None else None,
        "confidence": float(row.confidence or 0.0),
        "bbox": row.bbox,
        "is_resolved": bool(row.is_resolved),
        "is_ignored": bool(row.is_ignored),
        "resolved_label": row.resolved_label,
        "resolved_entity_type": row.resolved_entity_type,
        "resolved_entity_id": row.resolved_entity_id,
        "resolved_by_user_id": row.resolved_by_user_id,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "notes": row.notes,
        "extra_data": row.extra_data,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _emit_unknown_resolved_event(
    *,
    row: UnknownDetection,
    entity: str,
    entity_id: int,
) -> None:
    payload = {
        "entity": str(entity),
        "entity_id": int(entity_id),
        "removed_unknown_id": int(row.id),
        "detection_type": str(row.detection_type),
        "camera_id": int(row.camera_id),
        "zone_id": int(row.zone_id) if row.zone_id is not None else None,
        "resolved_label": str(row.resolved_label or ""),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }
    broadcast_api_event_sync("unknown_resolved", payload)
    broadcast_api_event_sync(
        "gallery_updated",
        {
            "entity": str(entity),
            "entity_id": int(entity_id),
            "reason": "unknown_resolved",
            "removed_unknown_id": int(row.id),
        },
    )


def _get_unknown_or_404(db: Session, unknown_id: int) -> UnknownDetection:
    row = db.query(UnknownDetection).filter(UnknownDetection.id == int(unknown_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown detection #{unknown_id} not found")
    return row


@router.get("/id/{unknown_id}")
def get_unknown_detection(
    unknown_id: int,
    current_user: Dict[str, Any] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    row = _get_unknown_or_404(db, unknown_id)
    return {
        "success": True,
        "item": _to_dict(row),
    }


@router.delete("/id/{unknown_id}")
def delete_unknown_detection(
    unknown_id: int,
    request: Request,
    delete_image: bool = Query(True),
    current_user: Dict[str, Any] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = _get_unknown_or_404(db, unknown_id)
    image_path = str(row.image_path or "").strip()
    snapshot = _to_dict(row)
    db.delete(row)
    db.commit()

    image_deleted = False
    if delete_image and image_path:
        try:
            image_file = _resolve_image_path(image_path)
            if image_file.exists() and image_file.is_file():
                image_file.unlink(missing_ok=True)
                image_deleted = True
        except Exception:
            image_deleted = False

    _audit_unknown_action(
        request=request,
        current_user=current_user,
        action="delete",
        details={
            "unknown_id": int(snapshot.get("id") or unknown_id),
            "detection_type": snapshot.get("detection_type"),
            "camera_id": snapshot.get("camera_id"),
            "delete_image": bool(delete_image),
            "image_deleted": bool(image_deleted),
        },
    )

    return {
        "success": True,
        "message": "Unknown detection deleted",
        "deleted_id": int(unknown_id),
        "image_deleted": bool(image_deleted),
    }


def _action_from_unknown(row: UnknownDetection) -> str:
    if bool(row.is_resolved):
        return "resolved"
    if bool(row.is_ignored):
        return "ignored"
    return "pending"


def _event_timestamp(row: UnknownDetection) -> Optional[datetime]:
    return row.resolved_at or row.created_at


def _parse_date_param(value: Optional[str], field_name: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None

    # YYYY-MM-DD
    try:
        parsed_date = date.fromisoformat(text)
        return datetime.combine(parsed_date, time.min)
    except ValueError:
        pass

    # Full ISO datetime
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {field_name}: {value}") from exc


def _format_timestamp(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _to_history_item(row: UnknownDetection, operator_username: Optional[str], operator_full_name: Optional[str]) -> Dict[str, Any]:
    public_image_path = _to_media_url(str(row.image_path or ""))
    return {
        "id": int(row.id),
        "detection_type": str(row.detection_type),
        "camera_id": int(row.camera_id),
        "zone_id": int(row.zone_id) if row.zone_id is not None else None,
        "confidence": float(row.confidence or 0.0),
        "image_path": public_image_path,
        "image_url": public_image_path,
        "action": _action_from_unknown(row),
        "resolved_label": row.resolved_label,
        "resolved_entity_type": row.resolved_entity_type,
        "resolved_entity_id": row.resolved_entity_id,
        "resolved_by_user_id": row.resolved_by_user_id,
        "resolved_by_username": operator_username,
        "resolved_by_full_name": operator_full_name,
        "created_at": _format_timestamp(row.created_at),
        "resolved_at": _format_timestamp(row.resolved_at),
        "event_at": _format_timestamp(_event_timestamp(row)),
        "notes": row.notes,
    }


@router.get("")
def list_unknown_detections(
    detection_type: Optional[str] = Query(None, pattern="^(face|vehicle)?$"),
    status: str = Query("open", pattern="^(open|resolved|ignored|all)$"),
    camera_id: Optional[int] = Query(None, ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    del current_user
    query = db.query(UnknownDetection)
    if detection_type:
        query = query.filter(UnknownDetection.detection_type == detection_type)
    if camera_id is not None:
        query = query.filter(UnknownDetection.camera_id == int(camera_id))

    if status == "open":
        query = query.filter(
            UnknownDetection.is_resolved.is_(False),
            UnknownDetection.is_ignored.is_(False),
        )
    elif status == "resolved":
        query = query.filter(UnknownDetection.is_resolved.is_(True))
    elif status == "ignored":
        query = query.filter(UnknownDetection.is_ignored.is_(True))

    rows = (
        query.order_by(UnknownDetection.created_at.desc())
        .offset(int(skip))
        .limit(int(limit))
        .all()
    )
    return {
        "success": True,
        "count": len(rows),
        "items": [_to_dict(row) for row in rows],
    }


@router.get("/history")
def list_unknown_resolution_history(
    detection_type: Optional[str] = Query(None, pattern="^(face|vehicle)?$"),
    action: str = Query("all", pattern="^(resolved|ignored|pending|all)$"),
    camera_id: Optional[int] = Query(None, ge=1),
    resolved_by_user_id: Optional[int] = Query(None, ge=1),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: str = Query("event_at", pattern="^(event_at|created_at|resolved_at|confidence|camera_id|id)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    del current_user  # authenticated route; user context currently not required for filtering

    dt_from = _parse_date_param(date_from, "date_from")
    dt_to = _parse_date_param(date_to, "date_to")
    if dt_to is not None and len(str(date_to or "").strip()) == 10:
        dt_to = dt_to + timedelta(days=1)
    if dt_from and dt_to and dt_from > dt_to:
        raise HTTPException(status_code=422, detail="date_from must be <= date_to")

    event_at_expr = func.coalesce(UnknownDetection.resolved_at, UnknownDetection.created_at)
    query = (
        db.query(
            UnknownDetection,
            User.username.label("resolved_by_username"),
            User.full_name.label("resolved_by_full_name"),
        )
        .outerjoin(User, User.id == UnknownDetection.resolved_by_user_id)
    )

    if detection_type:
        query = query.filter(UnknownDetection.detection_type == detection_type)
    if camera_id is not None:
        query = query.filter(UnknownDetection.camera_id == int(camera_id))
    if resolved_by_user_id is not None:
        query = query.filter(UnknownDetection.resolved_by_user_id == int(resolved_by_user_id))

    if action == "resolved":
        query = query.filter(UnknownDetection.is_resolved.is_(True))
    elif action == "ignored":
        query = query.filter(UnknownDetection.is_ignored.is_(True))
    elif action == "pending":
        query = query.filter(
            UnknownDetection.is_resolved.is_(False),
            UnknownDetection.is_ignored.is_(False),
        )

    if dt_from is not None:
        query = query.filter(event_at_expr >= dt_from)
    if dt_to is not None:
        query = query.filter(event_at_expr <= dt_to)

    sort_expr = event_at_expr
    if sort_by == "created_at":
        sort_expr = UnknownDetection.created_at
    elif sort_by == "resolved_at":
        sort_expr = UnknownDetection.resolved_at
    elif sort_by == "confidence":
        sort_expr = UnknownDetection.confidence
    elif sort_by == "camera_id":
        sort_expr = UnknownDetection.camera_id
    elif sort_by == "id":
        sort_expr = UnknownDetection.id

    total = int(query.count())
    order_clause = sort_expr.asc() if sort_order == "asc" else sort_expr.desc()
    rows = (
        query.order_by(order_clause)
        .offset(int(skip))
        .limit(int(limit))
        .all()
    )

    items = [
        _to_history_item(
            row=item[0],
            operator_username=item[1],
            operator_full_name=item[2],
        )
        for item in rows
    ]
    return {
        "success": True,
        "total": total,
        "count": len(items),
        "skip": int(skip),
        "limit": int(limit),
        "sort_by": sort_by,
        "sort_order": sort_order,
        "items": items,
    }


@router.get("/history/export/csv")
def export_unknown_resolution_history_csv(
    request: Request,
    detection_type: Optional[str] = Query(None, pattern="^(face|vehicle)?$"),
    action: str = Query("all", pattern="^(resolved|ignored|pending|all)$"),
    camera_id: Optional[int] = Query(None, ge=1),
    resolved_by_user_id: Optional[int] = Query(None, ge=1),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: str = Query("event_at", pattern="^(event_at|created_at|resolved_at|confidence|camera_id|id)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: Dict[str, Any] = Depends(require_supervisor),
    db: Session = Depends(get_db),
):
    payload = list_unknown_resolution_history(
        detection_type=detection_type,
        action=action,
        camera_id=camera_id,
        resolved_by_user_id=resolved_by_user_id,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=0,
        limit=5000,
        current_user={},
        db=db,
    )
    rows = payload.get("items", [])

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "id",
        "detection_type",
        "action",
        "camera_id",
        "zone_id",
        "confidence",
        "resolved_label",
        "resolved_entity_type",
        "resolved_by_user_id",
        "resolved_by_username",
        "resolved_by_full_name",
        "created_at",
        "resolved_at",
        "event_at",
        "notes",
    ])
    for row in rows:
        writer.writerow([
            row.get("id"),
            row.get("detection_type"),
            row.get("action"),
            row.get("camera_id"),
            row.get("zone_id"),
            row.get("confidence"),
            row.get("resolved_label"),
            row.get("resolved_entity_type"),
            row.get("resolved_by_user_id"),
            row.get("resolved_by_username"),
            row.get("resolved_by_full_name"),
            row.get("created_at"),
            row.get("resolved_at"),
            row.get("event_at"),
            row.get("notes"),
        ])

    _audit_unknown_action(
        request=request,
        current_user=current_user,
        action="history_export_csv",
        details={
            "rows_exported": len(rows),
            "filters": {
                "detection_type": detection_type,
                "action": action,
                "camera_id": camera_id,
                "resolved_by_user_id": resolved_by_user_id,
                "date_from": date_from,
                "date_to": date_to,
                "sort_by": sort_by,
                "sort_order": sort_order,
            },
        },
    )

    filename = f"unknown_resolution_history_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{unknown_id}/ignore")
def ignore_unknown_detection(
    unknown_id: int,
    payload: IgnoreUnknownPayload,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = _get_unknown_or_404(db, unknown_id)
    previous_action = _action_from_unknown(row)
    user_id = _coerce_user_id(current_user)

    row.is_ignored = True
    row.is_resolved = False
    row.resolved_by_user_id = user_id
    row.resolved_at = datetime.utcnow()
    if payload.reason:
        row.notes = str(payload.reason)
    db.add(row)
    db.commit()
    db.refresh(row)

    _audit_unknown_action(
        request=request,
        current_user=current_user,
        action="ignore",
        details={
            "unknown_id": int(row.id),
            "detection_type": str(row.detection_type),
            "camera_id": int(row.camera_id),
            "confidence": float(row.confidence or 0.0),
            "previous_action": previous_action,
            "new_action": _action_from_unknown(row),
            "reason": payload.reason,
        },
    )

    return {
        "success": True,
        "message": "Unknown detection ignored",
        "item": _to_dict(row),
    }


@router.post("/{unknown_id}/resolve/face-existing")
def resolve_face_unknown_existing(
    unknown_id: int,
    payload: ResolveFaceExistingPayload,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = _get_unknown_or_404(db, unknown_id)
    if row.detection_type != "face":
        raise HTTPException(status_code=400, detail="Unknown detection is not a face")
    if row.is_ignored:
        raise HTTPException(status_code=400, detail="Ignored unknown detection cannot be resolved")
    if row.is_resolved:
        return {"success": True, "message": "Already resolved", "item": _to_dict(row)}

    person = db.query(Personnel).filter(Personnel.id == int(payload.personnel_id)).first()
    if person is None:
        raise HTTPException(status_code=404, detail=f"Personnel #{payload.personnel_id} not found")

    detection: Optional[FaceDetection] = None
    if str(row.source_table or "") == "face_detections" and row.source_detection_id is not None:
        detection = (
            db.query(FaceDetection)
            .filter(FaceDetection.id == int(row.source_detection_id))
            .first()
        )

    pipeline = FaceRecognitionPipeline(db)
    image_candidates = _build_face_image_candidates(row, detection)
    enroll_result: Dict[str, Any] = {"success": False, "message": "Enrollment failed"}
    last_error_message = "Enrollment failed"
    attempted_sources = 0

    for idx, image_path in enumerate(image_candidates):
        image_bytes = _read_unknown_image(image_path)
        for variant_label, variant_bytes in _build_face_enrollment_variants(
            row=row,
            detection=detection,
            image_bytes=image_bytes,
        ):
            attempted_sources += 1
            enroll_result = pipeline.enroll_from_bytes(
                personnel_id=int(person.id),
                image_bytes=variant_bytes,
                pose_label=str(payload.pose_label or "front").strip().lower() or "front",
                source="unknown_resolution_existing",
                make_primary=bool(payload.make_primary),
                allow_conflict=bool(payload.allow_conflict),
                original_filename=f"unknown_face_{row.id}_src{idx+1}_{variant_label}.jpg",
            )
            if bool(enroll_result.get("success")):
                break
            last_error_message = str(enroll_result.get("message", "Enrollment failed"))
        if bool(enroll_result.get("success")):
            break

    if not bool(enroll_result.get("success")):
        raise HTTPException(
            status_code=400,
            detail=f"{last_error_message} (sources tried: {max(1, attempted_sources)})",
        )

    if detection is not None:
        detection.personnel_id = int(person.id)
        detection.is_blacklisted = bool(person.is_blacklisted)
        detection.is_authorized = bool(person.is_active and not person.is_blacklisted)
        detection.notes = (
            f"{detection.notes or ''} | Resolved from unknown #{row.id} as personnel #{person.id}"
        ).strip(" |")
        db.add(detection)

    user_id = _coerce_user_id(current_user)
    row.is_resolved = True
    row.is_ignored = False
    row.resolved_label = str(person.full_name)
    row.resolved_entity_type = "personnel"
    row.resolved_entity_id = int(person.id)
    row.resolved_by_user_id = user_id
    row.resolved_at = datetime.utcnow()
    row.notes = "Resolved by linking to existing personnel"
    db.add(row)
    db.commit()
    db.refresh(row)

    _audit_unknown_action(
        request=request,
        current_user=current_user,
        action="resolve_face_existing",
        details={
            "unknown_id": int(row.id),
            "personnel_id": int(person.id),
            "personnel_name": str(person.full_name),
            "camera_id": int(row.camera_id),
            "confidence": float(row.confidence or 0.0),
            "source_detection_id": int(row.source_detection_id) if row.source_detection_id is not None else None,
        },
    )
    _emit_unknown_resolved_event(row=row, entity="person", entity_id=int(person.id))

    return {
        "success": True,
        "message": "Unknown face resolved with existing personnel",
        "enrollment": enroll_result,
        "item": _to_dict(row),
    }


@router.post("/{unknown_id}/resolve/face-new")
def resolve_face_unknown_new_person(
    unknown_id: int,
    payload: ResolveFaceNewPayload,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_supervisor),
    db: Session = Depends(get_db),
):
    row = _get_unknown_or_404(db, unknown_id)
    if row.detection_type != "face":
        raise HTTPException(status_code=400, detail="Unknown detection is not a face")
    if row.is_ignored:
        raise HTTPException(status_code=400, detail="Ignored unknown detection cannot be resolved")
    if row.is_resolved:
        return {"success": True, "message": "Already resolved", "item": _to_dict(row)}

    project_type = _resolve_project_type(db, current_user)
    cin_value = _normalize_optional_text(payload.cin)
    recruit_value = _normalize_optional_text(payload.num_recrutement)
    category = _normalize_optional_text(payload.categorie) or "civil"
    grade_value = _normalize_optional_text(payload.grade)

    if project_type == "soc":
        missing = []
        if not cin_value:
            missing.append("cin")
        if not recruit_value:
            missing.append("num_recrutement")
        if not payload.categorie:
            missing.append("categorie")
        if not grade_value:
            missing.append("grade")
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required fields: {', '.join(missing)}",
            )

    try:
        validate_personnel_grade_for_category(category, grade_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if cin_value:
        existing_cin = db.query(Personnel).filter(Personnel.cin == cin_value).first()
        if existing_cin is not None:
            raise HTTPException(status_code=409, detail=f"Identifiant '{cin_value}' deja enregistre")

    if recruit_value:
        existing_recruit = (
            db.query(Personnel)
            .filter(Personnel.num_recrutement == recruit_value)
            .first()
        )
        if existing_recruit is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Reference '{recruit_value}' deja enregistree",
            )

    if not cin_value:
        cin_value = _generate_unique_identifier(db, Personnel.cin, "ID")
    if not recruit_value:
        recruit_value = _generate_unique_identifier(db, Personnel.num_recrutement, "REF")
    if not grade_value:
        grade_value = "Unassigned"

    try:
        normalized_category = PersonnelCategoryEnum(category)
    except ValueError as exc:
        if project_type == "soc":
            raise HTTPException(status_code=422, detail=f"Categorie invalide: {category}") from exc
        normalized_category = PersonnelCategoryEnum.CIVIL
    person = Personnel(
        nom=payload.nom.strip(),
        prenom=payload.prenom.strip(),
        full_name=f"{payload.prenom.strip()} {payload.nom.strip()}",
        cin=cin_value,
        num_recrutement=recruit_value,
        categorie=normalized_category,
        grade=grade_value,
        unite=(payload.unite or "").strip() or None,
        email=(payload.email or "").strip() or None,
        telephone=(payload.telephone or "").strip() or None,
        notes=(payload.notes or "").strip() or None,
        custom_fields=payload.custom_fields,
        is_active=True,
    )
    db.add(person)
    db.flush()

    detection: Optional[FaceDetection] = None
    if str(row.source_table or "") == "face_detections" and row.source_detection_id is not None:
        detection = (
            db.query(FaceDetection)
            .filter(FaceDetection.id == int(row.source_detection_id))
            .first()
        )

    pipeline = FaceRecognitionPipeline(db)
    image_candidates = _build_face_image_candidates(row, detection)
    enroll_result: Dict[str, Any] = {"success": False, "message": "Enrollment failed"}
    last_error_message = "Enrollment failed"
    attempted_sources = 0

    for idx, image_path in enumerate(image_candidates):
        image_bytes = _read_unknown_image(image_path)
        for variant_label, variant_bytes in _build_face_enrollment_variants(
            row=row,
            detection=detection,
            image_bytes=image_bytes,
        ):
            attempted_sources += 1
            enroll_result = pipeline.enroll_from_bytes(
                personnel_id=int(person.id),
                image_bytes=variant_bytes,
                pose_label=str(payload.pose_label or "front").strip().lower() or "front",
                source="unknown_resolution_new_person",
                make_primary=bool(payload.make_primary),
                allow_conflict=bool(payload.allow_conflict),
                original_filename=f"unknown_face_{row.id}_src{idx+1}_{variant_label}.jpg",
            )
            if bool(enroll_result.get("success")):
                break
            last_error_message = str(enroll_result.get("message", "Enrollment failed"))
        if bool(enroll_result.get("success")):
            break

    if not bool(enroll_result.get("success")):
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"{last_error_message} (sources tried: {max(1, attempted_sources)})",
        )

    if detection is not None:
        detection.personnel_id = int(person.id)
        detection.is_blacklisted = bool(person.is_blacklisted)
        detection.is_authorized = bool(person.is_active and not person.is_blacklisted)
        detection.notes = (
            f"{detection.notes or ''} | Resolved from unknown #{row.id} as new personnel #{person.id}"
        ).strip(" |")
        db.add(detection)

    user_id = _coerce_user_id(current_user)
    row.is_resolved = True
    row.is_ignored = False
    row.resolved_label = str(person.full_name)
    row.resolved_entity_type = "personnel"
    row.resolved_entity_id = int(person.id)
    row.resolved_by_user_id = user_id
    row.resolved_at = datetime.utcnow()
    row.notes = "Resolved by creating new personnel"
    db.add(row)
    db.commit()
    db.refresh(row)

    _audit_unknown_action(
        request=request,
        current_user=current_user,
        action="resolve_face_new_person",
        details={
            "unknown_id": int(row.id),
            "personnel_id": int(person.id),
            "personnel_name": str(person.full_name),
            "personnel_categorie": str(person.categorie.value if hasattr(person.categorie, "value") else person.categorie),
            "camera_id": int(row.camera_id),
            "confidence": float(row.confidence or 0.0),
            "source_detection_id": int(row.source_detection_id) if row.source_detection_id is not None else None,
        },
    )
    _emit_unknown_resolved_event(row=row, entity="person", entity_id=int(person.id))

    return {
        "success": True,
        "message": "Unknown face resolved by creating new personnel",
        "personnel_id": int(person.id),
        "enrollment": enroll_result,
        "item": _to_dict(row),
    }


@router.post("/{unknown_id}/resolve/vehicle")
def resolve_vehicle_unknown(
    unknown_id: int,
    payload: ResolveVehiclePayload,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    row = _get_unknown_or_404(db, unknown_id)
    if row.detection_type != "vehicle":
        raise HTTPException(status_code=400, detail="Unknown detection is not a vehicle")
    if row.is_ignored:
        raise HTTPException(status_code=400, detail="Ignored unknown detection cannot be resolved")
    if row.is_resolved:
        return {"success": True, "message": "Already resolved", "item": _to_dict(row)}

    plate = payload.matricule.strip().upper()
    registry = db.query(VehicleRegistry).filter(VehicleRegistry.matricule == plate).first()
    if registry is None:
        registry = VehicleRegistry(
            matricule=plate,
            marque=payload.marque.strip(),
            modele=payload.modele.strip(),
            couleur=(payload.couleur or "").strip() or None,
            categorie=payload.categorie,
            unite=(payload.unite or "").strip() or None,
            sous_categorie_militaire=payload.sous_categorie_militaire,
            statut=payload.statut,
        )
        db.add(registry)
        db.flush()
    else:
        registry.marque = payload.marque.strip() or registry.marque
        registry.modele = payload.modele.strip() or registry.modele
        registry.couleur = (payload.couleur or "").strip() or registry.couleur
        registry.categorie = payload.categorie
        registry.unite = (payload.unite or "").strip() or None
        registry.sous_categorie_militaire = payload.sous_categorie_militaire
        registry.statut = payload.statut
        registry.date_modification = datetime.utcnow()
        db.add(registry)

    if str(row.source_table or "") == "vehicle_events" and row.source_detection_id is not None:
        event = (
            db.query(VehicleEvent)
            .filter(VehicleEvent.id == int(row.source_detection_id))
            .first()
        )
        if event is not None:
            event.plate_number = plate
            event.normalized_plate = plate
            event.plate_type = "military" if payload.categorie == "militaire" else "civil"
            event.matched_registry = True
            db.add(event)

    user_id = _coerce_user_id(current_user)
    row.is_resolved = True
    row.is_ignored = False
    row.resolved_label = plate
    row.resolved_entity_type = "vehicle_registry"
    row.resolved_entity_id = int(registry.id)
    row.resolved_by_user_id = user_id
    row.resolved_at = datetime.utcnow()
    row.notes = "Resolved by vehicle registry mapping"
    db.add(row)
    db.commit()
    db.refresh(row)

    _audit_unknown_action(
        request=request,
        current_user=current_user,
        action="resolve_vehicle",
        details={
            "unknown_id": int(row.id),
            "vehicle_registry_id": int(registry.id),
            "matricule": plate,
            "categorie": payload.categorie,
            "camera_id": int(row.camera_id),
            "confidence": float(row.confidence or 0.0),
            "source_detection_id": int(row.source_detection_id) if row.source_detection_id is not None else None,
        },
    )
    _emit_unknown_resolved_event(row=row, entity="vehicle", entity_id=int(registry.id))

    return {
        "success": True,
        "message": "Unknown vehicle resolved",
        "vehicle_registry_id": int(registry.id),
        "item": _to_dict(row),
    }
