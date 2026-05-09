from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from vms.backend.core.database import get_db
from vms.backend.core.media_paths import to_public_media_path
from vms.backend.core.security import get_current_admin, get_current_user
from vms.backend.core.time_utils import utc_now_naive_iso
from vms.backend.models import FaceDetection, FaceImage, Personnel
from vms.backend.routers.runtime_guard import ensure_manual_inference_allowed
from vms.backend.services.camera_service import CameraService
from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline
from vms.backend.services.stream_service import StreamService

router = APIRouter(prefix="/api/facial", tags=["facial"])


def _image_url(image_path: Optional[str]) -> Optional[str]:
    return to_public_media_path(image_path)


def _resolve_personnel(
    db: Session,
    *,
    personnel_id: Optional[int],
    name: Optional[str],
) -> Personnel:
    if personnel_id is not None:
        person = db.query(Personnel).filter(Personnel.id == personnel_id).first()
        if person is None:
            raise HTTPException(status_code=404, detail=f"Personnel {personnel_id} not found")
        return person

    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="name or personnel_id is required")

    person = (
        db.query(Personnel)
        .filter(Personnel.full_name == normalized_name)
        .order_by(Personnel.id.asc())
        .first()
    )
    if person is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f'No personnel found for name "{normalized_name}". '
                "Use personnel_id for deterministic enrollment."
            ),
        )
    return person


def _serialize_known_face(image: FaceImage, person: Personnel) -> dict[str, Any]:
    public_path = _image_url(image.image_path)
    return {
        "id": int(image.id),
        "face_image_id": int(image.id),
        "personnel_id": int(person.id),
        "name": str(person.full_name or "").strip() or f"Personnel #{person.id}",
        "path": public_path,
        "image_url": public_path,
        "pose_label": image.pose_label,
        "is_reference": bool(image.is_reference),
        "quality_score": float(image.quality_score or 0.0),
        "created_at": image.created_at.isoformat() if image.created_at else None,
    }


def _serialize_legacy_detection(payload: dict[str, Any]) -> dict[str, Any]:
    label = str(payload.get("personnel_name") or payload.get("label") or "UNKNOWN")
    is_known = payload.get("status") == "matched"
    personnel_id = payload.get("personnel_id")
    return {
        "detection_id": payload.get("detection_id"),
        "bbox": payload.get("bbox"),
        "person_bbox": payload.get("person_bbox"),
        "is_known": bool(is_known),
        "person_id": int(personnel_id) if personnel_id is not None else None,
        "name": label,
        "status": payload.get("status"),
        "confidence": float(payload.get("confidence") or 0.0),
        "match_quality": payload.get("match_quality"),
        "processing_time": 0.0,
        "top_color": payload.get("top_color"),
        "bottom_color": payload.get("bottom_color"),
        "backpack": payload.get("backpack"),
        "hat": payload.get("hat"),
        "detected_at": payload.get("detected_at"),
    }


@router.get("/known-faces", response_model=dict)
def list_known_faces(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rows = (
            db.query(FaceImage, Personnel)
            .join(Personnel, FaceImage.personnel_id == Personnel.id)
            .order_by(FaceImage.created_at.desc(), FaceImage.id.desc())
            .offset(max(0, skip))
            .limit(max(1, min(int(limit), 500)))
            .all()
        )
        faces = [_serialize_known_face(image, person) for image, person in rows]
        return {
            "count": len(faces),
            "faces": faces,
            "message": "Known faces retrieved successfully",
            "pipeline": "FaceRecognitionPipeline",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/register-face", response_model=dict)
def register_face(
    name: Optional[str] = None,
    personnel_id: Optional[int] = None,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    try:
        person = _resolve_personnel(db, personnel_id=personnel_id, name=name)
        image_bytes = file.file.read()
        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.enroll_from_bytes(
            personnel_id=int(person.id),
            image_bytes=image_bytes,
            pose_label="front",
            source="api_facial_register",
            make_primary=True,
            original_filename=file.filename,
        )
        if not bool(payload.get("success")):
            raise HTTPException(status_code=400, detail=str(payload.get("message") or "Face registration failed"))
        return {
            "face_id": payload.get("face_image_id"),
            "face_image_id": payload.get("face_image_id"),
            "personnel_id": int(person.id),
            "name": payload.get("personnel_name") or person.full_name,
            "encoding_status": payload.get("message") or "success",
            "message": "Face registered successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/detect-faces/{camera_id}", response_model=dict)
def detect_faces_in_camera(
    camera_id: int,
    confidence: float = 0.7,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_manual_inference_allowed("facial.detect_faces_in_camera")
    try:
        camera = CameraService.get_camera(db, camera_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        stream_source = CameraService.resolve_camera_stream_source(db, camera_id)
        image_bytes = StreamService.get_camera_thumbnail(camera_id, stream_source)
        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.recognize_many_from_bytes(
            image_bytes=image_bytes,
            camera_id=camera_id,
            zone_id=None,
            persist=False,
            top_k=max(1, min(int(round(max(confidence, 0.1) * 10)), 10)),
            max_faces=0,
        )
        detections = [_serialize_legacy_detection(face) for face in (payload.get("faces") or [])]
        return {
            "camera_id": camera_id,
            "detections_count": len(detections),
            "detections": detections,
            "timestamp": utc_now_naive_iso(),
            "message": payload.get("message") or "Faces processed",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recognize-image", response_model=dict)
def recognize_faces_in_image(
    file: UploadFile = File(...),
    confidence: float = 0.7,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_manual_inference_allowed("facial.recognize_image")
    try:
        image_bytes = file.file.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Fichier image vide")

        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.recognize_many_from_bytes(
            image_bytes=image_bytes,
            camera_id=0,
            zone_id=None,
            persist=False,
            top_k=max(1, min(int(round(max(confidence, 0.1) * 10)), 10)),
            max_faces=0,
        )
        detections = [_serialize_legacy_detection(face) for face in (payload.get("faces") or [])]
        return {
            "detections_count": len(detections),
            "detections": detections,
            "timestamp": utc_now_naive_iso(),
            "message": payload.get("message") or "Faces processed",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/faces/{face_id}", response_model=dict)
def delete_known_face(
    face_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    try:
        face_image = db.query(FaceImage).filter(FaceImage.id == face_id).first()
        if face_image is None:
            raise HTTPException(status_code=404, detail="Face not found")

        pipeline = FaceRecognitionPipeline(db)
        payload = pipeline.delete_person_image(
            personnel_id=int(face_image.personnel_id),
            face_image_id=int(face_image.id),
            delete_file=True,
        )
        if not bool(payload.get("success")):
            raise HTTPException(status_code=400, detail=str(payload.get("message") or "Failed to delete face"))
        return {
            "face_id": face_id,
            "message": "Face deleted successfully",
            "deleted_encoding_ids": payload.get("deleted_encoding_ids") or [],
            "image_deleted": bool(payload.get("image_deleted")),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/events", response_model=dict)
def get_facial_events(
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        rows = (
            db.query(FaceDetection)
            .order_by(FaceDetection.detected_at.desc(), FaceDetection.id.desc())
            .offset(max(0, skip))
            .limit(max(1, min(int(limit), 500)))
            .all()
        )

        events = []
        for row in rows:
            person = row.personnel
            events.append(
                {
                    "id": int(row.id),
                    "detection_id": int(row.id),
                    "personnel_id": int(row.personnel_id) if row.personnel_id is not None else None,
                    "name": person.full_name if person is not None else "UNKNOWN",
                    "status": "matched" if row.personnel_id is not None else "unknown",
                    "camera_id": int(row.camera_id),
                    "zone_id": int(row.zone_id) if row.zone_id is not None else None,
                    "confidence": float(row.confidence or 0.0),
                    "match_quality": row.match_quality,
                    "image_url": _image_url(row.image_path),
                    "detected_at": row.detected_at.isoformat() if row.detected_at else None,
                }
            )

        return {
            "count": len(events),
            "events": events,
            "message": "Facial events retrieved successfully",
            "pipeline": "FaceRecognitionPipeline",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
