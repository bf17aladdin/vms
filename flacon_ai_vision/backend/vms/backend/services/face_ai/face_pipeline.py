from __future__ import annotations

import io
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

from .face_align import FaceAligner
from .face_detector import FaceDetection, FaceDetector
from .face_embedder import FaceEmbedder
from .face_matcher import FaceMatcher
from vms.backend.core.media_paths import to_public_media_path
from vms.backend.services.person_appearance import (
    appearance_similarity,
    build_appearance_embedding,
    extract_person_appearance,
    normalize_color,
    serialize_accessory_state,
    serialize_color,
)
from vms.backend.services.access_decision_service import AccessDecisionRequest, AccessDecisionService
from vms.backend.services.action_engine import ActionEngine
from vms.backend.services.unknown_detection_service import UnknownDetectionService


class FaceRecognitionPipeline:
    """Detect -> Align -> Embed -> Match -> Event -> History."""

    _components_lock = Lock()
    _tracking_lock = Lock()
    _detector: Optional[FaceDetector] = None
    _aligner: Optional[FaceAligner] = None
    _embedder: Optional[FaceEmbedder] = None
    _track_state_by_camera: Dict[int, Dict[int, Dict[str, Any]]] = {}
    _next_track_id_by_camera: Dict[int, int] = {}

    def __init__(self, db: Session):
        self.db = db
        self.detector, self.aligner, self.embedder = self._get_shared_components()
        self.matcher = FaceMatcher(db)
        self.unknown_detection_service = UnknownDetectionService(db)
        self.access_decision_service = AccessDecisionService(db)
        self.action_engine = ActionEngine(db)
        self.mask_score_threshold = float(os.getenv("FACE_MASK_SCORE_THRESHOLD", "0.5"))
        self.mask_match_threshold = float(os.getenv("FACE_MASK_MATCH_THRESHOLD", "0.52"))
        self.mask_switch_margin = float(os.getenv("FACE_MASK_SWITCH_MARGIN", "0.01"))
        self.try_upper_on_unknown = os.getenv("FACE_TRY_UPPER_ON_UNKNOWN", "true").lower() == "true"
        self.force_upper_face = os.getenv("FACE_FORCE_UPPER_FACE", "true").lower() == "true"
        self.upper_confidence_trigger = float(os.getenv("FACE_UPPER_CONFIDENCE_TRIGGER", "0.80"))
        self.track_max_age_sec = float(os.getenv("FACE_TRACK_MAX_AGE_SEC", "2.0"))
        self.track_iou_threshold = float(os.getenv("FACE_TRACK_IOU_THRESHOLD", "0.30"))
        self.track_center_distance_ratio = float(os.getenv("FACE_TRACK_CENTER_DISTANCE_RATIO", "1.50"))
        self.track_sticky_enabled = os.getenv("FACE_TRACK_STICKY_ENABLED", "true").lower() == "true"
        self.track_sticky_min_confidence = float(os.getenv("FACE_TRACK_STICKY_MIN_CONFIDENCE", "0.82"))
        self.track_sticky_unknown_floor = float(os.getenv("FACE_TRACK_STICKY_UNKNOWN_FLOOR", "0.48"))
        self.enroll_conflict_threshold = float(os.getenv("FACE_ENROLL_CONFLICT_THRESHOLD", "0.80"))
        self.enroll_min_quality = float(os.getenv("FACE_ENROLL_MIN_QUALITY", "0.30"))
        self.det_min_score_insight = float(os.getenv("FACE_DET_MIN_SCORE_INSIGHT", "0.45"))
        self.det_min_score_fallback = float(os.getenv("FACE_DET_MIN_SCORE_FALLBACK", "0.68"))
        self.det_min_aspect_ratio = float(os.getenv("FACE_DET_MIN_ASPECT_RATIO", "0.45"))
        self.det_max_aspect_ratio = float(os.getenv("FACE_DET_MAX_ASPECT_RATIO", "1.55"))
        self.history_image_mode = str(os.getenv("FACE_HISTORY_IMAGE_MODE", "crop")).strip().lower()
        self.history_crop_pad_ratio = float(os.getenv("FACE_HISTORY_CROP_PAD_RATIO", "0.22"))
        self.runtime_match_accept_floor = float(os.getenv("FACE_RUNTIME_MATCH_ACCEPT_FLOOR", "0.70"))

    def bind_db(self, db: Session) -> None:
        self.db = db
        self.matcher.db = db
        self.unknown_detection_service.db = db
        self.access_decision_service.db = db
        self.action_engine.db = db
        self.action_engine.unknown_detection_service.db = db

    @classmethod
    def _get_shared_components(cls) -> tuple[FaceDetector, FaceAligner, FaceEmbedder]:
        with cls._components_lock:
            if cls._detector is None:
                cls._detector = FaceDetector()
            if cls._aligner is None:
                cls._aligner = FaceAligner()
            if cls._embedder is None:
                cls._embedder = FaceEmbedder()
        return cls._detector, cls._aligner, cls._embedder

    def recognize_from_bytes(
        self,
        image_bytes: bytes,
        camera_id: int,
        zone_id: Optional[int] = None,
        persist: bool = True,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        frame = self._bytes_to_bgr(image_bytes)
        if frame is None:
            return {"success": False, "status": "error", "message": "Invalid image payload"}
        return self.recognize_from_frame(
            frame_bgr=frame,
            camera_id=camera_id,
            zone_id=zone_id,
            persist=persist,
            top_k=top_k,
            image_bytes=image_bytes,
        )

    def recognize_many_from_bytes(
        self,
        image_bytes: bytes,
        camera_id: int,
        zone_id: Optional[int] = None,
        persist: bool = True,
        top_k: int = 5,
        max_faces: int = 0,
    ) -> Dict[str, Any]:
        frame = self._bytes_to_bgr(image_bytes)
        if frame is None:
            return {"success": False, "status": "error", "message": "Invalid image payload", "faces": []}
        return self.recognize_many_from_frame(
            frame_bgr=frame,
            camera_id=camera_id,
            zone_id=zone_id,
            persist=persist,
            top_k=top_k,
            max_faces=max_faces,
            image_bytes=image_bytes,
        )

    def recognize_from_frame(
        self,
        frame_bgr: np.ndarray,
        camera_id: int,
        zone_id: Optional[int] = None,
        persist: bool = True,
        top_k: int = 5,
        image_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        payload = self.recognize_many_from_frame(
            frame_bgr=frame_bgr,
            camera_id=camera_id,
            zone_id=zone_id,
            persist=persist,
            top_k=top_k,
            max_faces=1,
            image_bytes=image_bytes,
        )
        if not payload.get("success"):
            return payload

        faces = payload.get("faces") or []
        if not faces:
            return {
                "success": False,
                "status": "no_face",
                "camera_id": camera_id,
                "zone_id": zone_id,
                "message": "No face detected",
            }
        return dict(faces[0])

    def recognize_many_from_frame(
        self,
        frame_bgr: np.ndarray,
        camera_id: int,
        zone_id: Optional[int] = None,
        persist: bool = True,
        top_k: int = 5,
        max_faces: int = 0,
        image_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        import time
        start_total = time.perf_counter()
        
        from vms.backend.models import Camera

        normalized_top_k = max(1, min(int(top_k), 20))
        normalized_max_faces = max(0, int(max_faces))
        
        # Measure detection time
        start_detection = time.perf_counter()
        detections = self.detector.detect(frame_bgr, max_faces=normalized_max_faces)
        detection_time_ms = (time.perf_counter() - start_detection) * 1000
        detections = [det for det in detections if self._passes_detection_quality(det)]
        
        if not detections:
            return {
                "success": False,
                "status": "no_face",
                "camera_id": camera_id,
                "zone_id": zone_id,
                "faces_count": 0,
                "matched_count": 0,
                "unknown_count": 0,
                "error_count": 0,
                "faces": [],
                "message": "No face detected",
                "performance": {
                    "detection_time_ms": round(detection_time_ms, 2),
                    "total_time_ms": round((time.perf_counter() - start_total) * 1000, 2)
                }
            }

        if image_bytes is None:
            image_bytes = self._frame_to_jpeg_bytes(frame_bgr)

        reference_time = datetime.utcnow()
        track_ids = self._assign_track_ids(
            camera_id=int(camera_id),
            detections=detections,
            reference_time=reference_time,
        )

        camera_exists: Optional[bool] = None
        if persist:
            camera_exists = self.db.query(Camera.id).filter(Camera.id == int(camera_id)).first() is not None

        faces: List[Dict[str, Any]] = []
        matched_count = 0
        unknown_count = 0
        error_count = 0
        for idx, detection in enumerate(detections):
            face_payload = self._recognize_detection(
                frame_bgr=frame_bgr,
                detection=detection,
                camera_id=camera_id,
                zone_id=zone_id,
                persist=persist,
                top_k=normalized_top_k,
                image_bytes=image_bytes,
                camera_exists=camera_exists,
                track_id=track_ids[idx] if idx < len(track_ids) else None,
            )
            face_payload["face_index"] = idx
            faces.append(face_payload)
            if face_payload.get("status") == "matched":
                matched_count += 1
            elif face_payload.get("status") == "unknown":
                unknown_count += 1
            else:
                error_count += 1

        if error_count == len(faces):
            status = "error"
            success = False
            message = "Face processing failed"
        elif error_count > 0:
            status = "partial"
            success = True
            message = "Face processing partially completed"
        else:
            status = "processed"
            success = True
            message = f"{len(faces)} face(s) processed"

        return {
            "success": success,
            "status": status,
            "camera_id": camera_id,
            "zone_id": zone_id,
            "faces_count": len(faces),
            "matched_count": matched_count,
            "unknown_count": unknown_count,
            "error_count": error_count,
            "faces": faces,
            "message": message,
            "performance": {
                "detection_time_ms": round(detection_time_ms, 2),
                "total_time_ms": round((time.perf_counter() - start_total) * 1000, 2)
            },
            "pipeline": {
                "detector_backend": self.detector.backend,
                "embedder_backend": self.embedder.backend,
                "matcher": self.matcher.backend,
            },
        }

    def _recognize_detection(
        self,
        *,
        frame_bgr: np.ndarray,
        detection: FaceDetection,
        camera_id: int,
        zone_id: Optional[int],
        persist: bool,
        top_k: int,
        image_bytes: bytes,
        camera_exists: Optional[bool],
        track_id: Optional[int],
    ) -> Dict[str, Any]:
        import time
        start_face = time.perf_counter()
        
        from vms.backend.models import FaceDetection as FaceDetectionModel

        aligned = self.aligner.align(frame_bgr, detection)
        mask_score = self._mask_occlusion_score(aligned.aligned_face)
        mask_likely = mask_score >= self.mask_score_threshold

        # Measure embedding time
        start_embed = time.perf_counter()
        embedding, embed_source = self.embedder.embed(aligned.aligned_face, detection=detection)
        embed_time_ms = (time.perf_counter() - start_embed) * 1000
        
        if embedding is None:
            return {
                "success": False,
                "status": "error",
                "camera_id": camera_id,
                "zone_id": zone_id,
                "track_id": track_id,
                "message": "Embedding extraction failed",
            }

        # Measure matching time
        start_match = time.perf_counter()
        match_payload = self.matcher.match(embedding, top_k=top_k)
        match_time_ms = (time.perf_counter() - start_match) * 1000
        
        selected_embedding = embedding
        selected_embed_source = embed_source
        selected_face_region = "full"
        upper_attempted = False
        upper_payload: Optional[Dict[str, Any]] = None

        full_matched = bool(match_payload.get("matched"))
        full_score = float(match_payload.get("best_score") or 0.0)
        should_try_upper = (
            mask_likely
            or (self.try_upper_on_unknown and not full_matched)
            or (self.force_upper_face and full_score < self.upper_confidence_trigger)
        )
        if should_try_upper:
            upper_attempted = True
            upper_face = self._extract_upper_face(aligned.aligned_face)
            if upper_face is not None:
                upper_embedding, upper_embed_source = self.embedder.embed(upper_face, detection=None)
                if upper_embedding is not None:
                    upper_threshold = self.mask_match_threshold if mask_likely else None
                    upper_payload = self.matcher.match(
                        upper_embedding,
                        top_k=top_k,
                        threshold_override=upper_threshold,
                    )
                    if self._prefer_upper_result(match_payload, upper_payload, mask_likely):
                        match_payload = upper_payload
                        selected_embedding = upper_embedding
                        selected_face_region = "upper"
                        selected_embed_source = f"{upper_embed_source}_upper"

        matched = bool(match_payload.get("matched"))
        best = match_payload.get("best")
        confidence = float(match_payload.get("best_score") or 0.0)
        match_quality = self._match_quality(confidence)
        personnel_id = int(best["personnel_id"]) if matched and best else None
        personnel_name = str(best["full_name"]) if matched and best else "UNKNOWN"
        is_blacklisted = bool(best["is_blacklisted"]) if matched and best else False
        is_authorized = bool(best["is_active"] and not best["is_blacklisted"]) if matched and best else None
        sticky_identity_applied = False
        low_confidence_rejected = False

        if (
            not matched
            and track_id is not None
            and self.track_sticky_enabled
            and confidence >= self.track_sticky_unknown_floor
        ):
            sticky_identity = self._load_track_identity(camera_id=int(camera_id), track_id=int(track_id))
            if sticky_identity is not None:
                sticky_confidence = float(sticky_identity.get("confidence", 0.0))
                sticky_personnel_id = int(sticky_identity.get("personnel_id") or 0)
                if sticky_personnel_id > 0 and sticky_confidence >= self.track_sticky_min_confidence:
                    matched = True
                    sticky_identity_applied = True
                    personnel_id = sticky_personnel_id
                    personnel_name = str(sticky_identity.get("personnel_name") or f"Personnel #{sticky_personnel_id}")
                    is_blacklisted = bool(sticky_identity.get("is_blacklisted", False))
                    is_authorized = bool(sticky_identity.get("is_authorized", False))
                    match_quality = self._match_quality(max(confidence, sticky_confidence))

        if (
            matched
            and (not sticky_identity_applied)
            and confidence < float(self.runtime_match_accept_floor)
        ):
            matched = False
            low_confidence_rejected = True
            personnel_id = None
            personnel_name = "UNKNOWN"
            is_blacklisted = False
            is_authorized = None
            match_quality = self._match_quality(confidence)

        saved_image_bytes = image_bytes
        if self.history_image_mode != "frame":
            crop = self._extract_history_crop(frame_bgr=frame_bgr, detection=detection)
            if crop is not None and crop.size > 0:
                saved_image_bytes = self._frame_to_jpeg_bytes(crop)

        image_path = self._save_image(
            image_bytes=saved_image_bytes,
            folder="face_detections",
            prefix=f"cam_{camera_id}_{'known' if matched else 'unknown'}",
        )
        face_bbox = self._bbox_to_dict(detection)
        appearance = extract_person_appearance(
            image_path=image_path,
            face_bbox=face_bbox,
        )

        detected_at = datetime.utcnow()
        decision_request = AccessDecisionRequest(
            detection_type="face",
            confidence=confidence,
            camera_id=camera_id,
            detected_at=detected_at,
            personnel_id=personnel_id if matched else None,
            metadata={
                "track_id": track_id,
                "face_region": selected_face_region,
                "mask_likely": mask_likely,
                "detector_source": detection.source,
            },
        )
        decision_result = self.access_decision_service.evaluate(decision_request)
        detection_id: Optional[int] = None
        decision_event_id: Optional[int] = None
        unknown_detection_id: Optional[int] = None
        persistence_warning: Optional[str] = None

        if persist:
            if camera_exists is False:
                persistence_warning = (
                    f"camera_id={camera_id} not found in cameras table; detection not persisted"
                )
            else:
                try:
                    row = FaceDetectionModel(
                        personnel_id=personnel_id,
                        camera_id=camera_id,
                        zone_id=zone_id,
                        track_id=track_id,
                        face_encoding=selected_embedding.tolist(),
                        confidence=confidence,
                        match_quality=match_quality,
                        image_path=image_path,
                        face_bbox=face_bbox,
                        person_bbox=appearance.person_bbox,
                        appearance_top_color=appearance.top_color,
                        appearance_bottom_color=appearance.bottom_color,
                        has_backpack=appearance.has_backpack,
                        has_hat=appearance.has_hat,
                        appearance_embedding=appearance.embedding,
                        detected_at=detected_at,
                        is_authorized=is_authorized,
                        is_blacklisted=is_blacklisted,
                        notes=(
                            f"{'Matched known personnel' if matched else 'Unknown face'}"
                            f" [track_id={track_id}, region={selected_face_region}, "
                            f"mask_likely={mask_likely}, sticky={sticky_identity_applied}, "
                            f"low_conf_reject={low_confidence_rejected}]"
                        ),
                    )
                    self.db.add(row)
                    self.db.commit()
                    self.db.refresh(row)
                    detection_id = int(row.id)
                    detected_at = row.detected_at or detected_at
                except IntegrityError as e:
                    self.db.rollback()
                    persistence_warning = f"Face detection not persisted due to DB integrity constraint: {e.orig or e}"
                except Exception as e:
                    self.db.rollback()
                    return {
                        "success": False,
                        "status": "error",
                        "camera_id": camera_id,
                        "zone_id": zone_id,
                        "track_id": track_id,
                        "message": f"Failed to persist face detection: {e}",
                    }

        if persist and camera_exists is not False and (detection_id is not None or persistence_warning is None):
            action_result = self.action_engine.handle_decision(
                request=decision_request,
                result=decision_result,
                camera_id=camera_id,
                zone_id=zone_id,
                frame_bgr=frame_bgr,
                bbox=detection.bbox,
                confidence=confidence,
                snapshot_path=image_path,
                source_table="face_detections" if detection_id is not None else None,
                source_detection_id=detection_id,
                label=personnel_name if matched else None,
                extra_data={
                    "track_id": track_id,
                    "face_region": selected_face_region,
                    "mask_likely": mask_likely,
                },
                detected_at=detected_at,
            )
            decision_event_id = action_result.get("event_id")
            unknown_detection_id = action_result.get("unknown_detection_id")

        message = "Face matched" if matched else "Face unknown"
        if persistence_warning:
            message = f"{message} (non-persistent)"
        if sticky_identity_applied:
            message = f"{message} (track_sticky)"

        if matched and track_id is not None and personnel_id is not None:
            self._save_track_identity(
                camera_id=int(camera_id),
                track_id=int(track_id),
                personnel_id=int(personnel_id),
                personnel_name=personnel_name,
                confidence=float(confidence),
                is_authorized=bool(is_authorized),
                is_blacklisted=bool(is_blacklisted),
            )

        return {
            "success": True,
            "status": "matched" if matched else "unknown",
            "label": personnel_name if matched else "UNKNOWN",
            "personnel_id": personnel_id,
            "personnel_name": personnel_name,
            "confidence": confidence,
            "match_quality": match_quality,
            "is_authorized": is_authorized,
            "is_blacklisted": is_blacklisted,
            "camera_id": camera_id,
            "zone_id": zone_id,
            "track_id": track_id,
            "sticky_identity_applied": sticky_identity_applied,
            "low_confidence_rejected": low_confidence_rejected,
            "detected_at": detected_at.isoformat(),
            "detection_id": detection_id,
            "event_id": decision_event_id,
            "decision_event_id": decision_event_id,
            "unknown_detection_id": unknown_detection_id,
            "image_path": image_path,
            "bbox": face_bbox,
            "person_bbox": appearance.person_bbox,
            "top_color": appearance.top_color,
            "bottom_color": appearance.bottom_color,
            "backpack": serialize_accessory_state(appearance.has_backpack),
            "hat": serialize_accessory_state(appearance.has_hat),
            "has_appearance_embedding": bool(appearance.embedding),
            "face_region": selected_face_region,
            "mask_likely": mask_likely,
            "mask_score": round(mask_score, 4),
            "pose": {
                "yaw": aligned.yaw,
                "pitch": aligned.pitch,
                "roll": aligned.roll,
            },
            "pipeline": {
                "detector": detection.source,
                "aligner": aligned.source,
                "embedder": selected_embed_source,
                "matcher": self.matcher.backend,
                "upper_attempted": upper_attempted,
                "upper_result_available": upper_payload is not None,
            },
            "top_matches": match_payload.get("top_matches", []),
            "decision": decision_result.decision,
            "reason_code": decision_result.reason_code,
            "explanation": decision_result.explanation,
            "checks": [check.to_dict() for check in decision_result.checks],
            "unknown_queue_action": decision_result.unknown_queue_action,
            "access_decision": decision_result.to_dict(),
            "needs_add_person": not matched,
            "add_person_action": {
                "enabled": not matched,
                "label": "Add Person",
                "ui_hint": "show_add_person_button",
            },
            "persisted": detection_id is not None,
            "persistence_warning": persistence_warning,
            "performance": {
                "embed_time_ms": round(embed_time_ms, 2),
                "match_time_ms": round(match_time_ms, 2),
                "total_face_time_ms": round((time.perf_counter() - start_face) * 1000, 2)
            },
            "message": message,
        }

    def _create_unknown_face_event(
        self,
        *,
        camera_id: int,
        zone_id: Optional[int],
        confidence: float,
        detected_at: datetime,
        snapshot_path: Optional[str],
        bbox: Dict[str, int],
        track_id: Optional[int] = None,
    ) -> Optional[int]:
        from vms.backend.models import Camera, Event

        try:
            camera = self.db.query(Camera).filter(Camera.id == int(camera_id)).first()
            site_id = int(camera.site_id) if camera and camera.site_id is not None else None
            creator_id = int(camera.owner_id) if camera and camera.owner_id is not None else 1

            event = Event(
                camera_id=int(camera_id),
                zone_id=int(zone_id) if zone_id is not None else None,
                site_id=site_id,
                creator_id=creator_id,
                event_type="person",
                severity="warning",
                decision="review_required",
                description="Unknown face detected. Add Person suggested.",
                detected_objects={
                    "face": 1,
                    "status": "unknown",
                    "bbox": bbox,
                    "track_id": track_id,
                },
                confidence=float(max(0.0, min(1.0, confidence))),
                snapshot_path=snapshot_path,
                detected_at=detected_at,
                extra_data={
                    "pipeline": "face_recognition",
                    "face_status": "unknown",
                    "needs_add_person": True,
                    "track_id": track_id,
                },
            )
            self.db.add(event)
            self.db.commit()
            self.db.refresh(event)
            return int(event.id)
        except Exception:
            self.db.rollback()
            return None

    def enroll_from_bytes(
        self,
        personnel_id: int,
        image_bytes: bytes,
        pose_label: str = "front",
        source: str = "manual",
        make_primary: bool = False,
        allow_conflict: bool = False,
        original_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        from vms.backend.models import FaceEncoding, FaceImage, Personnel

        person = self.db.query(Personnel).filter(Personnel.id == personnel_id).first()
        if not person:
            return {"success": False, "message": f"Personnel {personnel_id} not found"}

        frame = self._bytes_to_bgr(image_bytes)
        if frame is None:
            return {"success": False, "message": "Invalid image payload"}

        detections = self.detector.detect(frame, max_faces=0)
        if not detections:
            return {"success": False, "message": "No face detected in enrollment image"}
        if len(detections) > 1:
            return {
                "success": False,
                "message": (
                    f"Enrollment image must contain exactly one face (detected={len(detections)}). "
                    "Please crop to a single person."
                ),
            }

        detection = detections[0]
        aligned = self.aligner.align(frame, detection)
        embedding, embed_source = self.embedder.embed(aligned.aligned_face, detection=detection)
        if embedding is None:
            return {"success": False, "message": "Failed to compute embedding"}

        upper_embedding: Optional[np.ndarray] = None
        upper_embed_source: Optional[str] = None
        upper_face = self._extract_upper_face(aligned.aligned_face)
        if upper_face is not None:
            maybe_upper_embedding, maybe_upper_source = self.embedder.embed(upper_face, detection=None)
            if (
                maybe_upper_embedding is not None
                and int(maybe_upper_embedding.shape[0]) == int(embedding.shape[0])
            ):
                upper_embedding = maybe_upper_embedding
                upper_embed_source = maybe_upper_source

        image_path = self._save_image(
            image_bytes=image_bytes,
            folder="known_faces",
            prefix=f"personnel_{personnel_id}_{pose_label}",
            original_filename=original_filename,
        )

        quality = self._quality_score(detection=detection, yaw=aligned.yaw, pitch=aligned.pitch, roll=aligned.roll)
        if quality < self.enroll_min_quality:
            return {
                "success": False,
                "message": (
                    f"Enrollment image quality too low ({quality:.3f}). "
                    f"Minimum required: {self.enroll_min_quality:.3f}"
                ),
                "quality_score": quality,
            }

        conflict = self._detect_enrollment_conflict(personnel_id=personnel_id, embedding=embedding)
        if conflict is not None and not allow_conflict:
            return {
                "success": False,
                "message": (
                    "Enrollment blocked: this photo looks like another enrolled person. "
                    "Check selected identity or set allow_conflict=true to override."
                ),
                "conflict": conflict,
            }

        try:
            has_primary = (
                self.db.query(FaceEncoding)
                .filter(FaceEncoding.personnel_id == personnel_id, FaceEncoding.is_primary.is_(True), FaceEncoding.is_active.is_(True))
                .count()
            ) > 0
            is_primary = bool(make_primary or not has_primary)

            if is_primary:
                (
                    self.db.query(FaceEncoding)
                    .filter(FaceEncoding.personnel_id == personnel_id, FaceEncoding.is_primary.is_(True))
                    .update({"is_primary": False}, synchronize_session=False)
                )

            face_image = FaceImage(
                personnel_id=personnel_id,
                image_path=image_path,
                pose_label=pose_label,
                yaw=aligned.yaw,
                pitch=aligned.pitch,
                roll=aligned.roll,
                quality_score=quality,
                detector_score=float(detection.score),
                is_reference=is_primary,
                source=source,
            )
            self.db.add(face_image)
            self.db.flush()

            pgvector_dim = int(os.getenv("FACE_PGVECTOR_DIM", "512"))
            embedding_vector_value = embedding.tolist() if int(embedding.shape[0]) == pgvector_dim else None

            face_encoding_kwargs = {
                "personnel_id": personnel_id,
                "face_image_id": face_image.id,
                "encoding_vector": embedding.tolist(),
                "is_primary": is_primary,
                "quality_score": quality,
                "model_name": embed_source,
                "embedding_dim": int(embedding.shape[0]),
                "is_active": True,
                "detector_score": float(detection.score),
            }
            if hasattr(FaceEncoding, "embedding_vector"):
                face_encoding_kwargs["embedding_vector"] = embedding_vector_value

            face_encoding = FaceEncoding(**face_encoding_kwargs)
            self.db.add(face_encoding)

            upper_face_encoding_id: Optional[int] = None
            if upper_embedding is not None:
                upper_embedding_vector_value = (
                    upper_embedding.tolist()
                    if int(upper_embedding.shape[0]) == pgvector_dim
                    else None
                )
                upper_encoding_kwargs = {
                    "personnel_id": personnel_id,
                    "face_image_id": face_image.id,
                    "encoding_vector": upper_embedding.tolist(),
                    "is_primary": False,
                    "quality_score": max(0.0, float(quality) * 0.95),
                    "model_name": f"{(upper_embed_source or embed_source)}_upper",
                    "embedding_dim": int(upper_embedding.shape[0]),
                    "is_active": True,
                    "detector_score": float(detection.score),
                }
                if hasattr(FaceEncoding, "embedding_vector"):
                    upper_encoding_kwargs["embedding_vector"] = upper_embedding_vector_value
                upper_face_encoding = FaceEncoding(**upper_encoding_kwargs)
                self.db.add(upper_face_encoding)
                self.db.flush()
                upper_face_encoding_id = int(upper_face_encoding.id)

            person.photo_path = image_path
            person.face_embedding = np.asarray(embedding, dtype=np.float32).tobytes()
            person.face_encodings = embedding.tolist()
            self.db.add(person)

            self.db.commit()
            self.matcher.invalidate()

            return {
                "success": True,
                "message": "Face enrolled successfully",
                "personnel_id": personnel_id,
                "personnel_name": person.full_name,
                "face_image_id": face_image.id,
                "face_encoding_id": face_encoding.id,
                "face_encoding_upper_id": upper_face_encoding_id,
                "image_path": image_path,
                "pose_label": pose_label,
                "quality_score": quality,
                "is_primary": is_primary,
                "allow_conflict": bool(allow_conflict),
                "conflict_warning": conflict,
                "embedding_dim": int(embedding.shape[0]),
                "embedding_variants": 2 if upper_embedding is not None else 1,
                "pipeline": {
                    "detector": detection.source,
                    "aligner": aligned.source,
                    "embedder": embed_source,
                    "upper_embedder": upper_embed_source,
                },
            }
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Enrollment transaction failed: {e}"}

    def list_person_images(self, personnel_id: int, include_inactive: bool = False) -> List[Dict[str, Any]]:
        from vms.backend.models import FaceEncoding, FaceImage

        query = self.db.query(FaceImage).filter(FaceImage.personnel_id == personnel_id)
        rows = query.order_by(FaceImage.created_at.desc()).all()

        out: List[Dict[str, Any]] = []
        for image in rows:
            encoding = (
                self.db.query(FaceEncoding)
                .filter(FaceEncoding.face_image_id == image.id)
                .order_by(FaceEncoding.created_at.desc())
                .first()
            )
            if encoding is not None and not include_inactive and not bool(getattr(encoding, "is_active", True)):
                continue

            image_path = str(image.image_path or "").replace("\\", "/")
            image_url = to_public_media_path(image_path)

            out.append(
                {
                    "id": image.id,
                    "personnel_id": image.personnel_id,
                    "image_path": image_url,
                    "image_url": image_url,
                    "pose_label": image.pose_label,
                    "yaw": float(image.yaw or 0.0),
                    "pitch": float(image.pitch or 0.0),
                    "roll": float(image.roll or 0.0),
                    "quality_score": float(image.quality_score or 0.0),
                    "detector_score": float(image.detector_score or 0.0),
                    "is_reference": bool(image.is_reference),
                    "source": image.source,
                    "created_at": image.created_at.isoformat() if image.created_at else None,
                    "face_encoding_id": encoding.id if encoding else None,
                    "model_name": encoding.model_name if encoding else None,
                    "is_active": bool(encoding.is_active) if encoding is not None else None,
                }
            )
        return out

    def set_primary_image(self, personnel_id: int, face_image_id: int) -> Dict[str, Any]:
        from vms.backend.models import FaceEncoding, FaceImage, Personnel

        image = (
            self.db.query(FaceImage)
            .filter(FaceImage.id == face_image_id, FaceImage.personnel_id == personnel_id)
            .first()
        )
        if image is None:
            return {"success": False, "message": "Face image not found for personnel"}

        try:
            (
                self.db.query(FaceImage)
                .filter(FaceImage.personnel_id == personnel_id)
                .update({"is_reference": False}, synchronize_session=False)
            )
            image.is_reference = True
            self.db.add(image)

            (
                self.db.query(FaceEncoding)
                .filter(FaceEncoding.personnel_id == personnel_id)
                .update({"is_primary": False}, synchronize_session=False)
            )

            target_encoding = (
                self.db.query(FaceEncoding)
                .filter(
                    FaceEncoding.personnel_id == personnel_id,
                    FaceEncoding.face_image_id == face_image_id,
                    FaceEncoding.is_active.is_(True),
                )
                .order_by(FaceEncoding.created_at.asc())
                .first()
            )
            if target_encoding is not None:
                target_encoding.is_primary = True
                self.db.add(target_encoding)

            person = self.db.query(Personnel).filter(Personnel.id == personnel_id).first()
            if person is not None:
                person.photo_path = image.image_path
                self.db.add(person)

            self.db.commit()
            self.matcher.invalidate()
            return {
                "success": True,
                "personnel_id": personnel_id,
                "face_image_id": face_image_id,
                "face_encoding_id": int(target_encoding.id) if target_encoding is not None else None,
                "message": "Primary face image updated",
            }
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Failed to set primary image: {e}"}

    def delete_person_image(
        self,
        personnel_id: int,
        face_image_id: int,
        delete_file: bool = True,
    ) -> Dict[str, Any]:
        from vms.backend.models import FaceEncoding, FaceImage, Personnel

        image = (
            self.db.query(FaceImage)
            .filter(FaceImage.id == face_image_id, FaceImage.personnel_id == personnel_id)
            .first()
        )
        if image is None:
            return {"success": False, "message": "Face image not found for personnel"}

        image_path = str(image.image_path or "")
        linked_encodings = (
            self.db.query(FaceEncoding)
            .filter(
                FaceEncoding.personnel_id == personnel_id,
                FaceEncoding.face_image_id == face_image_id,
            )
            .all()
        )
        linked_encoding_ids = [int(enc.id) for enc in linked_encodings]

        try:
            for enc in linked_encodings:
                self.db.delete(enc)
            self.db.delete(image)
            self.db.flush()

            remaining_images = (
                self.db.query(FaceImage)
                .filter(FaceImage.personnel_id == personnel_id)
                .order_by(FaceImage.created_at.desc())
                .all()
            )

            if remaining_images and not any(bool(img.is_reference) for img in remaining_images):
                remaining_images[0].is_reference = True
                self.db.add(remaining_images[0])

            active_encodings = (
                self.db.query(FaceEncoding)
                .filter(
                    FaceEncoding.personnel_id == personnel_id,
                    FaceEncoding.is_active.is_(True),
                )
                .order_by(FaceEncoding.created_at.desc())
                .all()
            )
            if active_encodings:
                for enc in active_encodings:
                    enc.is_primary = False
                    self.db.add(enc)

                ref_image_ids = {img.id for img in remaining_images if bool(img.is_reference)}
                preferred = next(
                    (enc for enc in active_encodings if enc.face_image_id in ref_image_ids),
                    active_encodings[0],
                )
                preferred.is_primary = True
                self.db.add(preferred)

            person = self.db.query(Personnel).filter(Personnel.id == personnel_id).first()
            if person is not None:
                reference_image = next((img for img in remaining_images if bool(img.is_reference)), None)
                fallback_image = remaining_images[0] if remaining_images else None
                selected_image = reference_image or fallback_image
                person.photo_path = selected_image.image_path if selected_image is not None else None
                if not remaining_images:
                    person.face_embedding = None
                    person.face_encodings = None
                self.db.add(person)

            self.db.commit()
            self.matcher.invalidate()
        except Exception as e:
            self.db.rollback()
            return {"success": False, "message": f"Failed to delete face image: {e}"}

        image_deleted = False
        if delete_file and image_path:
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
            "personnel_id": personnel_id,
            "face_image_id": face_image_id,
            "deleted_encoding_ids": linked_encoding_ids,
            "image_deleted": image_deleted,
            "message": "Face image deleted",
        }

    def get_history(
        self,
        personnel_id: Optional[int] = None,
        camera_id: Optional[int] = None,
        track_id: Optional[int] = None,
        status: Optional[str] = None,
        top_color: Optional[str] = None,
        bottom_color: Optional[str] = None,
        backpack: Optional[bool | str] = None,
        hat: Optional[bool | str] = None,
        limit: int = 50,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        from vms.backend.models import FaceDetection

        query = self.db.query(FaceDetection)
        if personnel_id is not None:
            query = query.filter(FaceDetection.personnel_id == personnel_id)
        if camera_id is not None:
            query = query.filter(FaceDetection.camera_id == camera_id)
        if track_id is not None:
            query = query.filter(FaceDetection.track_id == track_id)
        if status == "unknown":
            query = query.filter(FaceDetection.personnel_id.is_(None))
        elif status == "matched":
            query = query.filter(FaceDetection.personnel_id.isnot(None))
        if top_color is not None:
            normalized_top = normalize_color(top_color)
            if normalized_top == "unknown":
                query = query.filter(
                    (FaceDetection.appearance_top_color.is_(None))
                    | (FaceDetection.appearance_top_color == "")
                    | (FaceDetection.appearance_top_color == "unknown")
                )
            else:
                query = query.filter(FaceDetection.appearance_top_color == normalized_top)
        if bottom_color is not None:
            normalized_bottom = normalize_color(bottom_color)
            if normalized_bottom == "unknown":
                query = query.filter(
                    (FaceDetection.appearance_bottom_color.is_(None))
                    | (FaceDetection.appearance_bottom_color == "")
                    | (FaceDetection.appearance_bottom_color == "unknown")
                )
            else:
                query = query.filter(FaceDetection.appearance_bottom_color == normalized_bottom)
        if backpack is not None:
            if backpack == "unknown":
                query = query.filter(FaceDetection.has_backpack.is_(None))
            else:
                query = query.filter(FaceDetection.has_backpack.is_(bool(backpack)))
        if hat is not None:
            if hat == "unknown":
                query = query.filter(FaceDetection.has_hat.is_(None))
            else:
                query = query.filter(FaceDetection.has_hat.is_(bool(hat)))

        rows = query.order_by(FaceDetection.detected_at.desc()).offset(max(0, skip)).limit(limit).all()

        out: List[Dict[str, Any]] = []
        for row in rows:
            label = row.personnel.full_name if row.personnel else "UNKNOWN"
            image_path = str(row.image_path or "").replace("\\", "/")
            image_url = to_public_media_path(image_path)

            out.append(
                {
                    "id": row.id,
                    "personnel_id": row.personnel_id,
                    "personnel_name": label,
                    "name": label,
                    "label": label,
                    "camera_id": row.camera_id,
                    "zone_id": row.zone_id,
                    "track_id": row.track_id,
                    "confidence": float(row.confidence or 0.0),
                    "match_quality": row.match_quality or "low",
                    "is_authorized": row.is_authorized,
                    "is_blacklisted": row.is_blacklisted,
                    "image_path": image_url,
                    "image_url": image_url,
                    "bbox": row.face_bbox,
                    "person_bbox": row.person_bbox,
                    "top_color": serialize_color(row.appearance_top_color),
                    "bottom_color": serialize_color(row.appearance_bottom_color),
                    "backpack": serialize_accessory_state(row.has_backpack),
                    "hat": serialize_accessory_state(row.has_hat),
                    "has_appearance_embedding": bool(self._resolve_appearance_embedding(row)),
                    "detected_at": row.detected_at.isoformat() if row.detected_at else None,
                    "status": "matched" if row.personnel_id is not None else "unknown",
                    "notes": row.notes,
                }
            )
        return out

    def get_statistics(self) -> Dict[str, Any]:
        from vms.backend.models import FaceDetection, FaceEncoding, FaceImage, Personnel

        total_detections = self.db.query(FaceDetection).count()
        recognized = self.db.query(FaceDetection).filter(FaceDetection.personnel_id.isnot(None)).count()
        total_face_images = self.db.query(FaceImage).count()
        active_embeddings = self.db.query(FaceEncoding).filter(FaceEncoding.is_active.is_(True)).count()
        enrolled_personnel = self.db.query(Personnel).filter(Personnel.face_embedding.isnot(None)).count()
        appearance_rows = self.db.query(
            FaceDetection.appearance_top_color,
            FaceDetection.appearance_bottom_color,
            FaceDetection.has_backpack,
            FaceDetection.has_hat,
        ).all()
        top_colors = Counter(
            serialize_color(row.appearance_top_color) for row in appearance_rows
        )
        bottom_colors = Counter(
            serialize_color(row.appearance_bottom_color) for row in appearance_rows
        )
        backpack_detected = sum(1 for row in appearance_rows if row.has_backpack is True)
        hat_detected = sum(1 for row in appearance_rows if row.has_hat is True)

        return {
            "total_detections": total_detections,
            "recognized": recognized,
            "unknown": max(0, total_detections - recognized),
            "registered_personnel": enrolled_personnel,
            "total_face_images": total_face_images,
            "active_embeddings": active_embeddings,
            "recognition_rate": round((recognized / total_detections) * 100, 2) if total_detections else 0.0,
            "appearance_top_colors": dict(top_colors),
            "appearance_bottom_colors": dict(bottom_colors),
            "backpack_detected": backpack_detected,
            "hat_detected": hat_detected,
            "pipeline": {
                "detector_backend": self.detector.backend,
                "embedder_backend": self.embedder.backend,
                "matcher": self.matcher.backend,
            },
        }

    def find_similar_detections(
        self,
        detection_id: int,
        *,
        camera_id: Optional[int] = None,
        cross_camera_only: bool = False,
        limit: int = 10,
    ) -> Dict[str, Any]:
        from vms.backend.models import FaceDetection

        source = (
            self.db.query(FaceDetection)
            .filter(FaceDetection.id == int(detection_id))
            .first()
        )
        if source is None:
            raise ValueError(f"Face detection #{detection_id} not found")

        source_embedding = self._resolve_appearance_embedding(source)
        if not source_embedding:
            return {
                "source": self._serialize_history_row(source),
                "matches": [],
            }

        query = self.db.query(FaceDetection).filter(FaceDetection.id != int(detection_id))
        if camera_id is not None:
            query = query.filter(FaceDetection.camera_id == int(camera_id))
        if cross_camera_only:
            query = query.filter(FaceDetection.camera_id != int(source.camera_id))

        rows = query.order_by(FaceDetection.detected_at.desc()).limit(max(limit * 12, 50)).all()
        matches: list[dict[str, Any]] = []
        for row in rows:
            candidate_embedding = self._resolve_appearance_embedding(row)
            similarity = appearance_similarity(source_embedding, candidate_embedding)
            if similarity <= 0:
                continue

            payload = self._serialize_history_row(row)
            payload["similarity"] = round(similarity, 4)
            payload["same_camera"] = bool(row.camera_id == source.camera_id)
            matches.append(payload)

        matches.sort(key=lambda item: float(item.get("similarity") or 0.0), reverse=True)
        return {
            "source": self._serialize_history_row(source),
            "matches": matches[:limit],
        }

    def _serialize_history_row(self, row) -> Dict[str, Any]:
        label = row.personnel.full_name if row.personnel else "UNKNOWN"
        image_path = str(row.image_path or "").replace("\\", "/")
        image_url = to_public_media_path(image_path)

        return {
            "id": row.id,
            "personnel_id": row.personnel_id,
            "personnel_name": label,
            "name": label,
            "label": label,
            "camera_id": row.camera_id,
            "zone_id": row.zone_id,
            "track_id": row.track_id,
            "confidence": float(row.confidence or 0.0),
            "match_quality": row.match_quality or "low",
            "is_authorized": row.is_authorized,
            "is_blacklisted": row.is_blacklisted,
            "image_path": image_url,
            "image_url": image_url,
            "bbox": row.face_bbox,
            "person_bbox": row.person_bbox,
            "top_color": serialize_color(row.appearance_top_color),
            "bottom_color": serialize_color(row.appearance_bottom_color),
            "backpack": serialize_accessory_state(row.has_backpack),
            "hat": serialize_accessory_state(row.has_hat),
            "has_appearance_embedding": bool(self._resolve_appearance_embedding(row)),
            "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            "status": "matched" if row.personnel_id is not None else "unknown",
            "notes": row.notes,
        }

    @staticmethod
    def _resolve_appearance_embedding(row) -> Optional[list[float]]:
        if row.appearance_embedding:
            return row.appearance_embedding
        if (
            row.appearance_top_color
            or row.appearance_bottom_color
            or row.has_backpack is not None
            or row.has_hat is not None
        ):
            return build_appearance_embedding(
                top_color=row.appearance_top_color,
                bottom_color=row.appearance_bottom_color,
                has_backpack=row.has_backpack,
                has_hat=row.has_hat,
            )
        return None

    def _bytes_to_bgr(self, image_bytes: bytes) -> Optional[np.ndarray]:
        if not image_bytes:
            return None
        if _HAS_CV2:
            nparr = np.frombuffer(image_bytes, np.uint8)
            bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if bgr is not None:
                return bgr
        try:
            rgb = np.asarray(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
            return rgb[:, :, ::-1].copy()
        except Exception:
            return None

    def _frame_to_jpeg_bytes(self, frame_bgr: np.ndarray) -> bytes:
        if _HAS_CV2:
            ok, encoded = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if ok:
                return encoded.tobytes()
        rgb = frame_bgr[:, :, ::-1]
        img = Image.fromarray(rgb)
        with io.BytesIO() as buf:
            img.save(buf, format="JPEG", quality=90)
            return buf.getvalue()

    def _extract_history_crop(
        self,
        *,
        frame_bgr: np.ndarray,
        detection: FaceDetection,
    ) -> Optional[np.ndarray]:
        h, w = frame_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return None

        x, y, bw, bh = detection.bbox
        pad_ratio = max(0.0, min(1.0, float(self.history_crop_pad_ratio)))
        pad_x = int(max(2, round(float(bw) * pad_ratio)))
        pad_y = int(max(2, round(float(bh) * pad_ratio)))

        x1 = max(0, int(x) - pad_x)
        y1 = max(0, int(y) - pad_y)
        x2 = min(w, int(x + bw) + pad_x)
        y2 = min(h, int(y + bh) + pad_y)
        if x2 <= x1 or y2 <= y1:
            return None
        return frame_bgr[y1:y2, x1:x2].copy()

    def _passes_detection_quality(self, detection: FaceDetection) -> bool:
        x, y, bw, bh = detection.bbox
        if bw <= 0 or bh <= 0:
            return False

        aspect_ratio = float(bw) / float(max(1, bh))
        if aspect_ratio < float(self.det_min_aspect_ratio) or aspect_ratio > float(self.det_max_aspect_ratio):
            return False

        source = str(detection.source or "").strip().lower()
        score = float(detection.score or 0.0)
        min_score = (
            float(self.det_min_score_insight)
            if source.startswith("insightface")
            else float(self.det_min_score_fallback)
        )
        if score < min_score:
            return False

        if detection.landmarks is not None:
            try:
                kps = np.asarray(detection.landmarks, dtype=np.float32)
                if kps.ndim == 2 and kps.shape[0] >= 5 and kps.shape[1] >= 2:
                    xs = kps[:, 0]
                    ys = kps[:, 1]
                    # Reject collapsed landmarks often produced by hard false positives.
                    if (float(xs.max() - xs.min()) < (float(bw) * 0.15)) or (
                        float(ys.max() - ys.min()) < (float(bh) * 0.15)
                    ):
                        return False
            except Exception:
                return False

        return True

    def _save_image(
        self,
        image_bytes: bytes,
        folder: str,
        prefix: str,
        original_filename: Optional[str] = None,
    ) -> str:
        base_dir = Path("data") / folder
        base_dir.mkdir(parents=True, exist_ok=True)

        suffix = ".jpg"
        if original_filename:
            ext = Path(original_filename).suffix.lower()
            if ext in {".jpg", ".jpeg", ".png"}:
                suffix = ext

        filename = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}{suffix}"
        path = base_dir / filename
        path.write_bytes(image_bytes)
        return str(path).replace("\\", "/")

    def _bbox_to_dict(self, detection: FaceDetection) -> Dict[str, int]:
        x, y, w, h = detection.bbox
        return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}

    def _assign_track_ids(
        self,
        *,
        camera_id: int,
        detections: List[FaceDetection],
        reference_time: datetime,
    ) -> List[int]:
        if not detections:
            return []

        now_ts = float(reference_time.timestamp())
        max_age_sec = max(0.1, float(self.track_max_age_sec))
        iou_threshold = max(0.0, min(1.0, float(self.track_iou_threshold)))
        center_ratio_threshold = max(0.1, float(self.track_center_distance_ratio))

        assigned_track_ids: List[int] = []
        with self._tracking_lock:
            tracks = self._track_state_by_camera.setdefault(int(camera_id), {})
            expired_ids = [
                tid
                for tid, state in tracks.items()
                if (now_ts - float(state.get("last_seen_ts", 0.0))) > max_age_sec
            ]
            for tid in expired_ids:
                tracks.pop(tid, None)

            unmatched_track_ids = set(tracks.keys())
            for detection in detections:
                bbox = self._bbox_to_dict(detection)
                best_track_id: Optional[int] = None
                best_score = float("-inf")
                bbox_diag = max(1.0, self._bbox_diag(bbox))
                bbox_center = self._bbox_center(bbox)

                for candidate_track_id in list(unmatched_track_ids):
                    state = tracks.get(candidate_track_id)
                    if state is None:
                        continue
                    previous_bbox = state.get("bbox") or {}
                    iou = self._bbox_iou_dict(previous_bbox, bbox)
                    prev_diag = max(1.0, self._bbox_diag(previous_bbox))
                    prev_center = self._bbox_center(previous_bbox)
                    center_distance = ((bbox_center[0] - prev_center[0]) ** 2 + (bbox_center[1] - prev_center[1]) ** 2) ** 0.5
                    distance_ratio = center_distance / max(bbox_diag, prev_diag)

                    if iou < iou_threshold and distance_ratio > center_ratio_threshold:
                        continue

                    score = iou - (0.15 * distance_ratio)
                    if score > best_score:
                        best_score = score
                        best_track_id = int(candidate_track_id)

                if best_track_id is None:
                    next_track_id = self._next_track_id_by_camera.get(int(camera_id), 0) + 1
                    self._next_track_id_by_camera[int(camera_id)] = next_track_id
                    best_track_id = int(next_track_id)
                else:
                    unmatched_track_ids.discard(best_track_id)

                previous_state = tracks.get(best_track_id, {})
                previous_state["bbox"] = bbox
                previous_state["last_seen_ts"] = now_ts
                tracks[best_track_id] = previous_state
                assigned_track_ids.append(best_track_id)

            self._track_state_by_camera[int(camera_id)] = tracks
        return assigned_track_ids

    def _bbox_center(self, bbox: Dict[str, Any]) -> Tuple[float, float]:
        x = float(bbox.get("x", 0))
        y = float(bbox.get("y", 0))
        w = float(bbox.get("w", 0))
        h = float(bbox.get("h", 0))
        return (x + (w / 2.0), y + (h / 2.0))

    def _bbox_diag(self, bbox: Dict[str, Any]) -> float:
        w = max(0.0, float(bbox.get("w", 0)))
        h = max(0.0, float(bbox.get("h", 0)))
        return (w * w + h * h) ** 0.5

    def _bbox_iou_dict(self, a: Dict[str, Any], b: Dict[str, Any]) -> float:
        ax1 = float(a.get("x", 0))
        ay1 = float(a.get("y", 0))
        ax2 = ax1 + max(0.0, float(a.get("w", 0)))
        ay2 = ay1 + max(0.0, float(a.get("h", 0)))
        bx1 = float(b.get("x", 0))
        by1 = float(b.get("y", 0))
        bx2 = bx1 + max(0.0, float(b.get("w", 0)))
        by2 = by1 + max(0.0, float(b.get("h", 0)))

        inter_x1 = max(ax1, bx1)
        inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)

        inter_w = max(0.0, inter_x2 - inter_x1)
        inter_h = max(0.0, inter_y2 - inter_y1)
        inter_area = inter_w * inter_h
        if inter_area <= 0:
            return 0.0

        area_a = max(0.0, (ax2 - ax1) * (ay2 - ay1))
        area_b = max(0.0, (bx2 - bx1) * (by2 - by1))
        denom = area_a + area_b - inter_area
        if denom <= 0:
            return 0.0
        return float(inter_area / denom)

    def _load_track_identity(self, *, camera_id: int, track_id: int) -> Optional[Dict[str, Any]]:
        with self._tracking_lock:
            tracks = self._track_state_by_camera.get(int(camera_id), {})
            state = tracks.get(int(track_id))
            if not state:
                return None
            now_ts = datetime.utcnow().timestamp()
            last_id_ts = float(state.get("identity_last_seen_ts", 0.0))
            if (now_ts - last_id_ts) > max(0.1, float(self.track_max_age_sec)):
                return None
            if not state.get("personnel_id"):
                return None
            return {
                "personnel_id": int(state.get("personnel_id") or 0),
                "personnel_name": state.get("personnel_name"),
                "confidence": float(state.get("identity_confidence") or 0.0),
                "is_authorized": bool(state.get("is_authorized", False)),
                "is_blacklisted": bool(state.get("is_blacklisted", False)),
            }

    def _save_track_identity(
        self,
        *,
        camera_id: int,
        track_id: int,
        personnel_id: int,
        personnel_name: str,
        confidence: float,
        is_authorized: bool,
        is_blacklisted: bool,
    ) -> None:
        with self._tracking_lock:
            tracks = self._track_state_by_camera.setdefault(int(camera_id), {})
            state = tracks.get(int(track_id), {})
            state["personnel_id"] = int(personnel_id)
            state["personnel_name"] = str(personnel_name)
            state["identity_confidence"] = float(max(0.0, min(1.0, confidence)))
            state["is_authorized"] = bool(is_authorized)
            state["is_blacklisted"] = bool(is_blacklisted)
            state["identity_last_seen_ts"] = float(datetime.utcnow().timestamp())
            tracks[int(track_id)] = state
            self._track_state_by_camera[int(camera_id)] = tracks

    def _detect_enrollment_conflict(
        self,
        *,
        personnel_id: int,
        embedding: np.ndarray,
    ) -> Optional[Dict[str, Any]]:
        match_payload = self.matcher.match(embedding, top_k=3)
        best = match_payload.get("best")
        if not best:
            return None
        best_score = float(match_payload.get("best_score") or 0.0)
        best_personnel_id = int(best.get("personnel_id") or 0)
        if best_personnel_id <= 0 or best_personnel_id == int(personnel_id):
            return None
        if best_score < self.enroll_conflict_threshold:
            return None
        return {
            "target_personnel_id": int(personnel_id),
            "matched_personnel_id": best_personnel_id,
            "matched_personnel_name": str(best.get("full_name") or f"Personnel #{best_personnel_id}"),
            "score": best_score,
            "threshold": self.enroll_conflict_threshold,
        }

    def _match_quality(self, confidence: float) -> str:
        if confidence >= 0.9:
            return "high"
        if confidence >= 0.75:
            return "medium"
        return "low"

    def _quality_score(self, detection: FaceDetection, yaw: float, pitch: float, roll: float) -> float:
        pose_penalty = min(1.0, (abs(yaw) + abs(pitch) + abs(roll)) / 120.0)
        score = float(detection.score) * (1.0 - 0.6 * pose_penalty)
        return float(max(0.0, min(1.0, score)))

    def _extract_upper_face(self, aligned_face_bgr: np.ndarray) -> Optional[np.ndarray]:
        if aligned_face_bgr is None or aligned_face_bgr.size == 0:
            return None
        h, w = aligned_face_bgr.shape[:2]
        cut = int(h * 0.62)
        cut = max(16, min(h - 1, cut))
        upper = aligned_face_bgr[:cut, :]
        if upper.size == 0:
            return None

        if _HAS_CV2:
            return cv2.resize(upper, (w, h), interpolation=cv2.INTER_LINEAR)

        ys = np.linspace(0, upper.shape[0] - 1, h).astype(int)
        xs = np.linspace(0, upper.shape[1] - 1, w).astype(int)
        return upper[np.ix_(ys, xs)]

    def _mask_occlusion_score(self, aligned_face_bgr: np.ndarray) -> float:
        if aligned_face_bgr is None or aligned_face_bgr.size == 0:
            return 0.0

        if _HAS_CV2:
            gray = cv2.cvtColor(aligned_face_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
            lap = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
        else:
            gray = np.mean(aligned_face_bgr, axis=2).astype(np.float32)
            lap = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))

        h = gray.shape[0]
        split = max(8, min(h - 8, int(h * 0.55)))
        upper = gray[:split, :]
        lower = gray[split:, :]
        upper_lap = lap[:split, :]
        lower_lap = lap[split:, :]
        if upper.size == 0 or lower.size == 0:
            return 0.0

        tex_upper = float(np.var(upper))
        tex_lower = float(np.var(lower))
        edge_upper = float(np.mean(upper_lap))
        edge_lower = float(np.mean(lower_lap))

        tex_ratio = tex_lower / (tex_upper + 1e-6)
        edge_ratio = edge_lower / (edge_upper + 1e-6)
        score_tex = float(np.clip(1.0 - tex_ratio, 0.0, 1.0))
        score_edge = float(np.clip(1.0 - edge_ratio, 0.0, 1.0))
        return float(np.clip(0.6 * score_tex + 0.4 * score_edge, 0.0, 1.0))

    def _prefer_upper_result(
        self,
        full_payload: Dict[str, Any],
        upper_payload: Optional[Dict[str, Any]],
        mask_likely: bool,
    ) -> bool:
        if not upper_payload:
            return False

        full_matched = bool(full_payload.get("matched"))
        upper_matched = bool(upper_payload.get("matched"))
        full_score = float(full_payload.get("best_score") or 0.0)
        upper_score = float(upper_payload.get("best_score") or 0.0)

        if upper_matched and not full_matched:
            return True
        if upper_matched and full_matched:
            margin = self.mask_switch_margin if mask_likely else max(self.mask_switch_margin, 0.03)
            return upper_score >= (full_score + margin)
        if mask_likely and not full_matched and upper_score >= (full_score + 0.02):
            return True
        return False
