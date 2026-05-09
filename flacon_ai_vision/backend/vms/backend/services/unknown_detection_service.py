from __future__ import annotations

import hashlib
import io
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from vms.backend.core.media_paths import to_public_media_path

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False


class UnknownDetectionService:
    """Store unknown detections (face/vehicle) using cropped screenshots."""

    _dedupe_lock = Lock()
    _recent_hashes: Dict[str, float] = {}

    def __init__(self, db: Session):
        self.db = db
        self.min_confidence = float(os.getenv("UNKNOWN_DETECTION_MIN_CONF", "0.45"))
        self.cooldown_sec = float(os.getenv("UNKNOWN_DETECTION_COOLDOWN_SEC", "10"))
        self.crop_size = int(os.getenv("UNKNOWN_DETECTION_CROP_SIZE", "256"))
        self.jpeg_quality = int(os.getenv("UNKNOWN_DETECTION_JPEG_QUALITY", "85"))

    def capture_from_frame(
        self,
        *,
        detection_type: str,
        frame_bgr: np.ndarray,
        bbox: Optional[Tuple[int, int, int, int]],
        camera_id: int,
        confidence: float,
        zone_id: Optional[int] = None,
        source_table: Optional[str] = None,
        source_detection_id: Optional[int] = None,
        notes: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from vms.backend.models import UnknownDetection

        normalized_type = str(detection_type or "").strip().lower()
        if normalized_type not in {"face", "vehicle"}:
            return {"saved": False, "reason": "invalid_detection_type"}

        score = float(max(0.0, min(1.0, confidence)))
        if score < self.min_confidence:
            return {"saved": False, "reason": "low_confidence"}

        if frame_bgr is None or not hasattr(frame_bgr, "shape"):
            return {"saved": False, "reason": "invalid_frame"}

        crop = self._extract_crop(frame_bgr=frame_bgr, bbox=bbox)
        if crop is None or crop.size == 0:
            return {"saved": False, "reason": "empty_crop"}

        image_bytes = self._crop_to_jpeg_bytes(crop)
        if not image_bytes:
            return {"saved": False, "reason": "encode_failed"}

        sha256 = hashlib.sha256(image_bytes).hexdigest()
        dedupe_key = f"{normalized_type}:{int(camera_id)}:{sha256}"
        if self._is_in_cooldown(dedupe_key):
            return {"saved": False, "reason": "cooldown_deduped", "image_hash": sha256}

        image_path = self._save_crop(
            image_bytes=image_bytes,
            detection_type=normalized_type,
            camera_id=int(camera_id),
            image_hash=sha256,
        )

        try:
            row = UnknownDetection(
                detection_type=normalized_type,
                image_path=image_path,
                image_hash=sha256,
                camera_id=int(camera_id),
                zone_id=int(zone_id) if zone_id is not None else None,
                source_table=str(source_table or ""),
                source_detection_id=int(source_detection_id) if source_detection_id is not None else None,
                confidence=score,
                bbox=self._bbox_to_dict(bbox),
                is_resolved=False,
                is_ignored=False,
                notes=notes,
                extra_data=metadata or {},
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            self._emit_unknown_created(row=row)
            return {
                "saved": True,
                "id": int(row.id),
                "image_path": image_path,
                "image_hash": sha256,
            }
        except Exception:
            self.db.rollback()
            return {"saved": False, "reason": "db_error", "image_hash": sha256}

    def _extract_crop(
        self,
        *,
        frame_bgr: np.ndarray,
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> Optional[np.ndarray]:
        h, w = frame_bgr.shape[:2]
        if h <= 0 or w <= 0:
            return None

        if bbox is None:
            return frame_bgr.copy()

        x, y, bw, bh = bbox
        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(w, int(x + bw))
        y2 = min(h, int(y + bh))
        if x2 <= x1 or y2 <= y1:
            return frame_bgr.copy()
        return frame_bgr[y1:y2, x1:x2].copy()

    def _crop_to_jpeg_bytes(self, crop_bgr: np.ndarray) -> bytes:
        normalized = crop_bgr
        target = max(64, min(512, int(self.crop_size)))
        if _HAS_CV2:
            normalized = cv2.resize(normalized, (target, target), interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode(
                ".jpg",
                normalized,
                [int(cv2.IMWRITE_JPEG_QUALITY), max(60, min(98, int(self.jpeg_quality)))],
            )
            if ok:
                return encoded.tobytes()

        rgb = normalized[:, :, ::-1]
        img = Image.fromarray(rgb)
        resized = img.resize((target, target))
        with io.BytesIO() as buf:
            resized.save(buf, format="JPEG", quality=max(60, min(98, int(self.jpeg_quality))))
            return buf.getvalue()

    def _save_crop(
        self,
        *,
        image_bytes: bytes,
        detection_type: str,
        camera_id: int,
        image_hash: str,
    ) -> str:
        base_dir = Path("data") / "unknown_detections" / detection_type
        base_dir.mkdir(parents=True, exist_ok=True)
        filename = (
            f"cam_{camera_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}_"
            f"{image_hash[:12]}.jpg"
        )
        path = base_dir / filename
        path.write_bytes(image_bytes)
        return str(path).replace("\\", "/")

    def _is_in_cooldown(self, key: str) -> bool:
        now_ts = datetime.utcnow().timestamp()
        with self._dedupe_lock:
            last_seen = self._recent_hashes.get(key)
            if last_seen is not None and (now_ts - float(last_seen)) <= self.cooldown_sec:
                return True
            self._recent_hashes[key] = now_ts

            # Cleanup old entries opportunistically.
            threshold = now_ts - (self.cooldown_sec * 3)
            stale_keys = [k for k, ts in self._recent_hashes.items() if float(ts) < threshold]
            for stale in stale_keys:
                self._recent_hashes.pop(stale, None)
            return False

    def _bbox_to_dict(self, bbox: Optional[Tuple[int, int, int, int]]) -> Optional[Dict[str, int]]:
        if bbox is None:
            return None
        x, y, w, h = bbox
        return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}

    def _to_media_url(self, path: Optional[str]) -> Optional[str]:
        return to_public_media_path(path)

    def _emit_unknown_created(self, *, row: Any) -> None:
        try:
            from vms.backend.routers.ws import broadcast_api_event_sync

            broadcast_api_event_sync(
                "unknown_created",
                {
                    "id": int(row.id),
                    "detection_type": str(row.detection_type),
                    "camera_id": int(row.camera_id),
                    "zone_id": int(row.zone_id) if row.zone_id is not None else None,
                    "confidence": float(row.confidence or 0.0),
                    "image_path": str(row.image_path or ""),
                    "image_url": self._to_media_url(str(row.image_path or "")),
                    "source_table": str(row.source_table or ""),
                    "source_detection_id": int(row.source_detection_id)
                    if row.source_detection_id is not None
                    else None,
                    "bbox": row.bbox,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "is_resolved": bool(row.is_resolved),
                    "is_ignored": bool(row.is_ignored),
                },
            )
        except Exception:
            # Broadcasting must never block capture pipeline persistence.
            return
