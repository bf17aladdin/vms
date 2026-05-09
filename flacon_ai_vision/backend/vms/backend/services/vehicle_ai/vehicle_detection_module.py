from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import List, Optional

import numpy as np

from .tracker_backends import VehicleTrackerBackend, create_tracker_backend
from .vehicle_detector import VehicleDetection, VehicleDetector


@dataclass
class DetectionStageResult:
    detections: List[VehicleDetection]
    detection_track_ids: List[Optional[int]]
    tracker_backend: str
    primary: Optional[VehicleDetection]
    primary_track_id: Optional[int]
    vehicle_detected: bool
    plate_only_fallback_attempted: bool
    plate_only_fallback_used: bool
    plate_only_fallback_reason: Optional[str]
    early_exit_reason: Optional[str]


class VehicleDetectionModule:
    """Single responsibility: detect vehicles and select primary detection/fallback."""

    def __init__(
        self,
        *,
        detector: VehicleDetector,
        min_vehicle_conf: float,
        plate_only_fallback_enabled: bool,
    ):
        self.detector = detector
        self.min_vehicle_conf = float(min_vehicle_conf)
        self.plate_only_fallback_enabled = bool(plate_only_fallback_enabled)
        self.track_enabled = str(os.getenv("VEHICLE_TRACK_ENABLED", "true")).strip().lower() == "true"
        self.track_max_age_sec = float(os.getenv("VEHICLE_TRACK_MAX_AGE_SEC", "2.5"))
        self.track_iou_threshold = float(os.getenv("VEHICLE_TRACK_IOU_THRESHOLD", "0.20"))
        self.track_center_distance_ratio = float(
            os.getenv("VEHICLE_TRACK_CENTER_DISTANCE_RATIO", "1.8")
        )
        self.track_mode = str(os.getenv("VEHICLE_TRACKER_MODE", "iou")).strip().lower()
        self.sort_match_iou = float(os.getenv("VEHICLE_SORT_MATCH_IOU", "0.20"))
        self.sort_match_distance_ratio = float(
            os.getenv("VEHICLE_SORT_MATCH_DISTANCE_RATIO", "1.8")
        )

        self._tracker_backend: Optional[VehicleTrackerBackend] = None
        self._tracker_backend_name = "disabled"
        if self.track_enabled:
            self._tracker_backend = create_tracker_backend(
                mode=self.track_mode,
                max_age_sec=self.track_max_age_sec,
                iou_threshold=self.track_iou_threshold,
                center_distance_ratio=self.track_center_distance_ratio,
                sort_match_iou=self.sort_match_iou,
                sort_match_distance_ratio=self.sort_match_distance_ratio,
            )
            self._tracker_backend_name = self._tracker_backend.name

    @property
    def tracker_backend_name(self) -> str:
        return self._tracker_backend_name

    def detect_and_select_primary(
        self,
        frame_bgr: np.ndarray,
        *,
        camera_id: int,
        ocr_available: bool,
    ) -> DetectionStageResult:
        detections = self.detector.detect(frame_bgr)
        detection_track_ids = self._assign_track_ids(
            camera_id=int(camera_id),
            detections=detections,
            reference_time=datetime.now(timezone.utc),
        )
        plate_only_fallback_attempted = False
        plate_only_fallback_used = False
        plate_only_fallback_reason: Optional[str] = None
        vehicle_detected = True
        early_exit_reason: Optional[str] = None
        primary: Optional[VehicleDetection] = detections[0] if detections else None
        primary_track_id = detection_track_ids[0] if detection_track_ids else None

        if primary is None:
            plate_only_fallback_attempted = True
            if self.plate_only_fallback_enabled and ocr_available:
                primary = self._full_frame_fallback_detection(frame_bgr)
                vehicle_detected = False
                plate_only_fallback_used = True
                plate_only_fallback_reason = "no_vehicle_detected"
                primary_track_id = None
            else:
                plate_only_fallback_reason = "ocr_backend_unavailable" if not ocr_available else "disabled"
                early_exit_reason = "no_vehicle_detected"
            return DetectionStageResult(
                detections=detections,
                detection_track_ids=detection_track_ids,
                tracker_backend=self._tracker_backend_name,
                primary=primary,
                primary_track_id=primary_track_id,
                vehicle_detected=vehicle_detected,
                plate_only_fallback_attempted=plate_only_fallback_attempted,
                plate_only_fallback_used=plate_only_fallback_used,
                plate_only_fallback_reason=plate_only_fallback_reason,
                early_exit_reason=early_exit_reason,
            )

        if float(primary.confidence) < self.min_vehicle_conf:
            plate_only_fallback_attempted = True
            if self.plate_only_fallback_enabled and ocr_available:
                primary = self._full_frame_fallback_detection(frame_bgr)
                vehicle_detected = False
                plate_only_fallback_used = True
                plate_only_fallback_reason = "vehicle_confidence_too_low"
                primary_track_id = None
            else:
                plate_only_fallback_reason = "ocr_backend_unavailable" if not ocr_available else "disabled"
                early_exit_reason = "vehicle_confidence_too_low"

        return DetectionStageResult(
            detections=detections,
            detection_track_ids=detection_track_ids,
            tracker_backend=self._tracker_backend_name,
            primary=primary,
            primary_track_id=primary_track_id,
            vehicle_detected=vehicle_detected,
            plate_only_fallback_attempted=plate_only_fallback_attempted,
            plate_only_fallback_used=plate_only_fallback_used,
            plate_only_fallback_reason=plate_only_fallback_reason,
            early_exit_reason=early_exit_reason,
        )

    def _assign_track_ids(
        self,
        *,
        camera_id: int,
        detections: List[VehicleDetection],
        reference_time: datetime,
    ) -> List[Optional[int]]:
        if not self.track_enabled or self._tracker_backend is None:
            return [None for _ in detections]
        return self._tracker_backend.assign(
            camera_id=int(camera_id),
            detections=detections,
            reference_time=reference_time,
        )

    def _full_frame_fallback_detection(self, frame_bgr: np.ndarray) -> VehicleDetection:
        height, width = frame_bgr.shape[:2]
        return VehicleDetection(
            bbox=(0, 0, int(width), int(height)),
            confidence=0.0,
            class_name="unknown",
            source="plate_only_fallback",
        )
