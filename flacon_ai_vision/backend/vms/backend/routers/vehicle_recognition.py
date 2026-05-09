from __future__ import annotations

import asyncio
import base64
from datetime import datetime
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from vms.backend.core.audit import write_audit_log
from vms.backend.core.database import SessionLocal, get_db
from vms.backend.core.time_utils import utc_now_naive, utc_now_naive_iso, utc_now_naive_strftime
from vms.backend.models import Camera, SecurityAlert
from vms.backend.core.security import get_current_user
from vms.backend.routers.runtime_guard import ensure_manual_inference_allowed
from vms.backend.services.job_queue import get_job_queue
from vms.backend.services.stream_service import StreamService
from vms.backend.services.camera_service import CameraService
from vms.backend.services.vehicle_ai.tamper_detector import CameraTamperDetector
from vms.backend.services.vehicle_ai.vehicle_pipeline import VehicleRecognitionPipeline
from vms.backend.services.vehicle_ai.vehicle_search_contract import (
    normalize_vehicle_body_style_filter,
    normalize_vehicle_color_filter,
    normalize_vehicle_type_filter,
)
from vms.backend.services.vehicle_ai.vehicle_taxonomy import (
    normalize_vehicle_brand,
    normalize_vehicle_model,
)
from vms.backend.vehicle.ai_engine import detect_vehicle_objects_from_bytes

router = APIRouter(prefix="/api/vehicle", tags=["vehicle-recognition"])
_tamper_detector = CameraTamperDetector()


class ManualOverridePayload(BaseModel):
    access_log_id: Optional[int] = None
    event_id: Optional[int] = None
    forced_decision: str = "allowed"
    note: Optional[str] = None


def _decode_base64_image(image_base64: str) -> bytes:
    payload = image_base64
    if "," in image_base64 and "base64" in image_base64.split(",", 1)[0]:
        payload = image_base64.split(",", 1)[1]
    return base64.b64decode(payload)


def _build_camera_source(camera: Camera) -> Optional[str]:
    if camera.rtsp_url and camera.rtsp_url.strip():
        injected = CameraService._inject_rtsp_auth(camera.rtsp_url.strip(), camera.username, camera.password)
        return injected or camera.rtsp_url.strip()

    if not camera.ip_address:
        return None

    port = int(camera.port or 554)
    if camera.username and camera.password:
        return f"rtsp://{camera.username}:{camera.password}@{camera.ip_address}:{port}/stream"
    if camera.username:
        return f"rtsp://{camera.username}@{camera.ip_address}:{port}/stream"
    return f"rtsp://{camera.ip_address}:{port}/stream"


def _save_tamper_snapshot(frame, camera_id: int, tamper_type: str) -> Optional[str]:
    if frame is None:
        return None
    try:
        image_bytes = StreamService.frame_to_jpeg(frame, quality=85)
        base_dir = Path("data") / "camera_tamper"
        base_dir.mkdir(parents=True, exist_ok=True)
        filename = f"cam_{int(camera_id)}_{tamper_type}_{utc_now_naive_strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        path = base_dir / filename
        path.write_bytes(image_bytes)
        return str(path).replace("\\", "/")
    except Exception:
        return None


def _create_tamper_alert(
    *,
    db: Session,
    camera_id: int,
    gate_id: Optional[str],
    snapshot_path: Optional[str],
    tamper_type: str,
    confidence: float,
    reason: str,
    metrics: Optional[dict],
) -> Optional[int]:
    try:
        row = SecurityAlert(
            type="camera_tamper",
            plate_number=None,
            normalized_plate=None,
            camera_id=int(camera_id),
            gate_id=gate_id,
            timestamp=utc_now_naive(),
            severity_level="critical",
            resolution_status="open",
            message=f"Camera tamper detected: {tamper_type}",
            event_id=None,
            access_log_id=None,
            snapshot_path=snapshot_path,
            details={
                "tamper_type": tamper_type,
                "confidence": float(max(0.0, min(1.0, confidence))),
                "reason": reason,
                "metrics": metrics or {},
            },
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    except Exception:
        db.rollback()
        return None


def _build_tamper_response(
    *,
    camera_id: int,
    zone_id: Optional[int],
    gate_id: Optional[str],
    direction: Optional[str],
    tamper_type: str,
    confidence: float,
    reason: str,
    metrics: Optional[dict],
    snapshot_path: Optional[str],
    alert_id: Optional[int],
):
    return {
        "success": True,
        "status": "camera_tamper",
        "vehicle_detected": False,
        "plate_number": None,
        "plate_type": "unknown",
        "confidence": 0.0,
        "camera_id": camera_id,
        "zone_id": zone_id,
        "gate_id": gate_id,
        "direction": str(direction or "UNKNOWN").upper(),
        "timestamp": utc_now_naive_iso(),
        "event_id": None,
        "access_log_id": None,
        "security_alert_ids": [alert_id] if alert_id is not None else [],
        "snapshot_path": snapshot_path,
        "security_tag": "camera_tamper",
        "priority": True,
        "decision": "denied",
        "decision_reason": tamper_type,
        "requires_manual_review": True,
        "alert_type": "camera_tamper",
        "tamper": {
            "tamper_detected": True,
            "tamper_type": tamper_type,
            "confidence": float(max(0.0, min(1.0, confidence))),
            "reason": reason,
            "metrics": metrics or {},
        },
        "pipeline": {
            "detector": "tamper_guard",
            "ocr": "skipped",
            "normalizer": "skipped",
            "classifier": "skipped",
        },
    }


def _bbox_dict_to_xyxy(bbox: Optional[dict]) -> Optional[list[int]]:
    if not bbox:
        return None
    x = int(bbox.get("x", 0))
    y = int(bbox.get("y", 0))
    w = int(bbox.get("w", 0))
    h = int(bbox.get("h", 0))
    return [x, y, x + max(0, w), y + max(0, h)]


def _build_detect_payload_from_modular_result(
    *,
    modular: dict,
    confidence: float,
    iou_threshold: float,
    max_detections: int,
    vehicle_only: bool,
    plate_only_fallback: bool,
) -> dict:
    vehicle_bbox_xyxy = _bbox_dict_to_xyxy(modular.get("vehicle_bbox"))
    plate_bbox_xyxy = _bbox_dict_to_xyxy(modular.get("plate_bbox"))
    has_vehicle_or_plate = bool(modular.get("vehicle_detected")) or bool(modular.get("plate_number"))

    row = None
    if has_vehicle_or_plate:
        consistency = modular.get("consistency")
        if consistency is None and isinstance(modular.get("vehicle_profile"), dict):
            consistency = (modular.get("vehicle_profile") or {}).get("consistency")
        anomaly = modular.get("anomaly")
        if anomaly is None and isinstance(modular.get("vehicle_profile"), dict):
            anomaly = (modular.get("vehicle_profile") or {}).get("anomaly")
        anomaly_alert = modular.get("anomaly_alert")
        if anomaly_alert is None and isinstance(modular.get("vehicle_profile"), dict):
            anomaly_alert = (modular.get("vehicle_profile") or {}).get("anomaly_alert")
        row = {
            "class": modular.get("vehicle_class") or "unknown",
            "class_id": -1,
            "confidence": float(modular.get("vehicle_confidence") or 0.0),
            "bbox": vehicle_bbox_xyxy or [0, 0, 0, 0],
            "plate": modular.get("plate_number") or "",
            "plate_type": modular.get("plate_type") or "unknown",
            "color": modular.get("dominant_color") or "unknown",
            "plate_bbox": plate_bbox_xyxy,
            "source": ((modular.get("pipeline") or {}).get("detector")) or "modular_pipeline",
            "plate_confidence": float(modular.get("plate_confidence") or 0.0),
            "track_id": modular.get("track_id"),
            "logo_path": ((modular.get("vehicle_profile") or {}).get("logo_path"))
            if isinstance(modular.get("vehicle_profile"), dict)
            else None,
            "vehicle_profile": modular.get("vehicle_profile"),
            "consistency": consistency,
            "anomaly": anomaly,
            "anomaly_alert": anomaly_alert,
        }

    rows = [row] if row is not None else []
    return {
        "success": bool(modular.get("success", False)),
        "message": "Detection completed",
        "model": os.getenv("VEHICLE_DETECT_MODEL", "yolov8n.pt"),
        "backend": "vehicle_modular_pipeline",
        "device": str(((modular.get("pipeline") or {}).get("detector_backend")) or "unknown"),
        "image_shape": None,
        "params": {
            "confidence": float(confidence),
            "iou_threshold": float(iou_threshold),
            "max_detections": int(max_detections),
            "vehicle_only": bool(vehicle_only),
            "plate_only_fallback": bool(plate_only_fallback),
            "use_modular_engine": True,
        },
        "pipeline": {
            "detector": (modular.get("pipeline") or {}).get("detector"),
            "tracker": (modular.get("pipeline") or {}).get("tracker"),
            "ocr": (modular.get("pipeline") or {}).get("ocr"),
            "plate_classifier": (modular.get("pipeline") or {}).get("classifier"),
        },
        "plate_only_fallback_attempted": bool(modular.get("plate_only_fallback_attempted", False)),
        "plate_only_fallback_used": bool(modular.get("plate_only_fallback_used", False)),
        "plate_only_fallback_reason": modular.get("plate_only_fallback_reason"),
        "consistency": modular.get("consistency"),
        "anomaly": modular.get("anomaly"),
        "anomaly_alert": modular.get("anomaly_alert"),
        "vehicles_count": len(rows),
        "vehicles": rows,
        "detections_count": len(rows),
        "detections": rows,
        "inference_ms": float(modular.get("latency_ms") or 0.0),
        "modular": modular,
    }


def _run_vehicle_recognition_job(
    *,
    image_bytes: bytes,
    camera_id: int,
    zone_id: Optional[int],
    gate_id: Optional[str],
    direction: str,
    persist: bool,
    save_snapshot: bool,
) -> dict:
    db = SessionLocal()
    try:
        pipeline = VehicleRecognitionPipeline(db)
        return pipeline.recognize_from_bytes(
            image_bytes=image_bytes,
            camera_id=camera_id,
            zone_id=zone_id,
            gate_id=gate_id,
            direction=direction,
            persist=persist,
            save_snapshot=save_snapshot,
        )
    finally:
        db.close()


@router.post("/recognize")
async def recognize_vehicle(
    camera_id: int = Form(...),
    zone_id: Optional[int] = Form(None),
    gate_id: Optional[str] = Form(None),
    direction: str = Form("IN"),
    persist: bool = Form(True),
    save_snapshot: bool = Form(True),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_manual_inference_allowed("vehicle.recognize")
    if file is None and not image_base64:
        raise HTTPException(status_code=400, detail="file or image_base64 is required")

    try:
        image_bytes = await file.read() if file is not None else _decode_base64_image(image_base64 or "")
        pipeline = VehicleRecognitionPipeline(db)
        payload = pipeline.recognize_from_bytes(
            image_bytes=image_bytes,
            camera_id=camera_id,
            zone_id=zone_id,
            gate_id=gate_id,
            direction=direction,
            persist=bool(persist),
            save_snapshot=bool(save_snapshot),
        )
        if not payload.get("success", False):
            raise HTTPException(status_code=400, detail=payload.get("message", "Vehicle recognition failed"))
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recognize/async")
async def recognize_vehicle_async(
    camera_id: int = Form(...),
    zone_id: Optional[int] = Form(None),
    gate_id: Optional[str] = Form(None),
    direction: str = Form("IN"),
    persist: bool = Form(True),
    save_snapshot: bool = Form(True),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
):
    ensure_manual_inference_allowed("vehicle.recognize_async")
    if file is None and not image_base64:
        raise HTTPException(status_code=400, detail="file or image_base64 is required")

    image_bytes = await file.read() if file is not None else _decode_base64_image(image_base64 or "")
    queue = get_job_queue()
    job_id = queue.enqueue(
        "vehicle_recognition",
        _run_vehicle_recognition_job,
        image_bytes=image_bytes,
        camera_id=camera_id,
        zone_id=zone_id,
        gate_id=gate_id,
        direction=direction,
        persist=bool(persist),
        save_snapshot=bool(save_snapshot),
    )
    return {"success": True, "job_id": job_id, "status": "queued"}


@router.post("/detect")
async def detect_vehicle(
    file: UploadFile = File(...),
    camera_id: Optional[int] = Form(None),
    confidence: float = Form(0.25),
    iou_threshold: float = Form(0.45),
    max_detections: int = Form(100),
    vehicle_only: bool = Form(True),
    plate_only_fallback: bool = Form(True),
    use_modular_engine: Optional[bool] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Vehicle detection endpoint (legacy detector or modular pipeline)."""
    ensure_manual_inference_allowed("vehicle.detect")

    try:
        image_bytes = await file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Empty file payload")

        default_modular = os.getenv("VEHICLE_DETECT_USE_MODULAR", "false").strip().lower() == "true"
        resolved_use_modular = default_modular if use_modular_engine is None else bool(use_modular_engine)
        timeout_sec = max(5.0, float(os.getenv("VEHICLE_DETECT_TIMEOUT_SEC", "60")))
        if resolved_use_modular:
            resolved_camera_id = int(camera_id) if camera_id is not None else 1
            try:
                modular_result = await asyncio.wait_for(
                    run_in_threadpool(
                        lambda: VehicleRecognitionPipeline(db).recognize_from_bytes(
                            image_bytes=image_bytes,
                            camera_id=resolved_camera_id,
                            zone_id=None,
                            gate_id=None,
                            direction="IN",
                            persist=False,
                            save_snapshot=False,
                        )
                    ),
                    timeout=timeout_sec,
                )
            except TimeoutError as exc:
                raise HTTPException(
                    status_code=504,
                    detail=(
                        f"Vehicle detection timeout after {int(timeout_sec)}s. "
                        "Try a smaller image or lower OCR load."
                    ),
                ) from exc

            payload = _build_detect_payload_from_modular_result(
                modular=modular_result,
                confidence=confidence,
                iou_threshold=iou_threshold,
                max_detections=max_detections,
                vehicle_only=bool(vehicle_only),
                plate_only_fallback=bool(plate_only_fallback),
            )
        else:
            try:
                payload = await asyncio.wait_for(
                    run_in_threadpool(
                        detect_vehicle_objects_from_bytes,
                        image_bytes,
                        confidence=confidence,
                        iou_threshold=iou_threshold,
                        max_detections=max_detections,
                        vehicle_only=bool(vehicle_only),
                        plate_only_fallback=bool(plate_only_fallback),
                        db=db,
                    ),
                    timeout=timeout_sec,
                )
            except TimeoutError as exc:
                raise HTTPException(
                    status_code=504,
                    detail=(
                        f"Vehicle detection timeout after {int(timeout_sec)}s. "
                        "Try a smaller image or lower OCR load."
                    ),
                ) from exc

        if not payload.get("success", False):
            raise HTTPException(status_code=400, detail=payload.get("message", "Vehicle detection failed"))

        payload["camera_id"] = int(camera_id) if camera_id is not None else None
        payload["filename"] = file.filename
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}")
def get_vehicle_job_status(
    job_id: str,
    current_user: dict = Depends(get_current_user),
):
    queue = get_job_queue()
    row = queue.get(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "success": True,
        "job_id": row.job_id,
        "name": row.name,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "result": row.result,
        "error": row.error,
    }


@router.get("/jobs")
def list_vehicle_jobs(
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None, pattern="^(queued|running|completed|failed)?$"),
    current_user: dict = Depends(get_current_user),
):
    queue = get_job_queue()
    rows = queue.list(limit=limit, status=status) if hasattr(queue, "list") else []
    items = [
        {
            "job_id": row.job_id,
            "name": row.name,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "has_result": row.result is not None,
            "has_error": bool(row.error),
        }
        for row in rows
    ]
    summary = {
        "queued": sum(1 for row in rows if row.status == "queued"),
        "running": sum(1 for row in rows if row.status == "running"),
        "completed": sum(1 for row in rows if row.status == "completed"),
        "failed": sum(1 for row in rows if row.status == "failed"),
    }
    return {"success": True, "count": len(items), "summary": summary, "jobs": items}


@router.post("/recognize/camera/{camera_id}")
def recognize_vehicle_from_camera(
    camera_id: int,
    payload: Optional[dict] = Body(default=None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_manual_inference_allowed("vehicle.recognize_camera")
    try:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if camera is None:
            raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

        zone_id_raw = (payload or {}).get("zone_id")
        zone_id = int(zone_id_raw) if zone_id_raw is not None else None
        gate_id = (payload or {}).get("gate_id")
        direction = str((payload or {}).get("direction", "IN"))
        persist = bool((payload or {}).get("persist", True))
        save_snapshot = bool((payload or {}).get("save_snapshot", True))

        source = _build_camera_source(camera)
        frame = StreamService.get_camera_frame(camera_id=camera_id, rtsp_url=source)
        if frame is None:
            alert_id = _create_tamper_alert(
                db=db,
                camera_id=camera_id,
                gate_id=gate_id,
                snapshot_path=None,
                tamper_type="signal_loss",
                confidence=1.0,
                reason="no_frame_from_stream",
                metrics={},
            )
            return _build_tamper_response(
                camera_id=camera_id,
                zone_id=zone_id,
                gate_id=gate_id,
                direction=direction,
                tamper_type="signal_loss",
                confidence=1.0,
                reason="no_frame_from_stream",
                metrics={},
                snapshot_path=None,
                alert_id=alert_id,
            )

        tamper = _tamper_detector.detect(frame)
        if tamper.tamper_detected:
            snapshot_path = _save_tamper_snapshot(frame, camera_id=camera_id, tamper_type=tamper.tamper_type or "tamper")
            alert_id = _create_tamper_alert(
                db=db,
                camera_id=camera_id,
                gate_id=gate_id,
                snapshot_path=snapshot_path,
                tamper_type=tamper.tamper_type or "camera_tamper",
                confidence=tamper.confidence,
                reason=tamper.reason,
                metrics=tamper.metrics,
            )
            return _build_tamper_response(
                camera_id=camera_id,
                zone_id=zone_id,
                gate_id=gate_id,
                direction=direction,
                tamper_type=tamper.tamper_type or "camera_tamper",
                confidence=tamper.confidence,
                reason=tamper.reason,
                metrics=tamper.metrics,
                snapshot_path=snapshot_path,
                alert_id=alert_id,
            )

        image_bytes = StreamService.frame_to_jpeg(frame, quality=88)
        pipeline = VehicleRecognitionPipeline(db)
        result = pipeline.recognize_from_frame(
            frame_bgr=frame,
            camera_id=camera_id,
            zone_id=zone_id,
            gate_id=gate_id,
            direction=direction,
            persist=persist,
            save_snapshot=save_snapshot,
            image_bytes=image_bytes,
        )
        if not result.get("success", False):
            raise HTTPException(status_code=400, detail=result.get("message", "Vehicle recognition failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recognize/camera/{camera_id}/async")
def recognize_vehicle_from_camera_async(
    camera_id: int,
    payload: Optional[dict] = Body(default=None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_manual_inference_allowed("vehicle.recognize_camera_async")
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    zone_id_raw = (payload or {}).get("zone_id")
    zone_id = int(zone_id_raw) if zone_id_raw is not None else None
    gate_id = (payload or {}).get("gate_id")
    direction = str((payload or {}).get("direction", "IN"))
    persist = bool((payload or {}).get("persist", True))
    save_snapshot = bool((payload or {}).get("save_snapshot", True))

    source = _build_camera_source(camera)
    frame = StreamService.get_camera_frame(camera_id=camera_id, rtsp_url=source)
    if frame is None:
        alert_id = _create_tamper_alert(
            db=db,
            camera_id=camera_id,
            gate_id=gate_id,
            snapshot_path=None,
            tamper_type="signal_loss",
            confidence=1.0,
            reason="no_frame_from_stream",
            metrics={},
        )
        return _build_tamper_response(
            camera_id=camera_id,
            zone_id=zone_id,
            gate_id=gate_id,
            direction=direction,
            tamper_type="signal_loss",
            confidence=1.0,
            reason="no_frame_from_stream",
            metrics={},
            snapshot_path=None,
            alert_id=alert_id,
        )

    tamper = _tamper_detector.detect(frame)
    if tamper.tamper_detected:
        snapshot_path = _save_tamper_snapshot(frame, camera_id=camera_id, tamper_type=tamper.tamper_type or "tamper")
        alert_id = _create_tamper_alert(
            db=db,
            camera_id=camera_id,
            gate_id=gate_id,
            snapshot_path=snapshot_path,
            tamper_type=tamper.tamper_type or "camera_tamper",
            confidence=tamper.confidence,
            reason=tamper.reason,
            metrics=tamper.metrics,
        )
        return _build_tamper_response(
            camera_id=camera_id,
            zone_id=zone_id,
            gate_id=gate_id,
            direction=direction,
            tamper_type=tamper.tamper_type or "camera_tamper",
            confidence=tamper.confidence,
            reason=tamper.reason,
            metrics=tamper.metrics,
            snapshot_path=snapshot_path,
            alert_id=alert_id,
        )

    image_bytes = StreamService.frame_to_jpeg(frame, quality=88)
    queue = get_job_queue()
    job_id = queue.enqueue(
        "vehicle_recognition_camera",
        _run_vehicle_recognition_job,
        image_bytes=image_bytes,
        camera_id=camera_id,
        zone_id=zone_id,
        gate_id=gate_id,
        direction=direction,
        persist=persist,
        save_snapshot=save_snapshot,
    )
    return {"success": True, "job_id": job_id, "status": "queued", "camera_id": camera_id}


@router.post("/recognize/camera/{camera_id}/release")
def release_vehicle_camera_stream(
    camera_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Explicitly release cached capture for a camera source.
    Useful when UI stops auto-run or leaves monitoring page.
    """
    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if camera is None:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    source = _build_camera_source(camera)
    released = StreamService.release_camera_stream(rtsp_url=source)
    return {
        "success": True,
        "camera_id": camera_id,
        "released": bool(released),
        "active_streams": StreamService.active_stream_count(),
    }


@router.get("/history")
def get_vehicle_history(
    camera_id: Optional[int] = Query(None),
    plate_type: Optional[str] = Query(None, pattern="^(civil|military|unknown)?$"),
    plate_number: Optional[str] = Query(None),
    color: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    body_style: Optional[str] = Query(None),
    vehicle_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = VehicleRecognitionPipeline(db)
    try:
        normalized_color = normalize_vehicle_color_filter(color)
        normalized_body_style = normalize_vehicle_body_style_filter(body_style)
        normalized_vehicle_type = normalize_vehicle_type_filter(vehicle_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    rows = pipeline.get_history(
        camera_id=camera_id,
        plate_type=plate_type,
        plate_number=plate_number,
        dominant_color=normalized_color,
        brand=normalize_vehicle_brand(brand) or None,
        model=normalize_vehicle_model(model),
        body_style=normalized_body_style,
        vehicle_type=normalized_vehicle_type,
        skip=skip,
        limit=limit,
    )
    return {"success": True, "count": len(rows), "events": rows}


@router.get("/forensic/{event_id}")
def get_vehicle_forensic_event(
    event_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = VehicleRecognitionPipeline(db)
    payload = pipeline.get_forensic_event(event_id=event_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Vehicle event {event_id} not found")
    return {"success": True, "forensic": payload}


@router.get("/replay/{event_id}")
def replay_vehicle_event(
    event_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = VehicleRecognitionPipeline(db)
    payload = pipeline.get_forensic_event(event_id=event_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Vehicle event {event_id} not found")
    return {"success": True, "replay": payload}


@router.get("/statistics")
def get_vehicle_statistics(
    hours: int = Query(24, ge=1, le=720),
    camera_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = VehicleRecognitionPipeline(db)
    return {"success": True, "statistics": pipeline.get_statistics(hours=hours, camera_id=camera_id)}


@router.get("/monitor/live")
def get_vehicle_live_monitoring(
    camera_id: Optional[int] = Query(None),
    window_minutes: int = Query(60, ge=5, le=24 * 30),
    bucket_seconds: int = Query(60, ge=10, le=3600),
    recent_limit: int = Query(8, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = VehicleRecognitionPipeline(db)
    monitoring = pipeline.get_live_monitoring(
        camera_id=camera_id,
        window_minutes=window_minutes,
        bucket_seconds=bucket_seconds,
        recent_limit=recent_limit,
    )
    return {"success": True, "monitoring": monitoring}


@router.get("/access/logs")
def get_vehicle_access_logs(
    camera_id: Optional[int] = Query(None),
    gate_id: Optional[str] = Query(None),
    plate_number: Optional[str] = Query(None),
    decision: Optional[str] = Query(None, pattern="^(allowed|denied|review_required|manual_override)?$"),
    direction: Optional[str] = Query(None, pattern="^(IN|OUT|UNKNOWN)?$"),
    from_hours: int = Query(24, ge=1, le=24 * 30),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = VehicleRecognitionPipeline(db)
    logs = pipeline.get_access_logs(
        camera_id=camera_id,
        gate_id=gate_id,
        plate_number=plate_number,
        decision=decision,
        direction=direction,
        from_hours=from_hours,
        skip=skip,
        limit=limit,
    )
    return {"success": True, "count": len(logs), "logs": logs}


@router.get("/access/alerts")
def get_vehicle_security_alerts(
    camera_id: Optional[int] = Query(None),
    resolution_status: Optional[str] = Query(None, pattern="^(open|in_review|resolved)?$"),
    severity_level: Optional[str] = Query(None, pattern="^(low|medium|high|critical)?$"),
    alert_type: Optional[str] = Query(None),
    from_hours: int = Query(72, ge=1, le=24 * 30),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = VehicleRecognitionPipeline(db)
    alerts = pipeline.get_security_alerts(
        camera_id=camera_id,
        resolution_status=resolution_status,
        severity_level=severity_level,
        alert_type=alert_type,
        from_hours=from_hours,
        skip=skip,
        limit=limit,
    )
    return {"success": True, "count": len(alerts), "alerts": alerts}


@router.post("/access/manual-override")
def apply_vehicle_manual_override(
    payload: ManualOverridePayload,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role = str(current_user.get("role", "")).strip().lower()
    if role not in {"admin", "operator"}:
        raise HTTPException(status_code=403, detail="Manual override requires operator or admin role")

    if payload.access_log_id is None and payload.event_id is None:
        raise HTTPException(status_code=400, detail="access_log_id or event_id is required")

    operator_id = current_user.get("user_id")
    if operator_id is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")

    pipeline = VehicleRecognitionPipeline(db)
    result = pipeline.apply_manual_override(
        access_log_id=payload.access_log_id,
        event_id=payload.event_id,
        operator_id=int(operator_id),
        operator_username=current_user.get("sub"),
        forced_decision=payload.forced_decision,
        note=payload.note,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Access log not found")

    write_audit_log(
        event_type="vehicle_access",
        action="manual_override",
        method="POST",
        path="/api/vehicle/access/manual-override",
        status_code=200,
        user_id=int(operator_id),
        username=current_user.get("sub"),
        details={
            "access_log_id": result.get("id"),
            "event_id": result.get("event_id"),
            "decision": result.get("decision"),
        },
    )

    return {"success": True, "override": result}
