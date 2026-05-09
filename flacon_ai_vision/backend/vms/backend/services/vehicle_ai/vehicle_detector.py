from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

try:
    from ultralytics import YOLO  # type: ignore

    _HAS_YOLO = True
except Exception:
    YOLO = None
    _HAS_YOLO = False

logger = logging.getLogger(__name__)


@dataclass
class VehicleDetection:
    bbox: Tuple[int, int, int, int]
    confidence: float
    class_name: str
    source: str


class VehicleDetector:
    """Vehicle detector with YOLO-first strategy and graceful fallback."""

    _COCO_VEHICLE_CLASSES = {
        2: "car",
        3: "motorcycle",
        5: "bus",
        7: "truck",
    }

    def __init__(self):
        self.model = None
        self.min_conf = float(os.getenv("VEHICLE_DETECT_MIN_CONF", "0.35"))
        self.max_detections = int(os.getenv("VEHICLE_DETECT_MAX", "8"))
        self.predict_device = self._resolve_predict_device()
        self._init_model()

    @property
    def backend(self) -> str:
        return f"yolo:{self.predict_device}" if self.model is not None else "none"

    def _resolve_predict_device(self) -> str:
        requested = (
            os.getenv("VEHICLE_AI_DEVICE", "").strip()
            or os.getenv("AI_DEVICE", "").strip()
            or "auto"
        ).lower()
        if requested not in {"cpu", "cuda", "cuda:0", "cuda:1", "auto"}:
            requested = "auto"

        if requested == "cpu":
            return "cpu"
        try:
            import torch  # type: ignore

            if requested == "auto":
                return "cuda:0" if torch.cuda.is_available() else "cpu"
            if requested.startswith("cuda"):
                if torch.cuda.is_available():
                    return requested
                logger.warning("Requested %s for vehicle detector but CUDA unavailable; falling back to CPU", requested)
                return "cpu"
        except Exception:
            if requested.startswith("cuda"):
                logger.warning("CUDA device requested but torch check failed; falling back to CPU")
            return "cpu"
        return "cpu"

    def _init_model(self) -> None:
        if not _HAS_YOLO:
            return
        model_name = os.getenv("VEHICLE_DETECT_MODEL", "yolov8n.pt").strip() or "yolov8n.pt"
        try:
            self.model = YOLO(model_name)
            if self.predict_device != "cpu":
                try:
                    self.model.to(self.predict_device)
                except Exception:
                    logger.warning("Unable to move YOLO model to %s, keeping default device", self.predict_device)
        except Exception as exc:
            logger.warning("Failed to initialize vehicle detector model %s: %s", model_name, exc)
            self.model = None

    def detect(self, frame_bgr: np.ndarray) -> List[VehicleDetection]:
        if frame_bgr is None or frame_bgr.size == 0:
            return []
        if self.model is None:
            return []

        out: List[VehicleDetection] = []
        try:
            results = self.model.predict(
                source=frame_bgr,
                verbose=False,
                conf=self.min_conf,
                max_det=self.max_detections,
                imgsz=640,
                device=self.predict_device,
            )
        except Exception as exc:
            if self.predict_device != "cpu":
                # One-shot resilient fallback for client machines without proper GPU stack.
                logger.warning(
                    "Vehicle detector prediction failed on %s, retrying on CPU: %s",
                    self.predict_device,
                    exc,
                )
                self.predict_device = "cpu"
                try:
                    results = self.model.predict(
                        source=frame_bgr,
                        verbose=False,
                        conf=self.min_conf,
                        max_det=self.max_detections,
                        imgsz=640,
                        device=self.predict_device,
                    )
                except Exception as retry_exc:
                    logger.error("Vehicle detector prediction failed on CPU retry: %s", retry_exc)
                    return out
            else:
                logger.error("Vehicle detector prediction failed on CPU: %s", exc)
                return out

        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                try:
                    class_id = int(box.cls[0])
                    class_name = self._COCO_VEHICLE_CLASSES.get(class_id)
                    if class_name is None:
                        continue
                    confidence = float(box.conf[0])
                    x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                    w = max(0, x2 - x1)
                    h = max(0, y2 - y1)
                    if w <= 0 or h <= 0:
                        continue
                    out.append(
                        VehicleDetection(
                            bbox=(x1, y1, w, h),
                            confidence=confidence,
                            class_name=class_name,
                            source="yolo",
                        )
                    )
                except Exception as exc:
                    logger.debug("Skipping malformed vehicle detection box: %s", exc)
                    continue

        out.sort(key=lambda item: item.confidence * max(item.bbox[2] * item.bbox[3], 1), reverse=True)
        return out

    def primary_or_full_frame(
        self,
        frame_bgr: np.ndarray,
        detections: Optional[List[VehicleDetection]] = None,
    ) -> Tuple[int, int, int, int]:
        if detections:
            return detections[0].bbox
        h, w = frame_bgr.shape[:2]
        return (0, 0, int(w), int(h))
