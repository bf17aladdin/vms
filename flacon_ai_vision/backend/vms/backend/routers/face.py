from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_user
from vms.backend.models import FaceDetection
from vms.backend.routers.runtime_guard import ensure_manual_inference_allowed
from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline

router = APIRouter(prefix="/api/face", tags=["face"])


def _decode_base64_image(image_base64: str) -> bytes:
    payload = image_base64
    if "," in image_base64 and "base64" in image_base64.split(",", 1)[0]:
        payload = image_base64.split(",", 1)[1]
    return base64.b64decode(payload)


@router.post("/recognize")
async def recognize_face(
    camera_id: int = Form(...),
    zone_id: Optional[int] = Form(None),
    top_k: int = Form(5),
    persist: bool = Form(True),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_manual_inference_allowed("face.recognize")
    if file is None and not image_base64:
        raise HTTPException(status_code=400, detail="file or image_base64 is required")

    try:
        image_bytes = await file.read() if file is not None else _decode_base64_image(image_base64 or "")
        pipeline = FaceRecognitionPipeline(db)
        return pipeline.recognize_from_bytes(
            image_bytes=image_bytes,
            camera_id=camera_id,
            zone_id=zone_id,
            persist=bool(persist),
            top_k=max(1, min(int(top_k), 20)),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recognize-multi")
async def recognize_faces_multi(
    camera_id: int = Form(...),
    zone_id: Optional[int] = Form(None),
    top_k: int = Form(5),
    max_faces: int = Form(0),
    persist: bool = Form(True),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_manual_inference_allowed("face.recognize_multi")
    if file is None and not image_base64:
        raise HTTPException(status_code=400, detail="file or image_base64 is required")

    try:
        image_bytes = await file.read() if file is not None else _decode_base64_image(image_base64 or "")
        pipeline = FaceRecognitionPipeline(db)
        return pipeline.recognize_many_from_bytes(
            image_bytes=image_bytes,
            camera_id=camera_id,
            zone_id=zone_id,
            persist=bool(persist),
            top_k=max(1, min(int(top_k), 20)),
            max_faces=max(0, min(int(max_faces), 200)),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/enroll")
async def enroll_face(
    personnel_id: int = Form(...),
    pose_label: str = Form("front"),
    make_primary: bool = Form(False),
    allow_conflict: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file is None and not image_base64:
        raise HTTPException(status_code=400, detail="file or image_base64 is required")

    try:
        image_bytes = await file.read() if file is not None else _decode_base64_image(image_base64 or "")
        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.enroll_from_bytes(
            personnel_id=personnel_id,
            image_bytes=image_bytes,
            pose_label=pose_label.lower().strip() or "front",
            source="api_face_enroll",
            make_primary=bool(make_primary),
            allow_conflict=bool(allow_conflict),
            original_filename=file.filename if file is not None else None,
        )
        if not payload.get("success"):
            raise HTTPException(status_code=400, detail=payload.get("message", "Enrollment failed"))
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/personnel/{personnel_id}/images")
async def add_person_image(
    personnel_id: int,
    pose_label: str = Form("front"),
    make_primary: bool = Form(False),
    allow_conflict: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file is None and not image_base64:
        raise HTTPException(status_code=400, detail="file or image_base64 is required")

    try:
        image_bytes = await file.read() if file is not None else _decode_base64_image(image_base64 or "")
        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.enroll_from_bytes(
            personnel_id=personnel_id,
            image_bytes=image_bytes,
            pose_label=pose_label.lower().strip() or "front",
            source="api_face_dataset",
            make_primary=bool(make_primary),
            allow_conflict=bool(allow_conflict),
            original_filename=file.filename if file is not None else None,
        )
        if not payload.get("success"):
            raise HTTPException(status_code=400, detail=payload.get("message", "Failed to add image"))
        return payload
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/personnel/{personnel_id}/images")
def list_person_images(
    personnel_id: int,
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = FaceRecognitionPipeline(db)
    rows = pipeline.list_person_images(personnel_id=personnel_id, include_inactive=include_inactive)
    return {"success": True, "count": len(rows), "items": rows}


@router.patch("/personnel/{personnel_id}/images/{image_id}/primary")
def set_primary_person_image(
    personnel_id: int,
    image_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = FaceRecognitionPipeline(db)
    payload = pipeline.set_primary_image(personnel_id=personnel_id, face_image_id=image_id)
    if not payload.get("success"):
        message = str(payload.get("message", "Failed to update primary image"))
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message)
    return payload


@router.delete("/personnel/{personnel_id}/images/{image_id}")
def delete_person_image(
    personnel_id: int,
    image_id: int,
    delete_file: bool = Query(True),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = FaceRecognitionPipeline(db)
    payload = pipeline.delete_person_image(
        personnel_id=personnel_id,
        face_image_id=image_id,
        delete_file=bool(delete_file),
    )
    if not payload.get("success"):
        message = str(payload.get("message", "Failed to delete face image"))
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message)
    return payload


@router.get("/history")
def get_face_history(
    personnel_id: Optional[int] = Query(None),
    camera_id: Optional[int] = Query(None),
    track_id: Optional[int] = Query(None, ge=1),
    status: Optional[str] = Query(None, pattern="^(matched|unknown)?$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = FaceRecognitionPipeline(db)
    detections = pipeline.get_history(
        personnel_id=personnel_id,
        camera_id=camera_id,
        track_id=track_id,
        status=status,
        skip=skip,
        limit=limit,
    )
    return {"success": True, "count": len(detections), "detections": detections}


@router.delete("/history/{detection_id}")
def delete_face_detection(
    detection_id: int,
    allow_known: bool = Query(False),
    delete_image: bool = Query(True),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(FaceDetection).filter(FaceDetection.id == detection_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Face detection not found")

    if row.personnel_id is not None and not allow_known:
        raise HTTPException(
            status_code=400,
            detail="Only unknown detections can be deleted (set allow_known=true to override)",
        )

    image_deleted = False
    image_path = row.image_path
    db.delete(row)
    db.commit()

    if delete_image and image_path:
        try:
            image_file = Path(image_path)
            if not image_file.is_absolute():
                image_file = (Path.cwd() / image_file).resolve()
            if image_file.exists() and image_file.is_file():
                image_file.unlink(missing_ok=True)
                image_deleted = True
        except Exception:
            image_deleted = False

    return {
        "success": True,
        "deleted_id": detection_id,
        "image_deleted": image_deleted,
        "known_deleted": row.personnel_id is not None,
    }


@router.get("/statistics")
def get_face_statistics(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pipeline = FaceRecognitionPipeline(db)
    return {"success": True, "statistics": pipeline.get_statistics()}
