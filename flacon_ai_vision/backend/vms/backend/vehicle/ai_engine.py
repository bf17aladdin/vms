from __future__ import annotations

import io
import os
import re
import time
from threading import Lock
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    cv2 = None
    _HAS_CV2 = False

try:
    from ultralytics import YOLO  # type: ignore

    _HAS_YOLO = True
except Exception:
    YOLO = None
    _HAS_YOLO = False

from vms.backend.services.vehicle_ai.plate_normalizer import PlateNormalizationResult, PlateNormalizer
from vms.backend.services.vehicle_ai.plate_reader import PlateReadResult, PlateReader
from vms.backend.services.vehicle_ai.plate_type_classifier import PlateTypeClassifier


class VehicleAIEngine:
    """ANPR extension over YOLOv8 detector: vehicle bbox + plate OCR + type + color."""

    _DEFAULT_VEHICLE_CLASS_IDS = {2, 3, 5, 7}  # car, motorcycle, bus, truck

    def __init__(self):
        if not _HAS_YOLO:
            raise RuntimeError("ultralytics is not installed")

        self.model_name = os.getenv("VEHICLE_AI_ENGINE_MODEL", "yolov8n.pt").strip() or "yolov8n.pt"
        self.device = (
            os.getenv("VEHICLE_AI_ENGINE_DEVICE", "").strip()
            or os.getenv("VEHICLE_AI_DEVICE", "").strip()
            or os.getenv("AI_DEVICE", "").strip()
            or "auto"
        )
        self.predict_device = self._resolve_predict_device(self.device)
        self.default_conf = float(os.getenv("VEHICLE_AI_ENGINE_CONF", "0.25"))
        self.default_iou = float(os.getenv("VEHICLE_AI_ENGINE_IOU", "0.45"))
        self.default_max_det = int(os.getenv("VEHICLE_AI_ENGINE_MAX_DET", "100"))
        self.default_imgsz = int(os.getenv("VEHICLE_AI_ENGINE_IMGSZ", "640"))
        self.vehicle_class_ids = self._parse_vehicle_class_ids(
            os.getenv("VEHICLE_AI_ENGINE_VEHICLE_CLASS_IDS", "2,3,5,7")
        )
        self.plate_only_fallback_enabled = os.getenv("VEHICLE_ANPR_PLATE_ONLY_FALLBACK", "true").strip().lower() == "true"
        self.plate_fallback_rois = max(1, int(os.getenv("VEHICLE_ANPR_PLATE_FALLBACK_ROIS", "2")))

        self.military_keywords = self._parse_csv_upper(
            os.getenv(
                "VEHICLE_ANPR_MILITARY_KEYWORDS",
                "MIL,ARMY,ARMEE,DEFENSE,FORCE,GENDARMERIE",
            )
        )
        self.civil_keywords = self._parse_csv_upper(
            os.getenv(
                "VEHICLE_ANPR_CIVIL_KEYWORDS",
                "TN,TUNIS,CIVIL",
            )
        )
        self.military_patterns = self._compile_patterns(
            self._parse_csv(os.getenv("VEHICLE_ANPR_MILITARY_REGEX", r"(^|\W)(MIL|ARMY|DEFENSE)($|\W),^M[0-9A-Z]{2,8}$"))
        )
        self.civil_patterns = self._compile_patterns(
            self._parse_csv(
                os.getenv("VEHICLE_ANPR_CIVIL_REGEX", r"(^|\W)(TN|TUNIS)($|\W),^[0-9]{2,4}[A-Z]{1,3}[0-9]{1,4}$")
            )
        )

        self.model = YOLO(self.model_name)
        if self.predict_device != "cpu":
            try:
                self.model.to(self.predict_device)
            except Exception:
                # Keep default device chosen by ultralytics.
                pass

        self.plate_reader = PlateReader()
        self.plate_normalizer = PlateNormalizer()
        self.min_plate_overlap_ratio = max(
            0.0,
            min(1.0, float(os.getenv("VEHICLE_ANPR_PLATE_OVERLAP_MIN_RATIO", "0.65"))),
        )
        self.min_plate_vertical_ratio = max(
            0.0,
            min(1.0, float(os.getenv("VEHICLE_ANPR_PLATE_VERTICAL_MIN_RATIO", "0.30"))),
        )

    def detect(
        self,
        frame_bgr: np.ndarray,
        *,
        confidence: Optional[float] = None,
        iou_threshold: Optional[float] = None,
        max_detections: Optional[int] = None,
        vehicle_only: bool = True,
        plate_only_fallback: Optional[bool] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        if frame_bgr is None or frame_bgr.size == 0:
            return self._empty_response("Invalid image payload")

        conf = float(self.default_conf if confidence is None else confidence)
        iou = float(self.default_iou if iou_threshold is None else iou_threshold)
        max_det = int(self.default_max_det if max_detections is None else max_detections)
        conf = max(0.0, min(1.0, conf))
        iou = max(0.0, min(1.0, iou))
        max_det = max(1, min(1000, max_det))
        fallback_enabled = self.plate_only_fallback_enabled if plate_only_fallback is None else bool(plate_only_fallback)

        started_at = time.perf_counter()
        try:
            results = self.model.predict(
                source=frame_bgr,
                verbose=False,
                conf=conf,
                iou=iou,
                max_det=max_det,
                imgsz=self.default_imgsz,
                device=self.predict_device,
            )
        except Exception:
            if self.predict_device == "cpu":
                raise
            self.predict_device = "cpu"
            results = self.model.predict(
                source=frame_bgr,
                verbose=False,
                conf=conf,
                iou=iou,
                max_det=max_det,
                imgsz=self.default_imgsz,
                device=self.predict_device,
            )
        infer_ms = (time.perf_counter() - started_at) * 1000.0

        classifier = PlateTypeClassifier(db) if db is not None else None
        vehicles = self._extract_vehicle_rows(
            frame_bgr=frame_bgr,
            results=results,
            vehicle_only=vehicle_only,
            max_detections=max_det,
            classifier=classifier,
        )
        fallback_used = False
        fallback_attempted = False
        fallback_reason: Optional[str] = None
        if not vehicles and fallback_enabled:
            fallback_attempted = True
            if self.plate_reader.backend == "none":
                fallback_reason = "ocr_backend_unavailable"
            fallback_row = self._build_plate_only_fallback_row(frame_bgr=frame_bgr, classifier=classifier)
            if fallback_row is not None:
                vehicles = [fallback_row]
                fallback_used = True
                fallback_reason = "ocr_success"
            elif fallback_reason is None:
                fallback_reason = "no_plate_text_found"

        return {
            "success": True,
            "message": "Detection completed",
            "model": self.model_name,
            "backend": "yolov8+anpr",
            "device": str(self.predict_device),
            "image_shape": {
                "height": int(frame_bgr.shape[0]),
                "width": int(frame_bgr.shape[1]),
                "channels": int(frame_bgr.shape[2]) if frame_bgr.ndim == 3 else 1,
            },
            "params": {
                "confidence": conf,
                "iou_threshold": iou,
                "max_detections": max_det,
                "vehicle_only": bool(vehicle_only),
                "plate_only_fallback": bool(fallback_enabled),
            },
            "pipeline": {
                "detector": "yolov8",
                "ocr": self.plate_reader.backend,
                "plate_classifier": "registry+rules" if classifier is not None else "rules",
            },
            "plate_only_fallback_attempted": bool(fallback_attempted),
            "plate_only_fallback_used": bool(fallback_used),
            "plate_only_fallback_reason": fallback_reason,
            "vehicles_count": len(vehicles),
            "vehicles": vehicles,
            # Backward-compatible aliases for existing frontend/debug consumers.
            "detections_count": len(vehicles),
            "detections": vehicles,
            "inference_ms": round(float(infer_ms), 3),
        }

    def detect_vehicles(
        self,
        frame: np.ndarray,
        *,
        confidence: Optional[float] = None,
        iou_threshold: Optional[float] = None,
        max_detections: Optional[int] = None,
        vehicle_only: bool = True,
        plate_only_fallback: Optional[bool] = None,
        db: Optional[Session] = None,
    ) -> List[Dict[str, Any]]:
        payload = self.detect(
            frame,
            confidence=confidence,
            iou_threshold=iou_threshold,
            max_detections=max_detections,
            vehicle_only=vehicle_only,
            plate_only_fallback=plate_only_fallback,
            db=db,
        )
        return list(payload.get("vehicles") or [])

    def _extract_vehicle_rows(
        self,
        *,
        frame_bgr: np.ndarray,
        results: Sequence[Any],
        vehicle_only: bool,
        max_detections: int,
        classifier: Optional[PlateTypeClassifier],
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            names = getattr(result, "names", None) or getattr(self.model, "names", None) or {}
            for box in boxes:
                try:
                    class_id = int(float(box.cls[0]))
                    confidence_score = float(box.conf[0])
                    if vehicle_only and class_id not in self.vehicle_class_ids:
                        continue
                    x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                    if x2 <= x1 or y2 <= y1:
                        continue
                except Exception:
                    continue

                plate_result = self._read_plate(frame_bgr=frame_bgr, vehicle_bbox_xyxy=(x1, y1, x2, y2))
                plate_text = self._resolve_plate_text(plate_result)
                plate_bbox = self._plate_bbox_xyxy(plate_result)
                plate_linked = self._is_plate_linked_to_vehicle(
                    vehicle_bbox_xyxy=(x1, y1, x2, y2),
                    plate_bbox_xyxy=plate_bbox,
                )
                if plate_bbox is not None and not plate_linked:
                    plate_text = None
                    plate_bbox = None
                plate_type = self._classify_plate_type(
                    plate_text=plate_text,
                    plate_result=plate_result,
                    classifier=classifier,
                )
                color_name = self._extract_dominant_color(
                    frame_bgr=frame_bgr,
                    bbox_xyxy=(x1, y1, x2, y2),
                )

                rows.append(
                    {
                        "class": self._resolve_class_name(names, class_id),
                        "class_id": class_id,
                        "confidence": round(confidence_score, 4),
                        "bbox": [int(x1), int(y1), int(x2), int(y2)],
                        "plate": plate_text,
                        "plate_type": plate_type,
                        "color": color_name,
                        "plate_bbox": plate_bbox,
                        "plate_linked": bool(plate_linked),
                    }
                )

        rows.sort(key=lambda row: float(row.get("confidence", 0.0)), reverse=True)
        return rows[:max_detections]

    def _build_plate_only_fallback_row(
        self,
        *,
        frame_bgr: np.ndarray,
        classifier: Optional[PlateTypeClassifier],
    ) -> Optional[Dict[str, Any]]:
        plate_result = self._read_plate_from_global_regions(frame_bgr)
        if plate_result is None:
            return None

        plate_text = self._resolve_plate_text(plate_result)
        if not plate_text:
            return None
        plate_type = self._classify_plate_type(
            plate_text=plate_text,
            plate_result=plate_result,
            classifier=classifier,
        )
        plate_bbox = self._plate_bbox_xyxy(plate_result)
        height, width = frame_bgr.shape[:2]

        return {
            "class": "unknown",
            "class_id": -1,
            "confidence": 0.0,
            "bbox": [0, 0, int(width), int(height)],
            "plate": plate_text,
            "plate_type": plate_type,
            "color": "unknown",
            "plate_bbox": plate_bbox,
            "source": "plate_only_fallback",
            "plate_confidence": round(float(plate_result.confidence or 0.0), 4),
        }

    def _read_plate_from_global_regions(self, frame_bgr: np.ndarray) -> Optional[PlateReadResult]:
        if frame_bgr is None or frame_bgr.size == 0:
            return None

        h, w = frame_bgr.shape[:2]
        candidates: List[tuple[int, int, int, int]] = [
            (0, int(h * 0.30), int(w), int(h * 0.55)),  # lower-middle band
            (int(w * 0.08), int(h * 0.22), int(w * 0.84), int(h * 0.62)),  # centered region
            (0, 0, int(w), int(h)),  # last resort
        ]

        best: Optional[PlateReadResult] = None
        best_score = -1.0

        for x, y, bw, bh in candidates[: self.plate_fallback_rois]:
            if bw <= 0 or bh <= 0:
                continue
            x = max(0, min(w - 1, int(x)))
            y = max(0, min(h - 1, int(y)))
            bw = max(1, min(w - x, int(bw)))
            bh = max(1, min(h - y, int(bh)))
            try:
                result = self.plate_reader.read_plate(frame_bgr, vehicle_bbox=(x, y, bw, bh))
            except Exception:
                result = None
            if result is None:
                continue

            text = self._resolve_plate_text(result)
            if not text:
                continue

            compact = re.sub(r"[^0-9A-Z]+", "", str(text).upper())
            digit_count = sum(1 for ch in compact if ch.isdigit())
            score = float(result.confidence or 0.0)
            if digit_count >= 2:
                score += 0.15
            if 4 <= len(compact) <= 12:
                score += 0.10
            if score > best_score:
                best = result
                best_score = score

        return best

    def _read_plate(
        self,
        *,
        frame_bgr: np.ndarray,
        vehicle_bbox_xyxy: tuple[int, int, int, int],
    ) -> Optional[PlateReadResult]:
        x1, y1, x2, y2 = vehicle_bbox_xyxy
        width = max(0, x2 - x1)
        height = max(0, y2 - y1)
        if width <= 0 or height <= 0:
            return None
        try:
            return self.plate_reader.read_plate(frame_bgr, vehicle_bbox=(x1, y1, width, height))
        except Exception:
            return None

    def _resolve_plate_text(self, plate_result: Optional[PlateReadResult]) -> Optional[str]:
        if plate_result is None:
            return None
        raw_text = str(plate_result.raw_text or "").strip()
        if not raw_text:
            return None
        normalized = self.plate_normalizer.normalize(raw_text)
        return (
            normalized.display_text
            or normalized.normalized_text
            or normalized.compact_text
            or raw_text.upper()
            or None
        )

    def _plate_bbox_xyxy(self, plate_result: Optional[PlateReadResult]) -> Optional[List[int]]:
        if plate_result is None or plate_result.bbox is None:
            return None
        px, py, pw, ph = plate_result.bbox
        if pw <= 0 or ph <= 0:
            return None
        return [int(px), int(py), int(px + pw), int(py + ph)]

    def _is_plate_linked_to_vehicle(
        self,
        *,
        vehicle_bbox_xyxy: tuple[int, int, int, int],
        plate_bbox_xyxy: Optional[List[int]],
    ) -> bool:
        if plate_bbox_xyxy is None:
            return False
        vx1, vy1, vx2, vy2 = vehicle_bbox_xyxy
        px1, py1, px2, py2 = [int(v) for v in plate_bbox_xyxy[:4]]

        vehicle_w = max(0, vx2 - vx1)
        vehicle_h = max(0, vy2 - vy1)
        plate_w = max(0, px2 - px1)
        plate_h = max(0, py2 - py1)
        if vehicle_w <= 0 or vehicle_h <= 0 or plate_w <= 0 or plate_h <= 0:
            return False

        ix1 = max(vx1, px1)
        iy1 = max(vy1, py1)
        ix2 = min(vx2, px2)
        iy2 = min(vy2, py2)
        inter_w = max(0, ix2 - ix1)
        inter_h = max(0, iy2 - iy1)
        inter_area = inter_w * inter_h
        plate_area = plate_w * plate_h
        if plate_area <= 0:
            return False

        overlap_ratio = float(inter_area) / float(plate_area)
        plate_center_y = (py1 + py2) / 2.0
        vertical_ratio = float(plate_center_y - vy1) / float(max(vehicle_h, 1))

        return overlap_ratio >= self.min_plate_overlap_ratio and vertical_ratio >= self.min_plate_vertical_ratio

    def _classify_plate_type(
        self,
        *,
        plate_text: Optional[str],
        plate_result: Optional[PlateReadResult],
        classifier: Optional[PlateTypeClassifier],
    ) -> str:
        if not plate_text:
            return "unknown"

        normalized = self.plate_normalizer.normalize(plate_text)

        if classifier is not None:
            try:
                out = classifier.classify(
                    normalized_text=normalized.normalized_text,
                    compact_text=normalized.compact_text,
                    raw_text=plate_text,
                    plate_crop=plate_result.plate_crop if plate_result is not None else None,
                )
                if out.plate_type in {"military", "civil"}:
                    return out.plate_type
            except Exception:
                pass

        return self._classify_plate_type_by_pattern(normalized)

    def _classify_plate_type_by_pattern(self, normalized: PlateNormalizationResult) -> str:
        payload = f"{normalized.raw_text} {normalized.normalized_text} {normalized.compact_text}".upper()
        military_score = 0
        civil_score = 0

        if any(keyword in payload for keyword in self.military_keywords):
            military_score += 2
        if any(keyword in payload for keyword in self.civil_keywords):
            civil_score += 2

        if self._match_patterns(payload, self.military_patterns):
            military_score += 2
        if self._match_patterns(payload, self.civil_patterns):
            civil_score += 2

        compact = normalized.compact_text
        if compact and re.fullmatch(r"M[0-9A-Z]{2,8}", compact):
            military_score += 1
        if compact and ("TN" in compact or "TUNIS" in payload):
            civil_score += 1

        if military_score > civil_score:
            return "military"
        if civil_score > military_score:
            return "civil"
        return "unknown"

    def _extract_dominant_color(
        self,
        *,
        frame_bgr: np.ndarray,
        bbox_xyxy: tuple[int, int, int, int],
    ) -> str:
        x1, y1, x2, y2 = bbox_xyxy
        h, w = frame_bgr.shape[:2]
        x1 = max(0, min(w, int(x1)))
        y1 = max(0, min(h, int(y1)))
        x2 = max(0, min(w, int(x2)))
        y2 = max(0, min(h, int(y2)))
        if x2 <= x1 or y2 <= y1:
            return "unknown"

        roi = frame_bgr[y1:y2, x1:x2]
        if roi is None or roi.size == 0:
            return "unknown"

        sample = roi.reshape(-1, 3).astype(np.float32)
        if sample.size == 0:
            return "unknown"
        # Use median to limit the impact of highlights/shadows.
        b, g, r = np.median(sample, axis=0).tolist()
        return self._map_rgb_to_color_name(r=r, g=g, b=b)

    def _map_rgb_to_color_name(self, *, r: float, g: float, b: float) -> str:
        rgb = np.array([[[max(0.0, min(255.0, b)), max(0.0, min(255.0, g)), max(0.0, min(255.0, r))]]], dtype=np.uint8)
        if _HAS_CV2:
            hsv = cv2.cvtColor(rgb, cv2.COLOR_BGR2HSV)[0, 0]
            hue = float(hsv[0]) * 2.0
            sat = float(hsv[1])
            val = float(hsv[2])
        else:
            brightness = (r + g + b) / 3.0
            spread = max(r, g, b) - min(r, g, b)
            if brightness < 45:
                return "black"
            if brightness > 215 and spread < 18:
                return "white"
            if spread < 22:
                return "gray"
            if r > g * 1.12 and r > b * 1.12:
                return "red"
            if g > r * 1.10 and g > b * 1.10:
                return "green"
            if b > r * 1.08 and b > g * 1.08:
                return "blue"
            return "other"

        if val < 46:
            return "black"
        if sat < 28 and val > 210:
            return "white"
        if sat < 35:
            return "gray"
        if (hue >= 345 or hue < 15) and sat > 50:
            return "red"
        if 15 <= hue < 32:
            return "orange"
        if 32 <= hue < 70:
            return "yellow"
        if 70 <= hue < 165:
            return "green"
        if 165 <= hue < 260:
            return "blue"
        if 260 <= hue < 345:
            return "purple"
        return "other"

    def _resolve_class_name(self, names: object, class_id: int) -> str:
        if isinstance(names, dict):
            value = names.get(class_id)
            if value is not None:
                return str(value)
            value = names.get(str(class_id))
            if value is not None:
                return str(value)
        if isinstance(names, list) and 0 <= class_id < len(names):
            return str(names[class_id])
        return f"class_{class_id}"

    def _empty_response(self, message: str) -> Dict[str, Any]:
        return {
            "success": False,
            "message": message,
            "vehicles_count": 0,
            "vehicles": [],
            "detections_count": 0,
            "detections": [],
        }

    def _parse_vehicle_class_ids(self, raw: str) -> set[int]:
        out: set[int] = set()
        for part in str(raw or "").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.add(int(part))
            except Exception:
                continue
        return out or set(self._DEFAULT_VEHICLE_CLASS_IDS)

    def _resolve_predict_device(self, requested: str) -> str:
        req = str(requested or "auto").strip().lower()
        if req in {"", "auto"}:
            try:
                import torch  # type: ignore

                return "0" if torch.cuda.is_available() else "cpu"
            except Exception:
                return "cpu"
        if req == "cpu":
            return "cpu"
        if req == "cuda":
            return "0"
        if req.startswith("cuda:"):
            suffix = req.split(":", 1)[1].strip()
            return suffix or "0"
        return req

    def _parse_csv(self, raw: str) -> List[str]:
        return [part.strip() for part in str(raw or "").split(",") if part.strip()]

    def _parse_csv_upper(self, raw: str) -> List[str]:
        return [part.upper() for part in self._parse_csv(raw)]

    def _compile_patterns(self, patterns: List[str]) -> List[re.Pattern[str]]:
        out: List[re.Pattern[str]] = []
        for pattern in patterns:
            try:
                out.append(re.compile(pattern, re.IGNORECASE))
            except Exception:
                continue
        return out

    def _match_patterns(self, text: str, patterns: List[re.Pattern[str]]) -> bool:
        for pattern in patterns:
            if pattern.search(text):
                return True
        return False


_ENGINE: Optional[VehicleAIEngine] = None
_ENGINE_LOCK = Lock()


def get_vehicle_ai_engine() -> VehicleAIEngine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = VehicleAIEngine()
    return _ENGINE


def decode_image_bytes_to_bgr(image_bytes: bytes) -> Optional[np.ndarray]:
    if not image_bytes:
        return None
    if _HAS_CV2:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None:
            return frame
    try:
        rgb = np.asarray(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
        return rgb[:, :, ::-1].copy()
    except Exception:
        return None


def detect_vehicles(
    frame: np.ndarray,
    *,
    confidence: Optional[float] = None,
    iou_threshold: Optional[float] = None,
    max_detections: Optional[int] = None,
    vehicle_only: bool = True,
    plate_only_fallback: Optional[bool] = None,
    db: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    engine = get_vehicle_ai_engine()
    return engine.detect_vehicles(
        frame,
        confidence=confidence,
        iou_threshold=iou_threshold,
        max_detections=max_detections,
        vehicle_only=vehicle_only,
        plate_only_fallback=plate_only_fallback,
        db=db,
    )


def detect_vehicle_objects_from_bytes(
    image_bytes: bytes,
    *,
    confidence: Optional[float] = None,
    iou_threshold: Optional[float] = None,
    max_detections: Optional[int] = None,
    vehicle_only: bool = True,
    plate_only_fallback: Optional[bool] = None,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    frame = decode_image_bytes_to_bgr(image_bytes)
    if frame is None:
        return {
            "success": False,
            "message": "Invalid image payload",
            "vehicles_count": 0,
            "vehicles": [],
            "detections_count": 0,
            "detections": [],
        }
    engine = get_vehicle_ai_engine()
    return engine.detect(
        frame,
        confidence=confidence,
        iou_threshold=iou_threshold,
        max_detections=max_detections,
        vehicle_only=vehicle_only,
        plate_only_fallback=plate_only_fallback,
        db=db,
    )
