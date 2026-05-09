"""
Router intégré pour les services AI
Connecte le pipeline visage, les services vehicle/zone et les endpoints REST
"""
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Query, Form, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, cast
from datetime import datetime, timedelta
from pathlib import Path
import logging
import base64
import json

from vms.backend.core.database import get_db
from vms.backend.core.realtime_manager import get_realtime_manager
from vms.backend.core.security import authenticate_websocket, require_operator, require_viewer
from vms.backend.routers.runtime_guard import ensure_manual_inference_allowed
from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline
from vms.backend.services.multi_cam_stream_hub import (
    MultiCamStreamParams,
    get_multi_cam_monitor_stream_hub,
)
from vms.backend.services.person_appearance import (
    normalize_color,
    parse_accessory_filter,
)
from vms.backend.services.vehicle_service import VehicleService
from vms.backend.services.zone_service import ZoneService
from vms.backend.services.logging_service import SystemLogger, ErrorHandler
from vms.backend.models import (
    FaceDetection,
    SecurityAlert,
    UnknownDetection,
    VehicleAccessLog,
    VehicleEvent,
    VehicleEventFrame,
)

logger = logging.getLogger("falcon_ai_vision.ai_router")

router = APIRouter(prefix="/api/ai", tags=["AI Services"])

RawDetection = dict[str, object]


def _to_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _to_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _to_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _decode_base64_image(image_base64: str) -> bytes:
    payload = image_base64
    if "," in image_base64 and "base64" in image_base64.split(",", 1)[0]:
        payload = image_base64.split(",", 1)[1]
    return base64.b64decode(payload)


def _to_unix_ts(value: object) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _normalize_face_detection(raw: RawDetection) -> RawDetection:
    timestamp = raw.get("timestamp") or raw.get("detected_at")
    return {
        "id": _to_int(raw.get("id") or raw.get("detection_id"), 0),
        "camera_id": _to_int(raw.get("camera_id"), 0),
        "zone_id": raw.get("zone_id"),
        "type": "face",
        "source": "face",
        "label": _to_str(raw.get("label") or raw.get("personnel_name") or raw.get("name"), "UNKNOWN"),
        "confidence": _to_float(raw.get("confidence"), 0.0),
        "status": _to_str(raw.get("status"), "matched" if raw.get("personnel_id") else "unknown"),
        "timestamp": timestamp,
        "image_url": raw.get("image_url"),
        "data": raw,
    }


def _normalize_vehicle_detection(raw: RawDetection) -> RawDetection:
    timestamp = raw.get("timestamp") or raw.get("detected_at") or raw.get("created_at")
    label = _to_str(raw.get("license_plate") or raw.get("matricule") or raw.get("plate_number"), "UNKNOWN")
    return {
        "id": _to_int(raw.get("id") or raw.get("detection_id"), 0),
        "camera_id": _to_int(raw.get("camera_id"), 0),
        "zone_id": raw.get("zone_id"),
        "type": "vehicle",
        "source": "vehicle",
        "label": label,
        "confidence": _to_float(raw.get("confidence"), 0.0),
        "status": _to_str(raw.get("status"), "detected"),
        "timestamp": timestamp,
        "image_url": raw.get("image_url"),
        "data": raw,
    }


def _parse_polygon_coords(polygon_coords: str) -> list[tuple[float, float]]:
    parsed = json.loads(polygon_coords)
    if not isinstance(parsed, list):
        raise ValueError("polygon_coords must be a list")

    normalized: list[tuple[float, float]] = []
    for item in parsed:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            x, y = item[0], item[1]
        elif isinstance(item, dict) and "x" in item and "y" in item:
            x, y = item["x"], item["y"]
        else:
            raise ValueError("Each polygon point must be [x, y] or {'x': ..., 'y': ...}")
        normalized.append((float(x), float(y)))
    return normalized


def _extract_success(result: object) -> bool:
    if isinstance(result, dict):
        return bool(result.get("success"))
    return False


def _parse_person_appearance_filters(
    *,
    top_color: Optional[str],
    bottom_color: Optional[str],
    backpack: Optional[str],
    hat: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[bool | str], Optional[bool | str]]:
    try:
        parsed_top = normalize_color(top_color) if top_color is not None else None
        parsed_bottom = normalize_color(bottom_color) if bottom_color is not None else None
        parsed_backpack = parse_accessory_filter(backpack)
        parsed_hat = parse_accessory_filter(hat)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return parsed_top, parsed_bottom, parsed_backpack, parsed_hat


async def _broadcast_face_recognition_event(
    *,
    pipeline: FaceRecognitionPipeline,
    result: dict,
):
    detection_id = result.get("detection_id")
    if not detection_id:
        return

    realtime = get_realtime_manager()
    await realtime.broadcast_person_detection(detection=result)

    try:
        similar = pipeline.find_similar_detections(
            int(detection_id),
            cross_camera_only=True,
            limit=1,
        )
    except Exception:
        return

    matches = similar.get("matches") or []
    if matches and float(matches[0].get("similarity") or 0.0) >= 0.88:
        await realtime.broadcast_person_reid_match(
            source_detection=similar.get("source") or result,
            match_detection=matches[0],
        )


# ============= FACIAL RECOGNITION =============

@router.post("/facial/register")
async def register_face(
    personnel_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Enregistrer le visage d'une personne"""
    try:
        image_bytes = await file.read()
        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.enroll_from_bytes(
            personnel_id=personnel_id,
            image_bytes=image_bytes,
            pose_label="front",
            source="api_ai_register",
            make_primary=True,
            original_filename=file.filename,
        )
        if bool(payload.get("success")):
            logger.info(f"âœ… Face registered: personnel {personnel_id}")
        return payload
    except Exception as e:
        logger.error(f"Error registering face: {e}")
        handler = ErrorHandler(db)
        return handler.handle_facial_exception(e, {"personnel_id": personnel_id})


@router.post("/face/enroll")
async def enroll_face(
    personnel_id: int = Form(...),
    pose_label: str = Form("front"),
    make_primary: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Register/enroll a person's face.

    Accepts either:
    - multipart `file`
    - `image_base64` form field
    """
    try:
        if file is not None:
            image_bytes = await file.read()
            original_filename = file.filename
        elif image_base64:
            image_bytes = _decode_base64_image(image_base64)
            original_filename = None
        else:
            raise HTTPException(status_code=400, detail="file or image_base64 is required")

        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.enroll_from_bytes(
            personnel_id=personnel_id,
            image_bytes=image_bytes,
            pose_label=pose_label.lower().strip() or "front",
            source="api_ai_enroll",
            make_primary=bool(make_primary),
            original_filename=original_filename,
        )
        if not payload.get("success"):
            raise HTTPException(status_code=400, detail=payload.get("message", "Enrollment failed"))
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error enrolling face: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/facial/recognize")
async def recognize_face(
    camera_id: int = Form(...),
    zone_id: Optional[int] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Reconnaître un visage dans une image"""
    ensure_manual_inference_allowed("ai.facial.recognize")
    try:
        image_bytes = await file.read()
        pipeline = FaceRecognitionPipeline(db)
        result = pipeline.recognize_from_bytes(
            image_bytes=image_bytes,
            camera_id=camera_id,
            zone_id=zone_id,
            persist=True,
            top_k=5,
        )
        if bool(result.get("success")):
            await _broadcast_face_recognition_event(pipeline=pipeline, result=result)
        note = result.get("notes") or result.get("message") or result.get("status") or "done"
        logger.info(f"âœ… Face recognition: {note}")
        return result

    except Exception as e:
        logger.error(f"Error recognizing face: {e}")
        handler = ErrorHandler(db)
        return handler.handle_facial_exception(e, {"camera_id": camera_id})


@router.post("/face/recognize")
async def recognize_face_from_frame(
    camera_id: int = Form(...),
    zone_id: Optional[int] = Form(None),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    top_k: int = Form(5),
    persist: bool = Form(True),
    db: Session = Depends(get_db),
):
    """
    Recognize face from a camera frame.

    Accepts either:
    - multipart file
    - image_base64 form field
    """
    ensure_manual_inference_allowed("ai.face.recognize")
    try:
        if file is not None:
            image_bytes = await file.read()
        elif image_base64:
            image_bytes = _decode_base64_image(image_base64)
        else:
            raise HTTPException(status_code=400, detail="file or image_base64 is required")

        pipeline = FaceRecognitionPipeline(db)
        result = pipeline.recognize_from_bytes(
            image_bytes=image_bytes,
            camera_id=camera_id,
            zone_id=zone_id,
            persist=bool(persist),
            top_k=max(1, min(int(top_k), 20)),
        )
        if bool(result.get("success")) and bool(persist):
            await _broadcast_face_recognition_event(pipeline=pipeline, result=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error recognizing face from frame: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/facial/history")
async def get_facial_history(
    personnel_id: Optional[int] = None,
    camera_id: Optional[int] = None,
    top_color: Optional[str] = Query(None),
    bottom_color: Optional[str] = Query(None),
    backpack: Optional[str] = Query(None),
    hat: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """Récupérer l'historique des détections faciales"""
    try:
        parsed_top, parsed_bottom, parsed_backpack, parsed_hat = _parse_person_appearance_filters(
            top_color=top_color,
            bottom_color=bottom_color,
            backpack=backpack,
            hat=hat,
        )
        pipeline = FaceRecognitionPipeline(db)
        history = pipeline.get_history(
            personnel_id=personnel_id,
            camera_id=camera_id,
            top_color=parsed_top,
            bottom_color=parsed_bottom,
            backpack=parsed_backpack,
            hat=parsed_hat,
            skip=skip,
            limit=limit,
        )

        return {
            "success": True,
            "count": len(history),
            "detections": history
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting facial history: {e}")
        return {
            "success": False,
            "message": str(e),
            "detections": []
        }


@router.get("/face/history")
async def get_face_history(
    personnel_id: Optional[int] = None,
    camera_id: Optional[int] = None,
    top_color: Optional[str] = Query(None),
    bottom_color: Optional[str] = Query(None),
    backpack: Optional[str] = Query(None),
    hat: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Detection history endpoint alias for /facial/history."""
    try:
        parsed_top, parsed_bottom, parsed_backpack, parsed_hat = _parse_person_appearance_filters(
            top_color=top_color,
            bottom_color=bottom_color,
            backpack=backpack,
            hat=hat,
        )
        pipeline = FaceRecognitionPipeline(db)
        history = pipeline.get_history(
            personnel_id=personnel_id,
            camera_id=camera_id,
            top_color=parsed_top,
            bottom_color=parsed_bottom,
            backpack=parsed_backpack,
            hat=parsed_hat,
            skip=skip,
            limit=limit,
        )
        return {
            "success": True,
            "count": len(history),
            "detections": history,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting face history: %s", e)
        return {
            "success": False,
            "message": str(e),
            "detections": [],
        }


@router.get("/facial/similar/{detection_id}")
async def get_facial_similar(
    detection_id: int,
    camera_id: Optional[int] = Query(None),
    cross_camera_only: bool = Query(False),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.find_similar_detections(
            detection_id=detection_id,
            camera_id=camera_id,
            cross_camera_only=bool(cross_camera_only),
            limit=limit,
        )
        return {"success": True, **payload}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as e:
        logger.error("Error getting facial similarity: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/facial/statistics")
async def get_facial_statistics(db: Session = Depends(get_db)):
    """Obtenir les statistiques de reconnaissance faciale"""
    try:
        pipeline = FaceRecognitionPipeline(db)
        stats = pipeline.get_statistics()

        return {
            "success": True,
            "statistics": stats
        }
    except Exception as e:
        logger.error(f"Error getting facial stats: {e}")
        return {
            "success": False,
            "message": str(e),
            "statistics": {}
        }


@router.get("/monitor/multi-cam")
async def get_multi_cam_monitor_snapshot(
    minutes: int = Query(30, ge=5, le=240),
    person_limit: int = Query(20, ge=1, le=100),
    vehicle_limit: int = Query(20, ge=1, le=100),
    similarity_threshold: float = Query(0.88, ge=0.5, le=1.0),
    force_refresh: bool = Query(True),
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    try:
        hub = get_multi_cam_monitor_stream_hub()
        payload = await hub.get_snapshot(
            params=MultiCamStreamParams.from_values(
                minutes=minutes,
                person_limit=person_limit,
                vehicle_limit=vehicle_limit,
                similarity_threshold=similarity_threshold,
            ),
            db=db,
            force_refresh=bool(force_refresh),
        )
        return payload
    except Exception as e:
        logger.error("Error getting multi-cam monitor snapshot: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/monitor/multi-cam/ws")
async def multi_cam_monitor_stream(websocket: WebSocket):
    current_user = await authenticate_websocket(websocket)
    if current_user is None:
        return

    params = MultiCamStreamParams.from_values(
        minutes=websocket.query_params.get("minutes"),
        person_limit=websocket.query_params.get("person_limit"),
        vehicle_limit=websocket.query_params.get("vehicle_limit"),
        similarity_threshold=websocket.query_params.get("similarity_threshold"),
    )
    hub = get_multi_cam_monitor_stream_hub()
    await hub.connect(websocket, params=params)
    try:
        while True:
            try:
                message = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            if message.strip().lower() == "ping":
                await websocket.send_json({"type": "pong", "data": {"stream_key": params.channel_key()}})
    finally:
        await hub.disconnect(websocket, params=params)


# ============= VEHICLES =============

@router.post("/vehicles/record-detection")
async def record_vehicle_detection(
    license_plate: str = Form(...),
    confidence: float = Form(...),
    camera_id: int = Form(...),
    zone_id: Optional[int] = Form(None),
    vehicle_type: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Enregistrer une détection de véhicule/plaque"""
    try:
        service = VehicleService(db)
        
        result = service.record_detection(
            license_plate=license_plate,
            confidence=confidence,
            camera_id=camera_id,
            zone_id=zone_id,
            vehicle_type=vehicle_type,
            color=color
        )
        
        if _extract_success(result):
            realtime = get_realtime_manager()
            await realtime.broadcast_vehicle_detection(detection=result)
            logger.info(f"âœ… Vehicle detected: {license_plate}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error recording vehicle: {e}")
        handler = ErrorHandler(db)
        return handler.handle_vehicle_exception(e, {"plate": license_plate})


@router.post("/vehicles/record-exit")
async def record_vehicle_exit(
    license_plate: str,
    camera_id: int,
    db: Session = Depends(get_db)
):
    """Enregistrer la sortie d'un vÃ©hicule"""
    try:
        service = VehicleService(db)
        
        result = service.record_exit(license_plate, camera_id)
        
        if _extract_success(result):
            logger.info(f"âœ… Vehicle exit: {license_plate}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error recording exit: {e}")
        handler = ErrorHandler(db)
        return handler.handle_vehicle_exception(e, {"plate": license_plate})


@router.get("/vehicles/statistics")
async def get_vehicle_statistics(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """Obtenir les statistiques de détection véhicules"""
    try:
        service = VehicleService(db)
        stats = service.get_statistics(db=db, days=days)
        
        return {
            "success": True,
            "period_days": days,
            "statistics": stats
        }
    except Exception as e:
        logger.error(f"Error getting vehicle stats: {e}")
        return {
            "success": False,
            "message": str(e),
            "statistics": {}
        }


@router.get("/vehicles/history")
async def get_vehicle_history(
    license_plate: Optional[str] = None,
    camera_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """Récupérer l'historique des détections véhicules"""
    try:
        service = VehicleService(db)
        history = service.get_detection_history(license_plate, camera_id, limit)
        
        return {
            "success": True,
            "count": len(history),
            "detections": history
        }
    except Exception as e:
        logger.error(f"Error getting vehicle history: {e}")
        return {
            "success": False,
            "message": str(e),
            "detections": []
        }


@router.delete("/vehicles/history/{event_id}")
async def delete_vehicle_history_event(
    event_id: int,
    delete_image: bool = Query(True),
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Delete one vehicle event from gallery history."""
    del current_user
    try:
        row = db.query(VehicleEvent).filter(VehicleEvent.id == int(event_id)).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Vehicle event #{event_id} not found")

        snapshot_path = str(row.snapshot_path or "").strip()

        deleted_frames = (
            db.query(VehicleEventFrame)
            .filter(VehicleEventFrame.event_id == int(event_id))
            .delete(synchronize_session=False)
        )
        detached_access_logs = (
            db.query(VehicleAccessLog)
            .filter(VehicleAccessLog.event_id == int(event_id))
            .update({VehicleAccessLog.event_id: None}, synchronize_session=False)
        )
        detached_alerts = (
            db.query(SecurityAlert)
            .filter(SecurityAlert.event_id == int(event_id))
            .update({SecurityAlert.event_id: None}, synchronize_session=False)
        )

        db.delete(row)
        db.commit()

        image_deleted = False
        if delete_image and snapshot_path:
            try:
                image_file = Path(snapshot_path)
                if not image_file.is_absolute():
                    image_file = (Path.cwd() / image_file).resolve()
                if image_file.exists() and image_file.is_file():
                    image_file.unlink(missing_ok=True)
                    image_deleted = True
            except Exception:
                image_deleted = False

        return {
            "success": True,
            "deleted_id": int(event_id),
            "image_deleted": bool(image_deleted),
            "deleted_frames": int(deleted_frames),
            "detached_access_logs": int(detached_access_logs),
            "detached_alerts": int(detached_alerts),
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Error deleting vehicle history event %s: %s", event_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detections")
async def get_ai_detections(
    camera_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    include_faces: bool = Query(True),
    include_vehicles: bool = Query(True),
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Unified detections feed (face + vehicle), sorted by newest first."""
    del current_user
    merged: list[RawDetection] = []
    warnings: list[str] = []

    # Fetch enough rows to apply global pagination after merging.
    fetch_size = min(500, max(1, int(skip) + int(limit)))

    if include_faces:
        try:
            face_pipeline = FaceRecognitionPipeline(db)
            face_history = face_pipeline.get_history(
                camera_id=camera_id,
                skip=0,
                limit=fetch_size,
            )
            for item in face_history:
                if isinstance(item, dict):
                    merged.append(_normalize_face_detection(cast(RawDetection, item)))
        except Exception as exc:
            logger.error("Error fetching face detections feed: %s", exc)
            warnings.append(f"face_feed_unavailable: {exc}")

    if include_vehicles:
        try:
            vehicle_service = VehicleService(db)
            vehicle_history = vehicle_service.get_detection_history(
                license_plate=None,
                camera_id=camera_id,
                limit=fetch_size,
            )
            for item in vehicle_history:
                if isinstance(item, dict):
                    merged.append(_normalize_vehicle_detection(cast(RawDetection, item)))
        except Exception as exc:
            logger.error("Error fetching vehicle detections feed: %s", exc)
            warnings.append(f"vehicle_feed_unavailable: {exc}")

    merged.sort(key=lambda item: _to_unix_ts(item.get("timestamp")), reverse=True)
    total = len(merged)
    page = merged[skip : skip + limit]

    return {
        "success": len(warnings) == 0,
        "partial": len(warnings) > 0,
        "count": len(page),
        "total": total,
        "skip": skip,
        "limit": limit,
        "detections": page,
        "warnings": warnings,
    }


@router.get("/camera/{camera_id}/detections")
async def get_ai_detections_by_camera(
    camera_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    include_faces: bool = Query(True),
    include_vehicles: bool = Query(True),
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Unified detections feed scoped to one camera."""
    return await get_ai_detections(
        camera_id=camera_id,
        skip=skip,
        limit=limit,
        include_faces=include_faces,
        include_vehicles=include_vehicles,
        current_user=current_user,
        db=db,
    )


@router.get("/ops-kpi")
async def get_ai_ops_kpi(
    window_minutes: int = Query(5, ge=1, le=1440),
    camera_id: Optional[int] = Query(None),
    unknown_rate_warning_pct: float = Query(20.0, ge=0.0, le=100.0),
    unknown_rate_critical_pct: float = Query(40.0, ge=0.0, le=100.0),
    false_positive_warning_pct: float = Query(10.0, ge=0.0, le=100.0),
    false_positive_critical_pct: float = Query(20.0, ge=0.0, le=100.0),
    pending_unknown_warning: int = Query(10, ge=0),
    pending_unknown_critical: int = Query(30, ge=0),
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Operational KPI snapshot for live SOC dashboard."""
    del current_user
    if unknown_rate_warning_pct > unknown_rate_critical_pct:
        raise HTTPException(status_code=422, detail="unknown_rate_warning_pct must be <= unknown_rate_critical_pct")
    if false_positive_warning_pct > false_positive_critical_pct:
        raise HTTPException(status_code=422, detail="false_positive_warning_pct must be <= false_positive_critical_pct")
    if pending_unknown_warning > pending_unknown_critical:
        raise HTTPException(status_code=422, detail="pending_unknown_warning must be <= pending_unknown_critical")

    now_utc = datetime.utcnow()
    window_start = now_utc - timedelta(minutes=int(window_minutes))

    face_query = db.query(func.count(FaceDetection.id)).filter(FaceDetection.detected_at >= window_start)
    vehicle_query = db.query(func.count(VehicleEvent.id)).filter(VehicleEvent.timestamp >= window_start)
    unknown_created_query = db.query(func.count(UnknownDetection.id)).filter(UnknownDetection.created_at >= window_start)
    unknown_resolved_query = db.query(func.count(UnknownDetection.id)).filter(
        UnknownDetection.is_resolved.is_(True),
        UnknownDetection.resolved_at.isnot(None),
        UnknownDetection.resolved_at >= window_start,
    )
    unknown_ignored_query = db.query(func.count(UnknownDetection.id)).filter(
        UnknownDetection.is_ignored.is_(True),
        UnknownDetection.resolved_at.isnot(None),
        UnknownDetection.resolved_at >= window_start,
    )
    unknown_pending_query = db.query(func.count(UnknownDetection.id)).filter(
        UnknownDetection.is_resolved.is_(False),
        UnknownDetection.is_ignored.is_(False),
    )

    if camera_id is not None:
        face_query = face_query.filter(FaceDetection.camera_id == int(camera_id))
        vehicle_query = vehicle_query.filter(VehicleEvent.camera_id == int(camera_id))
        unknown_created_query = unknown_created_query.filter(UnknownDetection.camera_id == int(camera_id))
        unknown_resolved_query = unknown_resolved_query.filter(UnknownDetection.camera_id == int(camera_id))
        unknown_ignored_query = unknown_ignored_query.filter(UnknownDetection.camera_id == int(camera_id))
        unknown_pending_query = unknown_pending_query.filter(UnknownDetection.camera_id == int(camera_id))

    face_detections_total_window = int(face_query.scalar() or 0)
    vehicle_detections_total_window = int(vehicle_query.scalar() or 0)
    detections_total_window = face_detections_total_window + vehicle_detections_total_window

    unknown_created_total_window = int(unknown_created_query.scalar() or 0)
    operator_resolved_total_window = int(unknown_resolved_query.scalar() or 0)
    operator_ignored_total_window = int(unknown_ignored_query.scalar() or 0)
    operator_resolutions_total_window = operator_resolved_total_window + operator_ignored_total_window
    pending_unknown_total = int(unknown_pending_query.scalar() or 0)

    unknown_rate_pct = (
        (unknown_created_total_window / detections_total_window) * 100.0
        if detections_total_window > 0
        else 0.0
    )
    false_positive_rate_pct = (
        (operator_ignored_total_window / operator_resolutions_total_window) * 100.0
        if operator_resolutions_total_window > 0
        else 0.0
    )

    sla_alerts: list[dict[str, object]] = []

    def add_upper_alert(
        *,
        code: str,
        label: str,
        metric: str,
        value: float,
        warning_threshold: float,
        critical_threshold: float,
        unit: str,
    ) -> None:
        severity = "critical" if value >= critical_threshold else "warning" if value >= warning_threshold else "ok"
        if severity == "ok":
            return
        threshold = critical_threshold if severity == "critical" else warning_threshold
        sla_alerts.append(
            {
                "code": code,
                "severity": severity,
                "label": label,
                "metric": metric,
                "value": round(float(value), 2),
                "unit": unit,
                "threshold": round(float(threshold), 2),
                "warning_threshold": round(float(warning_threshold), 2),
                "critical_threshold": round(float(critical_threshold), 2),
                "message": (
                    f"{label} is {round(float(value), 2)}{unit} "
                    f"(threshold {round(float(threshold), 2)}{unit}, severity={severity})"
                ),
            }
        )

    add_upper_alert(
        code="unknown_rate",
        label="Unknown rate",
        metric="unknown_rate_pct",
        value=float(unknown_rate_pct),
        warning_threshold=float(unknown_rate_warning_pct),
        critical_threshold=float(unknown_rate_critical_pct),
        unit="%",
    )
    add_upper_alert(
        code="false_positive_rate",
        label="False positive rate",
        metric="false_positive_rate_pct",
        value=float(false_positive_rate_pct),
        warning_threshold=float(false_positive_warning_pct),
        critical_threshold=float(false_positive_critical_pct),
        unit="%",
    )
    add_upper_alert(
        code="pending_unknown",
        label="Pending unknown queue",
        metric="pending_unknown_total",
        value=float(pending_unknown_total),
        warning_threshold=float(pending_unknown_warning),
        critical_threshold=float(pending_unknown_critical),
        unit="",
    )

    critical_count = sum(1 for alert in sla_alerts if str(alert.get("severity")) == "critical")
    warning_count = sum(1 for alert in sla_alerts if str(alert.get("severity")) == "warning")
    if critical_count > 0:
        sla_status = "critical"
    elif warning_count > 0:
        sla_status = "warning"
    else:
        sla_status = "ok"

    return {
        "success": True,
        "window_minutes": int(window_minutes),
        "camera_id": int(camera_id) if camera_id is not None else None,
        "updated_at": now_utc.isoformat(),
        "face_detections_total_window": face_detections_total_window,
        "vehicle_detections_total_window": vehicle_detections_total_window,
        "detections_total_window": detections_total_window,
        "unknown_created_total_window": unknown_created_total_window,
        "unknown_rate_pct": round(float(unknown_rate_pct), 2),
        "operator_resolved_total_window": operator_resolved_total_window,
        "operator_ignored_total_window": operator_ignored_total_window,
        "operator_resolutions_total_window": operator_resolutions_total_window,
        "false_positive_rate_pct": round(float(false_positive_rate_pct), 2),
        "pending_unknown_total": pending_unknown_total,
        "sla_status": sla_status,
        "attention_required": bool(sla_alerts),
        "sla_alerts": sla_alerts,
        "sla_alert_count": len(sla_alerts),
        "thresholds": {
            "unknown_rate_warning_pct": float(unknown_rate_warning_pct),
            "unknown_rate_critical_pct": float(unknown_rate_critical_pct),
            "false_positive_warning_pct": float(false_positive_warning_pct),
            "false_positive_critical_pct": float(false_positive_critical_pct),
            "pending_unknown_warning": int(pending_unknown_warning),
            "pending_unknown_critical": int(pending_unknown_critical),
        },
    }


# ============= ZONES =============

@router.post("/zones/create")
async def create_zone(
    name: str = Form(...),
    camera_id: int = Form(...),
    polygon_coords: str = Form(...),
    description: Optional[str] = Form(None),
    sensitivity: int = Form(5),
    db: Session = Depends(get_db)
):
    """Create virtual zone with polygon coordinates."""
    try:
        coords = _parse_polygon_coords(polygon_coords)
    except (ValueError, json.JSONDecodeError):
        return {"success": False, "message": "Invalid polygon_coords format (should be JSON list)"}
    try:
        service = ZoneService(db)
        
        result = service.create_zone(
            name=name,
            description=description,
            camera_id=camera_id,
            polygon_coords=coords,
            sensitivity=sensitivity
        )
        
        if _extract_success(result):
            logger.info(f"âœ… Zone created: {name}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error creating zone: {e}")
        handler = ErrorHandler(db)
        return handler.handle_zone_exception(e, {"zone_name": name})


@router.post("/zones/{zone_id}/entry")
async def record_zone_entry(
    zone_id: int,
    personnel_id: Optional[int] = None,
    vehicle_entry_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Enregistrer une entrée dans une zone"""
    try:
        if not personnel_id and not vehicle_entry_id:
            return {
                "success": False,
                "message": "Either personnel_id or vehicle_entry_id required"
            }
        
        service = ZoneService(db)
        result = service.record_entry(zone_id, personnel_id, vehicle_entry_id)
        
        if _extract_success(result):
            occupant_type = "personnel" if personnel_id else "vehicle"
            logger.info(f"âœ… Zone entry: {occupant_type} in zone {zone_id}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error recording zone entry: {e}")
        handler = ErrorHandler(db)
        return handler.handle_zone_exception(e, {"zone_id": zone_id})


@router.post("/zones/{occupancy_id}/exit")
async def record_zone_exit(
    occupancy_id: int,
    db: Session = Depends(get_db)
):
    """Enregistrer une sortie d'une zone"""
    try:
        service = ZoneService(db)
        result = service.record_exit(occupancy_id)
        
        if _extract_success(result):
            logger.info(f"âœ… Zone exit: occupancy {occupancy_id}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error recording zone exit: {e}")
        handler = ErrorHandler(db)
        return handler.handle_zone_exception(e, {"occupancy_id": occupancy_id})


@router.get("/zones/{zone_id}/occupancy")
async def get_zone_occupancy(
    zone_id: int,
    db: Session = Depends(get_db)
):
    """Obtenir l'occupance actuelle d'une zone"""
    try:
        service = ZoneService(db)
        result = service.get_zone_occupancy(zone_id)
        
        return result
        
    except Exception as e:
        logger.error(f"Error getting zone occupancy: {e}")
        return {
            "success": False,
            "message": str(e),
            "occupants": []
        }


@router.get("/zones/{zone_id}/statistics")
async def get_zone_statistics(
    zone_id: int,
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db)
):
    """Obtenir les statistiques d'une zone"""
    try:
        service = ZoneService(db)
        stats = service.get_zone_statistics(zone_id, days)
        
        return {
            "success": True,
            "zone_id": zone_id,
            "period_days": days,
            "statistics": stats
        }
    except Exception as e:
        logger.error(f"Error getting zone stats: {e}")
        return {
            "success": False,
            "message": str(e),
            "statistics": {}
        }


@router.post("/zones/{zone_id}/point-check")
async def check_point_in_zone(
    zone_id: int,
    x: float,
    y: float,
    db: Session = Depends(get_db)
):
    """Vérifier si un point (x,y) est dans la zone"""
    try:
        from vms.backend.models import Zone
        
        zone = db.query(Zone).filter(Zone.id == zone_id).first()
        if not zone:
            return {
                "success": False,
                "message": f"Zone {zone_id} not found"
            }
        
        service = ZoneService(db)
        point = (x, y)
        polygon_raw = zone.polygon_coordinates
        if isinstance(polygon_raw, str):
            polygon = _parse_polygon_coords(polygon_raw)
        elif isinstance(polygon_raw, list):
            polygon = _parse_polygon_coords(json.dumps(polygon_raw))
        else:
            return {"success": False, "message": "Zone polygon coordinates are invalid", "inside": False}

        inside = service.point_in_polygon(point, polygon)
        
        return {
            "success": True,
            "zone_id": zone_id,
            "point": {"x": x, "y": y},
            "inside": inside
        }
        
    except Exception as e:
        logger.error(f"Error checking point: {e}")
        return {
            "success": False,
            "message": str(e),
            "inside": False
        }


# ============= SYSTEM LOGS =============

@router.get("/logs")
async def get_system_logs(
    level: Optional[str] = None,
    module: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """Récupérer les logs du système"""
    try:
        logger_service = SystemLogger(db)
        logs = logger_service.get_logs(level, module, limit)
        
        return {
            "success": True,
            "count": len(logs),
            "logs": logs
        }
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        return {
            "success": False,
            "message": str(e),
            "logs": []
        }


@router.get("/health/detailed")
async def detailed_health_check(db: Session = Depends(get_db)):
    """Health check détaillé avec stats AI"""
    try:
        face_pipeline = FaceRecognitionPipeline(db)
        vehicle_service = VehicleService(db)
        
        facial_stats = face_pipeline.get_statistics()
        vehicle_stats = vehicle_service.get_statistics(days=1)
        
        return {
            "success": True,
            "timestamp": datetime.now().astimezone().isoformat(),
            "services": {
                "facial_recognition": {
                    "status": "operational",
                    "stats": facial_stats
                },
                "vehicle_detection": {
                    "status": "operational",
                    "stats": vehicle_stats
                },
                "zone_management": {
                    "status": "operational"
                }
            },
            "database": {
                "status": "connected"
            }
        }
    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return {
            "success": False,
            "message": str(e),
            "services": {}
        }
