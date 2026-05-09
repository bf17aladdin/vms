"""
Vehicle Registry API Router - registre des vehicules autorises
"""

from datetime import datetime
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.media_paths import to_public_media_path
from ..core.security import get_current_user
from ..models import (
    AuditLog,
    SecurityAlert,
    UnknownDetection,
    VehicleAccessLog,
    VehicleEntry,
    VehicleRegistry,
    VehicleRegistryImage,
)
from ..routers.upload import _store_uploaded_photo
from ..schemas import (
    VehicleRegistryCreate,
    VehicleRegistryUpdate,
    VehicleRegistryOut,
    VehicleTypeEnum,
    VehicleStateEnum,
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicle-registry", tags=["vehicle-registry"])

_CREATE_LEGACY_FIELDS = {
    "type_vehicule",
    "marque_modele",
    "immatriculation",
    "etat",
    "proprietaire",
}

_ARABIC_INDIC_DIGITS = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")
_EXT_ARABIC_INDIC_DIGITS = str.maketrans("\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9", "0123456789")
_TUNIS_CITY = "\u062a\u0648\u0646\u0633"
_AI_CHECK_EVENT_TYPE = "vehicle_registry_ai_check"
_AI_CHECK_CRITICAL_FLAGS = {"type_mismatch", "registry_not_found"}
_ALLOWED_VEHICLE_IMAGE_VIEW_LABELS = {"front", "rear", "left", "right", "interior", "detail"}


class VehicleRegistryAiCheckPayload(BaseModel):
    camera_id: Optional[int] = None
    filename: Optional[str] = None
    plate: Optional[str] = None
    plate_type: Optional[str] = None
    flags: List[str] = Field(default_factory=list)
    registry_vehicle_id: Optional[int] = None
    verdict: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class VehicleRegistryAiCreateAlertPayload(BaseModel):
    check_id: Optional[int] = None
    camera_id: Optional[int] = None
    plate: Optional[str] = None
    plate_type: Optional[str] = None
    flags: List[str] = Field(default_factory=list)
    registry_vehicle_id: Optional[int] = None
    verdict: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


def _normalize_categorie(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).lower()
    if raw in {"civile", "civil"}:
        return "civil"
    if raw == "militaire":
        return "militaire"
    return raw


def _normalize_statut(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return str(value).lower()


def _normalize_military_subcategory(value: Optional[str], categorie: Optional[str]) -> Optional[str]:
    if (categorie or "").lower() != "militaire":
        return None
    if value is None:
        return None
    raw = str(value).strip().lower()
    aliases = {
        "operationnel": "operationnel",
        "op\u00e9rationnel": "operationnel",
        "operational": "operationnel",
        "ops": "operationnel",
        "personnel": "personnel",
        "personel": "personnel",
    }
    return aliases.get(raw)


def _normalize_plate_text(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    stage = raw.translate(_ARABIC_INDIC_DIGITS).translate(_EXT_ARABIC_INDIC_DIGITS)
    stage = stage.upper()
    stage = re.sub(r"[^0-9A-Z\u0600-\u06FF]+", " ", stage)
    stage = re.sub(r"\s+", " ", stage).strip()
    return stage


def _choose_code_sequence(first: str, second: str) -> tuple[str, str]:
    if len(first) < len(second):
        return first, second
    if len(second) < len(first):
        return second, first
    try:
        if int(first) <= int(second):
            return first, second
        return second, first
    except Exception:
        return first, second


def _format_tunis_plate(value: Optional[str], categorie: Optional[str]) -> str:
    stage = _normalize_plate_text(value)
    if not stage:
        return ""
    if (categorie or "").lower() != "civil":
        return stage

    digits = re.findall(r"\d+", stage)
    if len(digits) < 2:
        return stage

    code, sequence = _choose_code_sequence(digits[0], digits[1])
    return f"{code} {_TUNIS_CITY} {sequence}"


def _coerce_user_id(current_user: Optional[dict]) -> Optional[int]:
    if not isinstance(current_user, dict):
        return None
    raw = current_user.get("user_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:
        return None


def _coerce_username(current_user: Optional[dict]) -> Optional[str]:
    if not isinstance(current_user, dict):
        return None
    text = str(current_user.get("sub") or current_user.get("username") or "").strip()
    return text or None


def _extract_client_ip(request: Request) -> Optional[str]:
    if request.client and request.client.host:
        return str(request.client.host).strip()[:64] or None
    return None


def _normalize_flag_list(raw_flags: Optional[List[str]]) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for item in raw_flags or []:
        value = str(item or "").strip().lower()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _extract_critical_flags(flags: List[str]) -> List[str]:
    return [flag for flag in flags if flag in _AI_CHECK_CRITICAL_FLAGS]


def _delete_local_file_if_present(path: Optional[str]) -> bool:
    raw = str(path or "").strip()
    if not raw:
        return False
    try:
        image_file = Path(raw)
        if not image_file.is_absolute():
            image_file = (Path.cwd() / image_file).resolve()
        if image_file.exists() and image_file.is_file():
            image_file.unlink(missing_ok=True)
            return True
    except Exception:
        return False
    return False


def _normalize_vehicle_image_view_label(value: Optional[str]) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in _ALLOWED_VEHICLE_IMAGE_VIEW_LABELS else "front"


def _list_vehicle_image_rows(db: Session, vehicle_id: int) -> List[VehicleRegistryImage]:
    return (
        db.query(VehicleRegistryImage)
        .filter(VehicleRegistryImage.vehicle_registry_id == int(vehicle_id))
        .order_by(
            VehicleRegistryImage.is_reference.desc(),
            VehicleRegistryImage.created_at.desc(),
            VehicleRegistryImage.id.desc(),
        )
        .all()
    )


def _serialize_vehicle_image(row: VehicleRegistryImage) -> Dict[str, Any]:
    return {
        "id": row.id,
        "vehicle_registry_id": row.vehicle_registry_id,
        "image_path": row.image_path,
        "image_url": to_public_media_path(row.image_path),
        "view_label": row.view_label or "front",
        "quality_score": float(row.quality_score or 0.0),
        "is_reference": bool(row.is_reference),
        "source": row.source,
        "created_at": row.created_at,
    }


def _sync_vehicle_dataset_with_photo_path(db: Session, vehicle: VehicleRegistry) -> bool:
    rows = _list_vehicle_image_rows(db, vehicle.id)
    current_photo_path = str(vehicle.photo_path or "").strip()
    changed = False

    if current_photo_path:
        matching_row = next((row for row in rows if str(row.image_path or "").strip() == current_photo_path), None)
        if matching_row is None:
            matching_row = VehicleRegistryImage(
                vehicle_registry_id=vehicle.id,
                image_path=current_photo_path,
                view_label="front",
                quality_score=0.0,
                is_reference=True,
                source="legacy_photo_path",
            )
            db.add(matching_row)
            db.flush()
            rows.append(matching_row)
            changed = True

        for row in rows:
            should_be_reference = row.id == matching_row.id
            if bool(row.is_reference) != should_be_reference:
                row.is_reference = should_be_reference
                changed = True

        if str(vehicle.photo_path or "").strip() != current_photo_path:
            vehicle.photo_path = current_photo_path
            changed = True
    elif rows:
        primary_row = next((row for row in rows if row.is_reference), None) or rows[0]
        for row in rows:
            should_be_reference = row.id == primary_row.id
            if bool(row.is_reference) != should_be_reference:
                row.is_reference = should_be_reference
                changed = True

        if str(vehicle.photo_path or "").strip() != str(primary_row.image_path or "").strip():
            vehicle.photo_path = primary_row.image_path
            changed = True
    else:
        if vehicle.photo_path is not None:
            vehicle.photo_path = None
            changed = True

    if changed:
        db.add(vehicle)
        db.flush()
    return changed


def _build_alert_metadata(
    *,
    check_id: Optional[int],
    flags: List[str],
    critical_flags: List[str],
    payload: VehicleRegistryAiCreateAlertPayload,
) -> Dict[str, Any]:
    return {
        "source": "vehicle_registry_ui",
        "check_id": check_id,
        "flags": flags,
        "critical_flags": critical_flags,
        "plate_type": str(payload.plate_type or "").strip().lower() or "unknown",
        "verdict": str(payload.verdict or "").strip().lower() or "review",
        "registry_vehicle_id": payload.registry_vehicle_id,
        "camera_id": payload.camera_id,
        "ai_details": payload.details if isinstance(payload.details, dict) else {},
    }


@router.get("/list", response_model=List[VehicleRegistryOut])
async def list_vehicles(
    db: Session = Depends(get_db),
    type_vehicule: Optional[VehicleTypeEnum] = Query(None),
    etat: Optional[VehicleStateEnum] = Query(None),
    categorie: Optional[str] = Query(None),
    statut: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """Lister les vehicules avec filtres retro-compatibles."""
    try:
        query = db.query(VehicleRegistry)

        resolved_categorie = _normalize_categorie(categorie or (type_vehicule.value if type_vehicule else None))
        resolved_statut = _normalize_statut(statut or (etat.value if etat else None))

        if resolved_categorie:
            query = query.filter(VehicleRegistry.categorie == resolved_categorie)
        if resolved_statut:
            query = query.filter(VehicleRegistry.statut == resolved_statut)

        vehicles = (
            query.order_by(VehicleRegistry.date_enregistrement.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        logger.info("✓ %s vehicules enregistres listes", len(vehicles))
        return vehicles
    except Exception as e:
        logger.error("Erreur listage vehicules: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=List[VehicleRegistryOut])
async def search_vehicles(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_db),
):
    """Recherche par matricule, marque, modele, unite."""
    try:
        query_lower = f"%{q.lower()}%"
        vehicles = db.query(VehicleRegistry).filter(
            VehicleRegistry.matricule.ilike(query_lower)
            | VehicleRegistry.marque.ilike(query_lower)
            | VehicleRegistry.modele.ilike(query_lower)
            | VehicleRegistry.unite.ilike(query_lower)
        ).all()

        logger.info("✓ %s vehicules trouves pour: %s", len(vehicles), q)
        return vehicles
    except Exception as e:
        logger.error("Erreur recherche vehicules: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create", response_model=VehicleRegistryOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    vehicle_data: VehicleRegistryCreate,
    db: Session = Depends(get_db),
):
    """Creer un nouveau vehicule enregistre."""
    try:
        # Drop legacy compatibility fields before ORM construction.
        payload = vehicle_data.model_dump(exclude=_CREATE_LEGACY_FIELDS)
        payload["categorie"] = _normalize_categorie(payload.get("categorie")) or "civil"
        payload["statut"] = _normalize_statut(payload.get("statut")) or "actif"
        payload["matricule"] = _format_tunis_plate(payload.get("matricule"), payload.get("categorie"))
        payload["sous_categorie_militaire"] = _normalize_military_subcategory(
            payload.get("sous_categorie_militaire"),
            payload.get("categorie"),
        )
        normalized_plate = payload["matricule"]

        existing = db.query(VehicleRegistry).filter(
            VehicleRegistry.matricule == normalized_plate
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Matricule '{normalized_plate}' deja enregistre",
            )

        new_vehicle = VehicleRegistry(**payload)
        db.add(new_vehicle)
        db.commit()
        db.refresh(new_vehicle)

        logger.info("✓ Vehicule cree: %s", new_vehicle.matricule)
        return new_vehicle
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur creation vehicule: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{vehicle_id:int}", response_model=VehicleRegistryOut)
async def get_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Vehicule #{vehicle_id} non trouve")
        return vehicle
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Erreur lecture vehicule: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{vehicle_id:int}/images", response_model=dict)
async def list_vehicle_images(
    vehicle_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Vehicule #{vehicle_id} non trouve")

        changed = _sync_vehicle_dataset_with_photo_path(db, vehicle)
        if changed:
            db.commit()
            db.refresh(vehicle)

        items = [_serialize_vehicle_image(row) for row in _list_vehicle_image_rows(db, vehicle_id)]
        return {"success": True, "count": len(items), "items": items}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur listing photos vehicule: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vehicle_id:int}/images", response_model=dict, status_code=status.HTTP_201_CREATED)
async def add_vehicle_image(
    vehicle_id: int,
    view_label: str = Form("front"),
    make_primary: bool = Form(False),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Vehicule #{vehicle_id} non trouve")

        _sync_vehicle_dataset_with_photo_path(db, vehicle)
        existing_rows = _list_vehicle_image_rows(db, vehicle_id)
        image_path = _store_uploaded_photo(file, "vehicle_photos", "vehicle")
        should_be_primary = bool(make_primary) or len(existing_rows) == 0

        if should_be_primary:
            for row in existing_rows:
                row.is_reference = False

        row = VehicleRegistryImage(
            vehicle_registry_id=vehicle.id,
            image_path=image_path,
            view_label=_normalize_vehicle_image_view_label(view_label),
            quality_score=0.0,
            is_reference=should_be_primary,
            source="api_vehicle_dataset",
        )
        db.add(row)
        db.flush()

        if should_be_primary or not str(vehicle.photo_path or "").strip():
            vehicle.photo_path = image_path
            db.add(vehicle)

        db.commit()
        db.refresh(row)
        db.refresh(vehicle)
        return {
            "success": True,
            "message": "Vehicle image added",
            "image": _serialize_vehicle_image(row),
            "vehicle_photo_path": vehicle.photo_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur ajout photo vehicule: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{vehicle_id:int}/images/{image_id:int}/primary", response_model=dict)
async def set_primary_vehicle_image(
    vehicle_id: int,
    image_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Vehicule #{vehicle_id} non trouve")

        _sync_vehicle_dataset_with_photo_path(db, vehicle)
        row = (
            db.query(VehicleRegistryImage)
            .filter(
                VehicleRegistryImage.id == image_id,
                VehicleRegistryImage.vehicle_registry_id == vehicle_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Photo vehicule introuvable")

        (
            db.query(VehicleRegistryImage)
            .filter(VehicleRegistryImage.vehicle_registry_id == vehicle_id)
            .update({VehicleRegistryImage.is_reference: False}, synchronize_session=False)
        )
        row.is_reference = True
        vehicle.photo_path = row.image_path
        db.add(row)
        db.add(vehicle)
        db.commit()
        db.refresh(row)
        db.refresh(vehicle)
        return {
            "success": True,
            "message": "Primary vehicle image updated",
            "image": _serialize_vehicle_image(row),
            "vehicle_photo_path": vehicle.photo_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur definition photo principale vehicule: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{vehicle_id:int}/images/{image_id:int}", response_model=dict)
async def delete_vehicle_image(
    vehicle_id: int,
    image_id: int,
    delete_file: bool = Query(True),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Vehicule #{vehicle_id} non trouve")

        _sync_vehicle_dataset_with_photo_path(db, vehicle)
        row = (
            db.query(VehicleRegistryImage)
            .filter(
                VehicleRegistryImage.id == image_id,
                VehicleRegistryImage.vehicle_registry_id == vehicle_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Photo vehicule introuvable")

        image_path = str(row.image_path or "").strip()
        was_reference = bool(row.is_reference)
        db.delete(row)
        db.flush()

        remaining_rows = _list_vehicle_image_rows(db, vehicle_id)
        if remaining_rows:
            primary_row = next((item for item in remaining_rows if item.is_reference), None)
            if primary_row is None or was_reference:
                primary_row = remaining_rows[0]
                for item in remaining_rows:
                    item.is_reference = item.id == primary_row.id
            vehicle.photo_path = primary_row.image_path
        else:
            vehicle.photo_path = None

        db.add(vehicle)
        db.commit()

        file_deleted = _delete_local_file_if_present(image_path) if delete_file else False
        return {
            "success": True,
            "deleted_image_id": image_id,
            "deleted_file": file_deleted,
            "vehicle_photo_path": vehicle.photo_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur suppression photo vehicule: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{vehicle_id:int}", response_model=VehicleRegistryOut)
async def update_vehicle(
    vehicle_id: int,
    vehicle_data: VehicleRegistryUpdate,
    db: Session = Depends(get_db),
):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Vehicule #{vehicle_id} non trouve")

        update_data = vehicle_data.model_dump(exclude_unset=True)
        if "categorie" in update_data and update_data["categorie"] is not None:
            update_data["categorie"] = _normalize_categorie(update_data["categorie"])
        next_categorie = update_data.get("categorie") or vehicle.categorie
        if "statut" in update_data and update_data["statut"] is not None:
            update_data["statut"] = _normalize_statut(update_data["statut"])
        if "matricule" in update_data and update_data["matricule"] is not None:
            update_data["matricule"] = _format_tunis_plate(update_data["matricule"], next_categorie)
        if "sous_categorie_militaire" in update_data:
            update_data["sous_categorie_militaire"] = _normalize_military_subcategory(
                update_data.get("sous_categorie_militaire"),
                next_categorie,
            )
        elif (next_categorie or "").lower() != "militaire":
            update_data["sous_categorie_militaire"] = None

        for field, value in update_data.items():
            setattr(vehicle, field, value)

        vehicle.date_modification = datetime.utcnow()
        db.add(vehicle)
        db.commit()
        db.refresh(vehicle)
        return vehicle
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur mise a jour vehicule: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{vehicle_id:int}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail=f"Vehicule #{vehicle_id} non trouve")
        matricule = str(vehicle.matricule or f"#{vehicle_id}")
        image_paths_to_delete = {
            str(path).strip()
            for path in [vehicle.photo_path, *[row.image_path for row in list(vehicle.images or [])]]
            if str(path or "").strip()
        }

        detached_entries = (
            db.query(VehicleEntry)
            .filter(VehicleEntry.vehicle_registry_id == int(vehicle_id))
            .update({VehicleEntry.vehicle_registry_id: None}, synchronize_session=False)
        )
        detached_access_logs = (
            db.query(VehicleAccessLog)
            .filter(VehicleAccessLog.registry_vehicle_id == int(vehicle_id))
            .update({VehicleAccessLog.registry_vehicle_id: None}, synchronize_session=False)
        )
        detached_unknown_detections = (
            db.query(UnknownDetection)
            .filter(
                UnknownDetection.resolved_entity_type == "vehicle_registry",
                UnknownDetection.resolved_entity_id == int(vehicle_id),
            )
            .update({UnknownDetection.resolved_entity_id: None}, synchronize_session=False)
        )

        db.delete(vehicle)
        db.commit()
        deleted_photo_count = sum(1 for path in image_paths_to_delete if _delete_local_file_if_present(path))
        logger.info(
            "✓ Vehicule supprime: %s (entries_detachees=%s, access_logs_detaches=%s, unknowns_detaches=%s, photo_supprimee=%s)",
            matricule,
            detached_entries,
            detached_access_logs,
            detached_unknown_detections,
            deleted_photo_count,
        )
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur suppression vehicule: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vehicle_id:int}/flag", response_model=VehicleRegistryOut)
async def flag_vehicle(
    vehicle_id: int,
    reason: str = Query(..., min_length=3),
    db: Session = Depends(get_db),
):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicule non trouve")
        vehicle.is_flagged = True
        vehicle.is_blacklisted = True
        vehicle.is_whitelisted = False
        vehicle.blacklist_reason = reason
        vehicle.flag_reason = reason
        vehicle.date_modification = datetime.utcnow()
        db.add(vehicle)
        db.commit()
        db.refresh(vehicle)
        return vehicle
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{vehicle_id:int}/unflag", response_model=VehicleRegistryOut)
async def unflag_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    try:
        vehicle = db.query(VehicleRegistry).filter(VehicleRegistry.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vehicule non trouve")
        vehicle.is_flagged = False
        vehicle.is_blacklisted = False
        vehicle.blacklist_reason = None
        vehicle.flag_reason = None
        vehicle.date_modification = datetime.utcnow()
        db.add(vehicle)
        db.commit()
        db.refresh(vehicle)
        return vehicle
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats/summary", response_model=dict)
async def get_summary_stats(db: Session = Depends(get_db)):
    """Stats globales du registre."""
    try:
        total = db.query(VehicleRegistry).count()
        militaires = db.query(VehicleRegistry).filter(VehicleRegistry.categorie == "militaire").count()
        civils = db.query(VehicleRegistry).filter(VehicleRegistry.categorie == "civil").count()
        actifs = db.query(VehicleRegistry).filter(VehicleRegistry.statut == "actif").count()
        hors_service = db.query(VehicleRegistry).filter(VehicleRegistry.statut == "hors_service").count()
        maintenance = db.query(VehicleRegistry).filter(VehicleRegistry.statut == "maintenance").count()
        flagged = db.query(VehicleRegistry).filter(VehicleRegistry.is_flagged.is_(True)).count()

        return {
            "total": total,
            "par_type": {"militaire": militaires, "civil": civils},
            "par_etat": {
                "actif": actifs,
                "hors_service": hors_service,
                "maintenance": maintenance,
            },
            "signales": flagged,
        }
    except Exception as e:
        logger.error("Erreur statistiques: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-checks", response_model=dict, status_code=status.HTTP_201_CREATED)
async def persist_ai_registry_check(
    payload: VehicleRegistryAiCheckPayload,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist IA vs registry consistency checks for operator audit/history."""
    try:
        flags = _normalize_flag_list(payload.flags)
        critical_flags = _extract_critical_flags(flags)
        details = {
            "source": "vehicle_registry_ui",
            "camera_id": payload.camera_id,
            "filename": (str(payload.filename or "").strip() or None),
            "plate": (str(payload.plate or "").strip() or None),
            "plate_type": str(payload.plate_type or "").strip().lower() or "unknown",
            "flags": flags,
            "critical_flags": critical_flags,
            "registry_vehicle_id": payload.registry_vehicle_id,
            "verdict": str(payload.verdict or "").strip().lower() or "review",
            "ai_details": payload.details if isinstance(payload.details, dict) else {},
        }
        row = AuditLog(
            user_id=_coerce_user_id(current_user),
            username=_coerce_username(current_user),
            event_type=_AI_CHECK_EVENT_TYPE,
            action="persist_check",
            method="POST",
            path=request.url.path[:255],
            status_code=status.HTTP_201_CREATED,
            ip_address=_extract_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            request_id=(request.headers.get("x-request-id") or "")[:64] or None,
            details=details,
            created_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return {
            "success": True,
            "check_id": row.id,
            "created_at": row.created_at,
            "flags": flags,
            "critical_flags": critical_flags,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur persistance ai-check: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-checks", response_model=dict)
async def list_ai_registry_checks(
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    only_critical: bool = Query(False),
):
    """List recent IA vs registry checks for operator history view."""
    try:
        query = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == _AI_CHECK_EVENT_TYPE, AuditLog.action == "persist_check")
            .order_by(AuditLog.created_at.desc())
        )
        fetch_limit = limit if not only_critical else min(limit * 5, 500)
        rows = query.offset(skip).limit(fetch_limit).all()
        items: List[Dict[str, Any]] = []
        for row in rows:
            details = row.details if isinstance(row.details, dict) else {}
            flags = _normalize_flag_list(details.get("flags") if isinstance(details, dict) else [])
            critical_flags = _extract_critical_flags(flags)
            if only_critical and not critical_flags:
                continue
            items.append(
                {
                    "id": row.id,
                    "created_at": row.created_at,
                    "username": row.username,
                    "camera_id": details.get("camera_id"),
                    "filename": details.get("filename"),
                    "plate": details.get("plate"),
                    "plate_type": details.get("plate_type"),
                    "verdict": details.get("verdict"),
                    "flags": flags,
                    "critical_flags": critical_flags,
                    "registry_vehicle_id": details.get("registry_vehicle_id"),
                    "created_alert_id": details.get("created_alert_id"),
                }
            )
            if len(items) >= limit:
                break
        return {
            "success": True,
            "count": len(items),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Erreur listing ai-checks: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-checks/create-alert", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_ai_registry_alert(
    payload: VehicleRegistryAiCreateAlertPayload,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create security alert when IA/registry critical flags are present."""
    flags = _normalize_flag_list(payload.flags)
    critical_flags = _extract_critical_flags(flags)
    if not critical_flags:
        raise HTTPException(
            status_code=400,
            detail="No critical flags found. Expected one of: type_mismatch, registry_not_found",
        )

    plate_number = str(payload.plate or "").strip() or None
    normalized_plate = _normalize_plate_text(plate_number)
    if not normalized_plate:
        normalized_plate = None

    if "type_mismatch" in critical_flags and "registry_not_found" in critical_flags:
        alert_type = "mismatch"
        message = "Critical IA/registry mismatch: type mismatch and registry_not_found"
    elif "type_mismatch" in critical_flags:
        alert_type = "mismatch"
        message = "Critical IA/registry mismatch: type_mismatch"
    else:
        alert_type = "unknown_plate"
        message = "Critical IA/registry mismatch: registry_not_found"

    try:
        alert_details = _build_alert_metadata(
            check_id=payload.check_id,
            flags=flags,
            critical_flags=critical_flags,
            payload=payload,
        )
        alert = SecurityAlert(
            type=alert_type,
            plate_number=plate_number,
            normalized_plate=normalized_plate,
            camera_id=int(payload.camera_id) if payload.camera_id is not None else None,
            site_id=None,
            gate_id="vehicle_registry_check",
            timestamp=datetime.utcnow(),
            severity_level="critical",
            resolution_status="open",
            message=message,
            event_id=None,
            access_log_id=None,
            snapshot_path=None,
            details=alert_details,
        )
        db.add(alert)
        db.flush()

        if payload.check_id is not None:
            check_row = (
                db.query(AuditLog)
                .filter(
                    AuditLog.id == int(payload.check_id),
                    AuditLog.event_type == _AI_CHECK_EVENT_TYPE,
                    AuditLog.action == "persist_check",
                )
                .first()
            )
            if check_row:
                prior_details = check_row.details if isinstance(check_row.details, dict) else {}
                merged_details = dict(prior_details)
                merged_details["created_alert_id"] = alert.id
                merged_details["alert_type"] = alert_type
                merged_details["alert_created_at"] = datetime.utcnow().isoformat()
                check_row.details = merged_details
                db.add(check_row)

        audit_row = AuditLog(
            user_id=_coerce_user_id(current_user),
            username=_coerce_username(current_user),
            event_type=_AI_CHECK_EVENT_TYPE,
            action="create_alert",
            method="POST",
            path=request.url.path[:255],
            status_code=status.HTTP_201_CREATED,
            ip_address=_extract_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            request_id=(request.headers.get("x-request-id") or "")[:64] or None,
            details={
                "source": "vehicle_registry_ui",
                "check_id": payload.check_id,
                "alert_id": alert.id,
                "flags": flags,
                "critical_flags": critical_flags,
                "alert_type": alert_type,
                "severity_level": "critical",
            },
            created_at=datetime.utcnow(),
        )
        db.add(audit_row)
        db.commit()
        db.refresh(alert)

        return {
            "success": True,
            "alert_id": alert.id,
            "severity_level": alert.severity_level,
            "alert_type": alert.type,
            "critical_flags": critical_flags,
            "message": message,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Erreur creation alerte ai-check: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
