from __future__ import annotations

import io
import os
import hashlib
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from vms.backend.core.media_paths import to_public_media_path

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

from .plate_normalizer import PlateNormalizer
from .plate_reader import PlateReader
from .plate_type_classifier import PlateTypeClassification
from .access_control import VehicleAccessController
from .vehicle_detector import VehicleDetector
from .vehicle_detection_module import VehicleDetectionModule
from .plate_scanner_module import PlateScannerModule
from .ocr_stabilizer_module import OcrStabilizerModule
from .vehicle_attributes_module import VehicleAttributesModule
from .vehicle_consistency_module import VehicleConsistencyModule
from .vehicle_anomaly_module import VehicleAnomalyModule
from .vehicle_alert_engine_module import VehicleAlertEngineModule
from .vehicle_live_monitoring_module import VehicleLiveMonitoringModule
from .vehicle_search_contract import UNKNOWN_ATTRIBUTE_FILTER
from vms.backend.services.access_decision_service import AccessDecisionRequest, AccessDecisionService
from vms.backend.services.action_engine import ActionEngine
from vms.backend.services.unknown_detection_service import UnknownDetectionService


class VehicleRecognitionPipeline:
    """Vehicle pipeline: Detect -> Plate -> OCR -> Normalize -> Type -> Event -> History."""

    _components_lock = Lock()
    _detector: Optional[VehicleDetector] = None
    _plate_reader: Optional[PlateReader] = None
    _normalizer: Optional[PlateNormalizer] = None
    _result_cache_lock = Lock()
    _result_cache: Dict[str, Dict[str, Any]] = {}

    def __init__(self, db: Session):
        self.db = db
        self.detector, self.plate_reader, self.normalizer = self._get_shared_components()
        self.access_controller = VehicleAccessController(db, normalizer=self.normalizer)
        self.unknown_detection_service = UnknownDetectionService(db)
        self.access_decision_service = AccessDecisionService(db)
        self.action_engine = ActionEngine(db)
        self.snapshot_quality = int(os.getenv("VEHICLE_SNAPSHOT_QUALITY", "88"))
        self.military_alert_enabled = os.getenv("VEHICLE_MILITARY_ALERT_ENABLED", "true").lower() == "true"
        self.cache_ttl_sec = float(os.getenv("VEHICLE_RECOG_CACHE_TTL_SEC", "1.5"))
        self.cache_max_entries = max(1, int(os.getenv("VEHICLE_RECOG_CACHE_MAX", "512")))
        self.cache_allow_persist = os.getenv("VEHICLE_RECOG_CACHE_ALLOW_PERSIST", "false").lower() == "true"
        self.ocr_agg_window_sec = float(os.getenv("VEHICLE_OCR_AGG_WINDOW_SEC", "1.5"))
        self.ocr_agg_max_samples = max(1, int(os.getenv("VEHICLE_OCR_AGG_MAX_SAMPLES", "6")))
        self.ocr_agg_decay_sec = float(os.getenv("VEHICLE_OCR_AGG_DECAY_SEC", "0.9"))
        self.ocr_agg_min_samples = max(1, int(os.getenv("VEHICLE_OCR_AGG_MIN_SAMPLES", "3")))
        self.ocr_agg_min_stability = float(os.getenv("VEHICLE_OCR_AGG_MIN_STABILITY", "0.65"))
        self.ocr_agg_min_margin = float(os.getenv("VEHICLE_OCR_AGG_MIN_MARGIN", "0.12"))
        self.default_civil_city = (os.getenv("VEHICLE_DEFAULT_CIVIL_CITY", "\u062a\u0648\u0646\u0633") or "\u062a\u0648\u0646\u0633").strip()
        self.runtime_min_vehicle_conf = float(os.getenv("VEHICLE_RUNTIME_MIN_VEHICLE_CONF", "0.45"))
        self.runtime_min_plate_conf = float(os.getenv("VEHICLE_RUNTIME_MIN_PLATE_CONF", "0.25"))
        self.runtime_min_plate_chars = max(3, int(os.getenv("VEHICLE_RUNTIME_MIN_PLATE_CHARS", "4")))
        self.runtime_min_plate_digits = max(1, int(os.getenv("VEHICLE_RUNTIME_MIN_PLATE_DIGITS", "2")))
        self.runtime_strict_tn_plate = os.getenv("VEHICLE_RUNTIME_STRICT_TN_PLATE", "true").lower() == "true"
        self.plate_only_fallback_enabled = os.getenv("VEHICLE_ANPR_PLATE_ONLY_FALLBACK", "true").lower() == "true"
        self.detection_module = VehicleDetectionModule(
            detector=self.detector,
            min_vehicle_conf=self.runtime_min_vehicle_conf,
            plate_only_fallback_enabled=self.plate_only_fallback_enabled,
        )
        self.plate_scanner_module = PlateScannerModule(
            reader=self.plate_reader,
            normalizer=self.normalizer,
            min_plate_conf=self.runtime_min_plate_conf,
            min_plate_chars=self.runtime_min_plate_chars,
            min_plate_digits=self.runtime_min_plate_digits,
            strict_tn_plate=self.runtime_strict_tn_plate,
        )
        self.attributes_module = VehicleAttributesModule(
            db=self.db,
            default_civil_city=self.default_civil_city,
        )
        self.ocr_stabilizer_module = OcrStabilizerModule(
            window_sec=self.ocr_agg_window_sec,
            max_samples=self.ocr_agg_max_samples,
            decay_sec=self.ocr_agg_decay_sec,
            min_samples=self.ocr_agg_min_samples,
            min_stability=self.ocr_agg_min_stability,
            min_margin=self.ocr_agg_min_margin,
        )
        self.consistency_module = VehicleConsistencyModule()
        self.anomaly_module = VehicleAnomalyModule()
        self.alert_engine_module = VehicleAlertEngineModule()
        self.live_monitoring_module = VehicleLiveMonitoringModule(db=self.db)

    def bind_db(self, db: Session) -> None:
        self.db = db
        self.access_controller.db = db
        self.unknown_detection_service.db = db
        self.access_decision_service.db = db
        self.action_engine.db = db
        self.action_engine.unknown_detection_service.db = db
        self.attributes_module.db = db
        self.live_monitoring_module.db = db

    @classmethod
    def _get_shared_components(cls) -> tuple[VehicleDetector, PlateReader, PlateNormalizer]:
        with cls._components_lock:
            if cls._detector is None:
                cls._detector = VehicleDetector()
            if cls._plate_reader is None:
                cls._plate_reader = PlateReader()
            if cls._normalizer is None:
                cls._normalizer = PlateNormalizer()
        return cls._detector, cls._plate_reader, cls._normalizer

    def recognize_from_bytes(
        self,
        image_bytes: bytes,
        camera_id: int,
        zone_id: Optional[int] = None,
        gate_id: Optional[str] = None,
        direction: str = "IN",
        persist: bool = True,
        save_snapshot: bool = True,
    ) -> Dict[str, Any]:
        frame = self._bytes_to_bgr(image_bytes)
        if frame is None:
            return {"success": False, "status": "error", "message": "Invalid image payload"}
        return self.recognize_from_frame(
            frame_bgr=frame,
            camera_id=camera_id,
            zone_id=zone_id,
            gate_id=gate_id,
            direction=direction,
            persist=persist,
            save_snapshot=save_snapshot,
            image_bytes=image_bytes,
        )

    def recognize_from_frame(
        self,
        frame_bgr: np.ndarray,
        camera_id: int,
        zone_id: Optional[int] = None,
        gate_id: Optional[str] = None,
        direction: str = "IN",
        persist: bool = True,
        save_snapshot: bool = True,
        image_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        cacheable = bool(self.cache_ttl_sec > 0 and ((not persist) or self.cache_allow_persist))
        cache_key = self._build_cache_key(
            frame_bgr=frame_bgr,
            camera_id=camera_id,
            zone_id=zone_id,
            gate_id=gate_id,
            direction=direction,
            save_snapshot=save_snapshot,
        )
        if cacheable:
            cached = self._cache_get(cache_key)
            if cached is not None:
                # Never return stale event_id for non-persistent cache hits.
                if not persist:
                    cached["event_id"] = None
                    cached["snapshot_path"] = None
                return cached

        pipeline_started = time.perf_counter()
        detect_started = time.perf_counter()
        detection_stage = self.detection_module.detect_and_select_primary(
            frame_bgr,
            camera_id=int(camera_id),
            ocr_available=self.plate_reader.backend != "none",
        )
        detect_latency_ms = (time.perf_counter() - detect_started) * 1000.0
        plate_only_fallback_attempted = bool(detection_stage.plate_only_fallback_attempted)
        plate_only_fallback_used = bool(detection_stage.plate_only_fallback_used)
        plate_only_fallback_reason = detection_stage.plate_only_fallback_reason
        vehicle_detected = bool(detection_stage.vehicle_detected)
        primary = detection_stage.primary
        primary_track_id = detection_stage.primary_track_id
        tracker_backend = detection_stage.tracker_backend

        if detection_stage.early_exit_reason is not None or primary is None:
            decision_reason = detection_stage.early_exit_reason or "no_vehicle_detected"
            pipeline_latency_ms = (time.perf_counter() - pipeline_started) * 1000.0
            consistency = self.consistency_module.empty_result(flag=decision_reason)
            anomaly = self.anomaly_module.evaluate(consistency=consistency)
            anomaly_alert = self.alert_engine_module.evaluate(
                camera_id=int(camera_id),
                track_id=None,
                plate_number=None,
                anomaly=anomaly,
                consistency=consistency,
            )
            anomaly_alert = dict(anomaly_alert or {})
            anomaly_alert.setdefault("alert_id", None)
            anomaly_alert.setdefault("emitted", False)
            response = {
                "success": True,
                "status": "no_vehicle",
                "message": "Aucun vehicule detecte dans ce frame.",
                "vehicle_detected": False,
                "plate_number": None,
                "plate_display": None,
                "plate_code": None,
                "plate_city": None,
                "plate_sequence": None,
                "plate_type": "unknown",
                "confidence": 0.0,
                "vehicle_profile": None,
                "consistency": consistency,
                "anomaly": anomaly,
                "anomaly_alert": anomaly_alert,
                "ocr_stabilization": {"applied": False},
                "camera_id": camera_id,
                "zone_id": zone_id,
                "gate_id": gate_id,
                "direction": str(direction or "IN").upper(),
                "decision": "denied",
                "decision_reason": decision_reason,
                "requires_manual_review": False,
                "track_id": None,
                "timestamp": datetime.utcnow().isoformat(),
                "latency_ms": round(float(pipeline_latency_ms), 3),
                "detector_latency_ms": round(float(detect_latency_ms), 3),
                "plate_only_fallback_attempted": bool(plate_only_fallback_attempted),
                "plate_only_fallback_used": bool(plate_only_fallback_used),
                "plate_only_fallback_reason": plate_only_fallback_reason,
                "plate_visibility": "not_applicable",
                "pipeline": {
                    "detector": self.detector.backend,
                    "tracker": tracker_backend,
                    "ocr": self.plate_reader.backend,
                    "normalizer": "rule_based",
                    "classifier": "hybrid_rules",
                },
            }
            if cacheable:
                self._cache_set(cache_key, response)
            return response
        ocr_started = time.perf_counter()
        plate_bbox_source = None if plate_only_fallback_used else primary.bbox
        scan_result = self.plate_scanner_module.scan(
            frame_bgr=frame_bgr,
            vehicle_bbox=plate_bbox_source,
        )
        ocr_latency_ms = (time.perf_counter() - ocr_started) * 1000.0

        plate_result = scan_result.plate_result
        raw_text = scan_result.raw_text
        plate_confidence = float(scan_result.plate_confidence)
        plate_bbox = scan_result.plate_bbox
        plate_crop = scan_result.plate_crop
        normalized_text = scan_result.normalized_text
        compact_text = scan_result.compact_text
        plate_code = scan_result.plate_code
        plate_city = scan_result.plate_city
        plate_sequence = scan_result.plate_sequence
        plate_display = scan_result.plate_display
        plate_reliable = bool(scan_result.plate_reliable)
        ocr_stabilization: Optional[Dict[str, Any]] = None

        if raw_text and plate_reliable:
            aggregate = self.ocr_stabilizer_module.update(
                camera_id=camera_id,
                track_id=primary_track_id,
                compact_text=compact_text,
                normalized_text=normalized_text,
                raw_text=raw_text,
                confidence=plate_confidence,
            )
            if aggregate is not None:
                ocr_stabilization = aggregate
                if bool(aggregate.get("applied", False)):
                    raw_text = aggregate.get("raw_text", raw_text)
                    plate_confidence = float(max(plate_confidence, float(aggregate.get("confidence", 0.0))))
                    normalized = self.plate_scanner_module.normalize_text(raw_text)
                    normalized_text = str(normalized.get("normalized_text") or "")
                    compact_text = str(normalized.get("compact_text") or "")
                    plate_code = normalized.get("plate_code")
                    plate_city = normalized.get("plate_city")
                    plate_sequence = normalized.get("plate_sequence")
                    plate_display = normalized.get("plate_display")
                    plate_reliable = bool(
                        plate_confidence >= float(self.runtime_min_plate_conf)
                        and self.plate_scanner_module.is_text_plausible(raw_text)
                    )

        classification: Optional[PlateTypeClassification] = None
        classify_started = time.perf_counter()
        if plate_reliable and (normalized_text or compact_text or raw_text):
            classification = self.attributes_module.classify_plate_type(
                plate_reliable=bool(plate_reliable),
                normalized_text=normalized_text,
                compact_text=compact_text,
                raw_text=raw_text,
                plate_crop=plate_crop,
            )
        classify_latency_ms = (time.perf_counter() - classify_started) * 1000.0

        if classification is None:
            plate_type = "unknown"
            classifier_confidence = 0.0
            classifier_reason = "plate_unreadable"
            security_tag = None
            matched_registry = False
            reasons = ["plate_unreadable"]
        else:
            plate_type = classification.plate_type
            classifier_confidence = float(classification.confidence)
            classifier_reason = classification.reason
            security_tag = classification.security_tag
            matched_registry = bool(classification.matched_registry)
            reasons = classification.reasons

        plate_identity = self.attributes_module.resolve_plate_identity(
            plate_reliable=bool(plate_reliable),
            plate_type=plate_type,
            normalized_text=normalized_text,
            raw_text=raw_text,
            plate_code=plate_code,
            plate_city=plate_city,
            plate_sequence=plate_sequence,
            plate_display=plate_display,
        )
        plate_number = plate_identity.plate_number
        plate_display = plate_identity.plate_display
        plate_code = plate_identity.plate_code
        plate_city = plate_identity.plate_city
        plate_sequence = plate_identity.plate_sequence

        vehicle_profile = self.attributes_module.infer_vehicle_profile(
            class_name=primary.class_name,
            bbox=primary.bbox,
            frame_bgr=frame_bgr,
            plate_number=plate_number,
        )

        overall_confidence = self._combine_confidence(
            vehicle_confidence=float(primary.confidence),
            plate_confidence=plate_confidence,
            classifier_confidence=classifier_confidence,
            has_plate=plate_number is not None,
        )

        access_decision = self.access_controller.evaluate(
            plate_number=plate_number,
            plate_type=plate_type,
            confidence=overall_confidence,
            plate_confidence=plate_confidence,
            vehicle_type=primary.class_name,
            vehicle_bbox=primary.bbox,
            frame_bgr=frame_bgr,
            classifier_security_tag=security_tag,
            classifier_registry_match=matched_registry,
        )

        matched_registry = bool(matched_registry or access_decision.registry_matched)
        if access_decision.security_tag:
            security_tag = access_decision.security_tag

        access_decision_request = AccessDecisionRequest(
            detection_type="vehicle",
            confidence=overall_confidence,
            camera_id=camera_id,
            detected_at=datetime.utcnow(),
            plate_number=plate_number,
            vehicle_registry_id=access_decision.registry_vehicle_id,
            metadata={
                "plate_type": plate_type,
                "vehicle_type": primary.class_name,
                "track_id": primary_track_id,
                "security_tag": security_tag,
                "matched_registry": matched_registry,
            },
        )
        access_decision_result = self.access_decision_service.evaluate(access_decision_request)

        consistency = self.consistency_module.compute(
            camera_id=int(camera_id),
            track_id=primary_track_id,
            plate_number=plate_number,
            plate_type=plate_type,
            plate_reliable=bool(plate_reliable),
            plate_confidence=float(plate_confidence),
            vehicle_detected=bool(vehicle_detected),
            vehicle_class=primary.class_name,
            matched_registry=bool(matched_registry),
            ocr_stabilization=ocr_stabilization or {"applied": False},
            vehicle_profile=vehicle_profile,
            plate_only_fallback_used=bool(plate_only_fallback_used),
        )
        anomaly = self.anomaly_module.evaluate(consistency=consistency)
        anomaly_alert = self.alert_engine_module.evaluate(
            camera_id=int(camera_id),
            track_id=primary_track_id,
            plate_number=plate_number,
            anomaly=anomaly,
            consistency=consistency,
        )
        anomaly_alert = dict(anomaly_alert or {})
        anomaly_alert.setdefault("alert_id", None)
        anomaly_alert.setdefault("emitted", False)
        vehicle_profile = dict(vehicle_profile or {})
        vehicle_profile["consistency"] = consistency
        vehicle_profile["anomaly"] = anomaly
        vehicle_profile["anomaly_alert"] = anomaly_alert
        persisted_body_style = self._clean_vehicle_attr(vehicle_profile.get("body_style"))
        persisted_color = self._clean_vehicle_attr(vehicle_profile.get("dominant_color"))
        persisted_brand = self._clean_vehicle_attr(vehicle_profile.get("brand") or vehicle_profile.get("make"))
        persisted_model = self._clean_vehicle_attr(vehicle_profile.get("model"))

        base_severity = "warning" if plate_type == "military" and self.military_alert_enabled else "info"
        severity = self._merge_severity(base_severity, access_decision.severity)
        is_priority = bool(
            access_decision.is_priority or (plate_type == "military" and self.military_alert_enabled)
        )
        if bool(anomaly_alert.get("should_emit", False)):
            severity = self._merge_severity(severity, str(anomaly_alert.get("severity_level", "medium")))
            if str(anomaly_alert.get("severity_level", "")).lower() in {"high", "critical"}:
                is_priority = True
        if bool(anomaly.get("detected", False)):
            level = str(anomaly.get("level") or "none").lower()
            if level in {"critical", "high"}:
                severity = self._merge_severity(severity, "critical" if level == "critical" else "high")
                is_priority = True

        if image_bytes is None and save_snapshot:
            image_bytes = self._frame_to_jpeg_bytes(frame_bgr)

        snapshot_path = None
        if save_snapshot and image_bytes:
            snapshot_path = self._save_snapshot(
                image_bytes=image_bytes,
                camera_id=camera_id,
                plate_type=plate_type,
            )

        event_id = None
        access_log_id = None
        alert_ids: List[int] = []
        unknown_detection_id: Optional[int] = None
        site_id = self._resolve_site_id(camera_id=camera_id)
        timestamp = datetime.utcnow()
        pipeline_latency_ms = (time.perf_counter() - pipeline_started) * 1000.0
        vehicle_profile_meta = dict(vehicle_profile)
        vehicle_profile_meta.pop("consistency", None)
        vehicle_profile_meta.pop("anomaly", None)
        if persist:
            event_id, timestamp = self._persist_event(
                plate_number=plate_number,
                plate_type=plate_type,
                confidence=overall_confidence,
                camera_id=camera_id,
                zone_id=zone_id,
                site_id=site_id,
                snapshot_path=snapshot_path,
                vehicle_detected=bool(vehicle_detected),
                vehicle_type=primary.class_name,
                body_style=persisted_body_style,
                dominant_color=persisted_color,
                brand=persisted_brand,
                model=persisted_model,
                vehicle_confidence=float(primary.confidence),
                vehicle_bbox=self._bbox_to_dict(primary.bbox),
                plate_confidence=plate_confidence,
                plate_bbox=plate_bbox,
                raw_plate_text=raw_text or None,
                normalized_plate=compact_text or normalized_text or None,
                reason=access_decision.reason if access_decision.reason != "policy_pass" else classifier_reason,
                severity=severity,
                is_priority=is_priority,
                security_tag=security_tag,
                matched_registry=matched_registry,
                consistency_score=float(consistency.get("consistency_score", 0.0)),
                consistency_level=str(consistency.get("confidence_level", "low")),
                consistency_flags=list(consistency.get("flags") or []),
                anomaly_detected=bool(anomaly.get("detected", False)),
                anomaly_level=str(anomaly.get("level", "none")),
                anomaly_reason=str(anomaly.get("reason", "none")),
                anomaly_flags=list(anomaly.get("flags") or []),
                pipeline_meta={
                    "detector": primary.source,
                    "tracker": tracker_backend,
                    "track_id": primary_track_id,
                    "ocr": plate_result.source if plate_result else "none",
                    "normalizer": "rule_based",
                    "classifier": "hybrid_rules",
                    "plate_only_fallback_attempted": bool(plate_only_fallback_attempted),
                    "plate_only_fallback_used": bool(plate_only_fallback_used),
                    "plate_only_fallback_reason": plate_only_fallback_reason,
                    "vehicle_profile": vehicle_profile_meta,
                    "is_priority": is_priority,
                    "reasons": reasons,
                    "gate_id": gate_id,
                    "direction": str(direction or "IN").upper(),
                    "access_controller_decision": access_decision.decision,
                    "access_controller_reason": access_decision.reason,
                    "access_flags": access_decision.flags,
                    "requires_manual_review": access_decision.requires_manual_review,
                    "access_decision": access_decision_result.to_dict(),
                    "visual_consistency": access_decision.visual_consistency,
                    "anomaly_rules": list(anomaly.get("rules_triggered") or []),
                    "anomaly_score": float(anomaly.get("anomaly_score", 0.0)),
                    "detector_latency_ms": round(float(detect_latency_ms), 3),
                    "ocr_latency_ms": round(float(ocr_latency_ms), 3),
                    "classifier_latency_ms": round(float(classify_latency_ms), 3),
                    "pipeline_latency_ms": round(float(pipeline_latency_ms), 3),
                    "ocr_candidates": plate_result.candidates[:5] if plate_result else [],
                    "plate_reliable": bool(plate_reliable),
                    "ocr_stabilization": ocr_stabilization or {"applied": False},
                },
            )
            if event_id is not None:
                self._persist_event_frame(
                    event_id=event_id,
                    frame_path=snapshot_path,
                    stage="full_frame",
                    timestamp=timestamp,
                    ocr_text=raw_text or None,
                    decision=access_decision.decision,
                    frame_meta={
                        "camera_id": camera_id,
                        "gate_id": gate_id,
                        "plate_type": plate_type,
                    },
                )
                if plate_crop is not None and plate_crop.size > 0:
                    plate_frame_path = self._save_forensic_frame(
                        frame_bgr=plate_crop,
                        camera_id=camera_id,
                        event_id=event_id,
                        stage="plate_crop",
                    )
                    self._persist_event_frame(
                        event_id=event_id,
                        frame_path=plate_frame_path,
                        stage="plate_crop",
                        timestamp=timestamp,
                        ocr_text=raw_text or None,
                        decision=access_decision.decision,
                        frame_meta={
                            "plate_confidence": plate_confidence,
                            "bbox": plate_bbox,
                        },
                    )
                access_log_id, alert_ids = self.access_controller.persist_access_decision(
                    decision=access_decision,
                    event_id=event_id,
                    plate_number=plate_number,
                    plate_type=plate_type,
                    camera_id=camera_id,
                    site_id=site_id,
                    gate_id=gate_id,
                    direction=direction,
                    timestamp=timestamp,
                    snapshot_path=snapshot_path,
                    vehicle_detected=bool(vehicle_detected),
                    vehicle_type=primary.class_name,
                    plate_confidence=plate_confidence,
                )
                anomaly_alert_id = None
                if bool(anomaly_alert.get("should_emit", False)):
                    anomaly_alert_id = self._persist_anomaly_alert(
                        camera_id=int(camera_id),
                        site_id=site_id,
                        gate_id=gate_id,
                        event_id=event_id,
                        access_log_id=access_log_id,
                        timestamp=timestamp,
                        plate_number=plate_number,
                        normalized_plate=compact_text or normalized_text or None,
                        snapshot_path=snapshot_path,
                        anomaly=anomaly,
                        consistency=consistency,
                        anomaly_alert=anomaly_alert,
                    )
                    if anomaly_alert_id is not None:
                        alert_ids.append(int(anomaly_alert_id))
                anomaly_alert["alert_id"] = int(anomaly_alert_id) if anomaly_alert_id is not None else None
                anomaly_alert["emitted"] = bool(anomaly_alert_id is not None)

        decision_event_id: Optional[int] = None
        if persist:
            unknown_bbox = plate_result.bbox if plate_result is not None and plate_result.bbox is not None else primary.bbox
            action_result = self.action_engine.handle_decision(
                request=access_decision_request,
                result=access_decision_result,
                camera_id=camera_id,
                zone_id=zone_id,
                frame_bgr=frame_bgr,
                bbox=unknown_bbox,
                confidence=overall_confidence,
                snapshot_path=snapshot_path,
                source_table="vehicle_events" if event_id is not None else None,
                source_detection_id=event_id,
                label=plate_display or plate_number,
                extra_data={
                    "plate_number": plate_number,
                    "plate_type": plate_type,
                    "vehicle_class": primary.class_name,
                    "track_id": primary_track_id,
                    "access_controller": {
                        "decision": access_decision.decision,
                        "reason": access_decision.reason,
                        "severity": access_decision.severity,
                        "flags": access_decision.flags,
                    },
                    "anomaly_detected": anomaly.get("detected"),
                    "anomaly_level": anomaly.get("level"),
                    "consistency_score": consistency.get("consistency_score"),
                    "consistency_level": consistency.get("confidence_level"),
                },
                detected_at=timestamp,
            )
            decision_event_id = action_result.get("event_id")
            unknown_detection_id = action_result.get("unknown_detection_id")

        resolved_status = (
            "recognized"
            if plate_number
            else ("plate_only_no_plate" if plate_only_fallback_used else "vehicle_without_plate")
        )
        plate_visibility = (
            "readable"
            if plate_number
            else ("visible_unreadable" if plate_bbox is not None else "invisible")
        )
        if plate_number:
            response_message = "Plaque detectee et analysee."
            response_reason = classifier_reason
        elif plate_bbox is not None:
            response_message = "Vehicule detecte, zone plaque trouvee mais matricule illisible."
            response_reason = "plate_unreadable"
        else:
            response_message = "Vehicule detecte, matricule invisible dans ce cadrage."
            response_reason = "plate_invisible"

        response = {
            "success": True,
            "status": resolved_status,
            "message": response_message,
            "vehicle_detected": bool(vehicle_detected),
            "plate_number": plate_number,
            "plate_display": plate_number,
            "plate_code": plate_code,
            "plate_city": plate_city,
            "plate_sequence": plate_sequence,
            "plate_type": plate_type,
            "confidence": overall_confidence,
            "plate_reliable": bool(plate_reliable),
            "raw_plate_text": raw_text or None,
            "normalized_plate": compact_text or normalized_text or None,
            "ocr_stabilization": ocr_stabilization or {"applied": False},
            "vehicle_profile": vehicle_profile,
            "consistency": consistency,
            "anomaly": anomaly,
            "anomaly_alert": anomaly_alert,
            "camera_id": camera_id,
            "site_id": site_id,
            "zone_id": zone_id,
            "gate_id": gate_id,
            "direction": str(direction or "IN").upper(),
            "track_id": primary_track_id,
            "timestamp": timestamp.isoformat(),
            "event_id": event_id,
            "decision_event_id": decision_event_id,
            "access_log_id": access_log_id,
            "security_alert_ids": alert_ids,
            "snapshot_path": snapshot_path,
            "vehicle_class": primary.class_name,
            "vehicle_confidence": float(primary.confidence),
            "plate_confidence": plate_confidence,
            "vehicle_bbox": self._bbox_to_dict(primary.bbox),
            "plate_bbox": plate_bbox,
            "security_tag": security_tag,
            "priority": is_priority,
            "reason": response_reason,
            "decision": access_decision.decision,
            "decision_reason": access_decision.reason,
            "requires_manual_review": access_decision.requires_manual_review,
            "alert_type": access_decision.alert_type,
            "access_decision": access_decision_result.decision,
            "access_reason_code": access_decision_result.reason_code,
            "access_explanation": access_decision_result.explanation,
            "access_checks": [check.to_dict() for check in access_decision_result.checks],
            "unknown_queue_action": access_decision_result.unknown_queue_action,
            "access_decision_result": access_decision_result.to_dict(),
            "visual_consistency": access_decision.visual_consistency,
            "dominant_color": access_decision.dominant_color,
            "plate_visibility": plate_visibility,
            "latency_ms": round(float(pipeline_latency_ms), 3),
            "detector_latency_ms": round(float(detect_latency_ms), 3),
            "ocr_latency_ms": round(float(ocr_latency_ms), 3),
            "classifier_latency_ms": round(float(classify_latency_ms), 3),
            "matched_registry": matched_registry,
            "unknown_detection_id": unknown_detection_id,
            "plate_only_fallback_attempted": bool(plate_only_fallback_attempted),
            "plate_only_fallback_used": bool(plate_only_fallback_used),
            "plate_only_fallback_reason": plate_only_fallback_reason,
            "pipeline": {
                "detector": primary.source,
                "tracker": tracker_backend,
                "ocr": plate_result.source if plate_result else "none",
                "normalizer": "rule_based",
                "classifier": "hybrid_rules",
                "detector_backend": self.detector.backend,
                "ocr_backend": self.plate_reader.backend,
                "plate_reliable": bool(plate_reliable),
            },
        }
        if cacheable:
            self._cache_set(cache_key, response)
        return response

    def _plate_parts_from_text(
        self,
        *,
        plate_text: Optional[str],
        plate_type: Optional[str],
    ) -> Dict[str, Optional[str]]:
        if not plate_text:
            return {
                "plate_display": None,
                "plate_code": None,
                "plate_city": None,
                "plate_sequence": None,
            }

        normalized = self.normalizer.normalize(str(plate_text))
        plate_code = normalized.plate_code
        plate_city = normalized.plate_city
        plate_sequence = normalized.plate_sequence
        plate_display = normalized.display_text or str(plate_text).strip().upper()

        if (plate_type or "").lower() == "civil" and plate_code and plate_sequence:
            plate_city = plate_city or self.default_civil_city
            plate_display = f"{plate_code} {plate_city} {plate_sequence}"

        return {
            "plate_display": plate_display,
            "plate_code": plate_code,
            "plate_city": plate_city,
            "plate_sequence": plate_sequence,
        }

    def get_history(
        self,
        camera_id: Optional[int] = None,
        plate_type: Optional[str] = None,
        plate_number: Optional[str] = None,
        dominant_color: Optional[str] = None,
        brand: Optional[str] = None,
        model: Optional[str] = None,
        body_style: Optional[str] = None,
        vehicle_type: Optional[str] = None,
        limit: int = 50,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        from vms.backend.models import VehicleEvent

        def _filter_unknown_attr(query, column):
            normalized = func.trim(func.lower(func.coalesce(column, "")))
            return query.filter(or_(column.is_(None), normalized == "", normalized == "unknown"))

        query = self.db.query(VehicleEvent)
        if camera_id is not None:
            query = query.filter(VehicleEvent.camera_id == camera_id)
        if plate_type is not None:
            query = query.filter(VehicleEvent.plate_type == plate_type)
        if plate_number:
            normalized = self.normalizer.normalize(plate_number)
            if normalized.compact_text:
                query = query.filter(VehicleEvent.normalized_plate.isnot(None))
                query = query.filter(VehicleEvent.normalized_plate.ilike(f"%{normalized.compact_text}%"))
            else:
                query = query.filter(VehicleEvent.plate_number.ilike(f"%{plate_number}%"))
        if dominant_color:
            if dominant_color == UNKNOWN_ATTRIBUTE_FILTER:
                query = _filter_unknown_attr(query, VehicleEvent.dominant_color)
            else:
                query = query.filter(func.lower(func.coalesce(VehicleEvent.dominant_color, "")) == str(dominant_color).strip().lower())
        if body_style:
            if body_style == UNKNOWN_ATTRIBUTE_FILTER:
                query = _filter_unknown_attr(query, VehicleEvent.body_style)
            else:
                query = query.filter(func.lower(func.coalesce(VehicleEvent.body_style, "")) == str(body_style).strip().lower())
        if vehicle_type:
            if vehicle_type == UNKNOWN_ATTRIBUTE_FILTER:
                query = _filter_unknown_attr(query, VehicleEvent.vehicle_type)
            else:
                query = query.filter(func.lower(func.coalesce(VehicleEvent.vehicle_type, "")) == str(vehicle_type).strip().lower())
        if brand:
            query = query.filter(VehicleEvent.brand.ilike(f"%{str(brand).strip()}%"))
        if model:
            query = query.filter(VehicleEvent.model.ilike(f"%{str(model).strip()}%"))

        rows = query.order_by(VehicleEvent.timestamp.desc()).offset(max(0, skip)).limit(max(1, limit)).all()
        out: List[Dict[str, Any]] = []
        for row in rows:
            plate_parts = self._plate_parts_from_text(
                plate_text=row.plate_number,
                plate_type=row.plate_type,
            )
            out.append(
                {
                    "id": row.id,
                    "plate_number": row.plate_number,
                    **plate_parts,
                    "plate_type": row.plate_type,
                    "confidence": float(row.confidence or 0.0),
                    "vehicle_detected": bool(row.vehicle_detected),
                    "vehicle_type": row.vehicle_type,
                    "body_style": row.body_style,
                    "dominant_color": row.dominant_color,
                    "brand": row.brand,
                    "model": row.model,
                    "vehicle_confidence": float(row.vehicle_confidence or 0.0),
                    "plate_confidence": float(row.plate_confidence or 0.0),
                    "camera_id": row.camera_id,
                    "zone_id": row.zone_id,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                    "snapshot_path": to_public_media_path(row.snapshot_path),
                    "security_tag": row.security_tag,
                    "severity": row.severity,
                    "is_priority": bool(row.is_priority),
                    "reason": row.reason,
                    "matched_registry": bool(row.matched_registry),
                    "consistency_score": float(row.consistency_score or 0.0),
                    "consistency_level": row.consistency_level or "low",
                    "consistency_flags": row.consistency_flags or [],
                    "anomaly_detected": bool(row.anomaly_detected),
                    "anomaly_level": row.anomaly_level or "none",
                    "anomaly_reason": row.anomaly_reason or "none",
                    "anomaly_flags": row.anomaly_flags or [],
                    "decision": (row.pipeline_meta or {}).get("access_decision") if row.pipeline_meta else None,
                    "decision_reason": (row.pipeline_meta or {}).get("access_reason") if row.pipeline_meta else None,
                    "requires_manual_review": bool((row.pipeline_meta or {}).get("requires_manual_review", False))
                    if row.pipeline_meta
                    else False,
                }
            )
        return out

    def get_statistics(self, hours: int = 24, camera_id: Optional[int] = None) -> Dict[str, Any]:
        from vms.backend.models import VehicleEvent

        cutoff = datetime.utcnow() - timedelta(hours=max(1, int(hours)))
        query = self.db.query(VehicleEvent).filter(VehicleEvent.timestamp >= cutoff)
        if camera_id is not None:
            query = query.filter(VehicleEvent.camera_id == camera_id)

        rows = query.all()
        total = len(rows)
        military = sum(1 for row in rows if (row.plate_type or "").lower() == "military")
        civil = sum(1 for row in rows if (row.plate_type or "").lower() == "civil")
        unknown = max(0, total - military - civil)
        avg_conf = float(sum(float(row.confidence or 0.0) for row in rows) / total) if total else 0.0
        avg_consistency = (
            float(sum(float(row.consistency_score or 0.0) for row in rows) / total) if total else 0.0
        )
        anomaly_events = sum(1 for row in rows if bool(row.anomaly_detected))

        return {
            "period_hours": hours,
            "camera_id": camera_id,
            "total_events": total,
            "military_events": military,
            "civil_events": civil,
            "unknown_events": unknown,
            "avg_confidence": round(avg_conf, 4),
            "avg_consistency_score": round(avg_consistency, 4),
            "anomaly_events": anomaly_events,
            "pipeline": {
                "detector_backend": self.detector.backend,
                "ocr_backend": self.plate_reader.backend,
                "tracker_backend": self.detection_module.tracker_backend_name,
                "classifier": "hybrid_rules",
            },
        }

    def get_live_monitoring(
        self,
        *,
        camera_id: Optional[int] = None,
        window_minutes: int = 60,
        bucket_seconds: int = 60,
        recent_limit: int = 8,
    ) -> Dict[str, Any]:
        return self.live_monitoring_module.collect(
            camera_id=camera_id,
            window_minutes=window_minutes,
            bucket_seconds=bucket_seconds,
            recent_limit=recent_limit,
        )

    def get_forensic_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        from vms.backend.models import SecurityAlert, VehicleAccessLog, VehicleEvent, VehicleEventFrame

        row = self.db.query(VehicleEvent).filter(VehicleEvent.id == int(event_id)).first()
        if row is None:
            return None

        frames = (
            self.db.query(VehicleEventFrame)
            .filter(VehicleEventFrame.event_id == int(event_id))
            .order_by(VehicleEventFrame.timestamp.asc(), VehicleEventFrame.id.asc())
            .all()
        )
        access_logs = (
            self.db.query(VehicleAccessLog)
            .filter(VehicleAccessLog.event_id == int(event_id))
            .order_by(VehicleAccessLog.timestamp.desc())
            .all()
        )
        alerts = (
            self.db.query(SecurityAlert)
            .filter(SecurityAlert.event_id == int(event_id))
            .order_by(SecurityAlert.timestamp.desc())
            .all()
        )
        plate_parts = self._plate_parts_from_text(
            plate_text=row.plate_number,
            plate_type=row.plate_type,
        )

        return {
            "event": {
                "id": row.id,
                "plate_number": row.plate_number,
                **plate_parts,
                "plate_type": row.plate_type,
                "confidence": float(row.confidence or 0.0),
                "vehicle_detected": bool(row.vehicle_detected),
                "vehicle_type": row.vehicle_type,
                "body_style": row.body_style,
                "dominant_color": row.dominant_color,
                "brand": row.brand,
                "model": row.model,
                "vehicle_confidence": float(row.vehicle_confidence or 0.0),
                "plate_confidence": float(row.plate_confidence or 0.0),
                "raw_plate_text": row.raw_plate_text,
                "normalized_plate": row.normalized_plate,
                "camera_id": row.camera_id,
                "zone_id": row.zone_id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "snapshot_path": to_public_media_path(row.snapshot_path),
                "severity": row.severity,
                "is_priority": bool(row.is_priority),
                "security_tag": row.security_tag,
                "reason": row.reason,
                "matched_registry": bool(row.matched_registry),
                "consistency_score": float(row.consistency_score or 0.0),
                "consistency_level": row.consistency_level or "low",
                "consistency_flags": row.consistency_flags or [],
                "anomaly_detected": bool(row.anomaly_detected),
                "anomaly_level": row.anomaly_level or "none",
                "anomaly_reason": row.anomaly_reason or "none",
                "anomaly_flags": row.anomaly_flags or [],
                "pipeline_meta": row.pipeline_meta or {},
            },
            "frames": [
                {
                    "id": f.id,
                    "frame_path": to_public_media_path(f.frame_path),
                    "timestamp": f.timestamp.isoformat() if f.timestamp else None,
                    "stage": f.stage,
                    "ocr_text": f.ocr_text,
                    "decision": f.decision,
                    "frame_meta": f.frame_meta or {},
                }
                for f in frames
            ],
            "access_logs": [
                {
                    "id": a.id,
                    "timestamp": a.timestamp.isoformat() if a.timestamp else None,
                    "decision": a.decision,
                    "reason": a.reason,
                    "direction": a.direction,
                    "confidence_score": float(a.confidence_score or 0.0),
                    "security_tag": a.security_tag,
                    "operator_id": a.operator_id,
                    "operator_note": a.operator_note,
                    "audit_meta": a.audit_meta or {},
                }
                for a in access_logs
            ],
            "alerts": [
                {
                    "id": al.id,
                    "type": al.type,
                    "severity_level": al.severity_level,
                    "resolution_status": al.resolution_status,
                    "timestamp": al.timestamp.isoformat() if al.timestamp else None,
                    "message": al.message,
                    "details": al.details or {},
                }
                for al in alerts
            ],
        }

    def get_access_logs(
        self,
        *,
        camera_id: Optional[int] = None,
        gate_id: Optional[str] = None,
        plate_number: Optional[str] = None,
        decision: Optional[str] = None,
        direction: Optional[str] = None,
        from_hours: int = 24,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return self.access_controller.list_access_logs(
            camera_id=camera_id,
            gate_id=gate_id,
            plate_number=plate_number,
            decision=decision,
            direction=direction,
            from_hours=from_hours,
            skip=skip,
            limit=limit,
        )

    def get_security_alerts(
        self,
        *,
        camera_id: Optional[int] = None,
        resolution_status: Optional[str] = None,
        severity_level: Optional[str] = None,
        alert_type: Optional[str] = None,
        from_hours: int = 72,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return self.access_controller.list_alerts(
            camera_id=camera_id,
            resolution_status=resolution_status,
            severity_level=severity_level,
            alert_type=alert_type,
            from_hours=from_hours,
            skip=skip,
            limit=limit,
        )

    def apply_manual_override(
        self,
        *,
        access_log_id: Optional[int],
        event_id: Optional[int],
        operator_id: int,
        operator_username: Optional[str],
        forced_decision: str,
        note: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        return self.access_controller.manual_override(
            access_log_id=access_log_id,
            event_id=event_id,
            operator_id=operator_id,
            operator_username=operator_username,
            forced_decision=forced_decision,
            note=note,
        )

    def _persist_event(
        self,
        plate_number: Optional[str],
        plate_type: str,
        confidence: float,
        camera_id: int,
        zone_id: Optional[int],
        site_id: Optional[int],
        snapshot_path: Optional[str],
        vehicle_detected: bool,
        vehicle_type: Optional[str],
        body_style: Optional[str],
        dominant_color: Optional[str],
        brand: Optional[str],
        model: Optional[str],
        vehicle_confidence: float,
        vehicle_bbox: Optional[Dict[str, int]],
        plate_confidence: float,
        plate_bbox: Optional[Dict[str, int]],
        raw_plate_text: Optional[str],
        normalized_plate: Optional[str],
        reason: str,
        severity: str,
        is_priority: bool,
        security_tag: Optional[str],
        matched_registry: bool,
        consistency_score: float,
        consistency_level: str,
        consistency_flags: List[str],
        anomaly_detected: bool,
        anomaly_level: str,
        anomaly_reason: str,
        anomaly_flags: List[str],
        pipeline_meta: Dict[str, Any],
    ) -> tuple[Optional[int], datetime]:
        from vms.backend.models import VehicleEvent

        now = datetime.utcnow()
        try:
            row = VehicleEvent(
                plate_number=plate_number,
                plate_type=plate_type,
                confidence=confidence,
                camera_id=camera_id,
                zone_id=zone_id,
                site_id=site_id if site_id is not None else self._resolve_site_id(camera_id=camera_id),
                timestamp=now,
                snapshot_path=snapshot_path,
                vehicle_detected=vehicle_detected,
                vehicle_type=vehicle_type,
                body_style=body_style,
                dominant_color=dominant_color,
                brand=brand,
                model=model,
                vehicle_confidence=vehicle_confidence,
                vehicle_bbox=vehicle_bbox,
                plate_confidence=plate_confidence,
                plate_bbox=plate_bbox,
                raw_plate_text=raw_plate_text,
                normalized_plate=normalized_plate,
                reason=reason,
                severity=severity,
                is_priority=is_priority,
                security_tag=security_tag,
                matched_registry=matched_registry,
                consistency_score=consistency_score,
                consistency_level=consistency_level,
                consistency_flags=consistency_flags,
                anomaly_detected=anomaly_detected,
                anomaly_level=anomaly_level,
                anomaly_reason=anomaly_reason,
                anomaly_flags=anomaly_flags,
                pipeline_meta=pipeline_meta,
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return int(row.id), row.timestamp or now
        except Exception:
            self.db.rollback()
            return None, now

    def _resolve_site_id(self, *, camera_id: int) -> Optional[int]:
        from vms.backend.models import Camera

        row = self.db.query(Camera.site_id).filter(Camera.id == int(camera_id)).first()
        if not row:
            return None
        return row[0]

    def _clean_vehicle_attr(self, value: Any) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        lowered = text.lower()
        if lowered in {"unknown", "none", "null", "n/a"}:
            return None
        if lowered in {"sedan_coupe", "suv_crossover", "compact_hatch", "truck", "bus", "motorcycle"}:
            return lowered
        return text

    def _persist_anomaly_alert(
        self,
        *,
        camera_id: int,
        site_id: Optional[int],
        gate_id: Optional[str],
        event_id: Optional[int],
        access_log_id: Optional[int],
        timestamp: datetime,
        plate_number: Optional[str],
        normalized_plate: Optional[str],
        snapshot_path: Optional[str],
        anomaly: Dict[str, Any],
        consistency: Dict[str, Any],
        anomaly_alert: Dict[str, Any],
    ) -> Optional[int]:
        from vms.backend.models import SecurityAlert

        try:
            row = SecurityAlert(
                type=str(anomaly_alert.get("alert_type") or "anomaly_consistency"),
                plate_number=plate_number,
                normalized_plate=normalized_plate,
                camera_id=int(camera_id),
                site_id=site_id,
                gate_id=gate_id,
                timestamp=timestamp,
                severity_level=str(anomaly_alert.get("severity_level") or "medium"),
                resolution_status="open",
                message=str(anomaly_alert.get("message") or "Vehicle anomaly detected"),
                event_id=event_id,
                access_log_id=access_log_id,
                snapshot_path=snapshot_path,
                details={
                    "reason": anomaly_alert.get("reason"),
                    "level": anomaly_alert.get("level"),
                    "base_level": anomaly_alert.get("base_level"),
                    "suppressed": bool(anomaly_alert.get("suppressed", False)),
                    "suppression_reason": anomaly_alert.get("suppression_reason"),
                    "rules_triggered": anomaly_alert.get("rules_triggered") or [],
                    "frequency_count": int(anomaly_alert.get("frequency_count") or 0),
                    "emit_count_window": int(anomaly_alert.get("emit_count_window") or 0),
                    "cooldown_remaining_sec": float(anomaly_alert.get("cooldown_remaining_sec") or 0.0),
                    "anomaly": anomaly,
                    "consistency": consistency,
                },
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return int(row.id)
        except Exception:
            self.db.rollback()
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
            ok, encoded = cv2.imencode(
                ".jpg",
                frame_bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), max(60, min(98, self.snapshot_quality))],
            )
            if ok:
                return encoded.tobytes()
        rgb = frame_bgr[:, :, ::-1]
        image = Image.fromarray(rgb)
        with io.BytesIO() as buf:
            image.save(buf, format="JPEG", quality=max(60, min(98, self.snapshot_quality)))
            return buf.getvalue()

    def _save_snapshot(self, image_bytes: bytes, camera_id: int, plate_type: str) -> str:
        base_dir = Path("data") / "vehicle_events"
        base_dir.mkdir(parents=True, exist_ok=True)
        filename = f"cam_{camera_id}_{plate_type}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        path = base_dir / filename
        path.write_bytes(image_bytes)
        return str(path).replace("\\", "/")

    def _save_forensic_frame(
        self,
        *,
        frame_bgr: np.ndarray,
        camera_id: int,
        event_id: int,
        stage: str,
    ) -> str:
        base_dir = Path("data") / "vehicle_event_frames"
        base_dir.mkdir(parents=True, exist_ok=True)
        filename = (
            f"evt_{int(event_id)}_cam_{int(camera_id)}_{stage}_"
            f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        )
        path = base_dir / filename
        image_bytes = self._frame_to_jpeg_bytes(frame_bgr)
        path.write_bytes(image_bytes)
        return str(path).replace("\\", "/")

    def _persist_event_frame(
        self,
        *,
        event_id: int,
        frame_path: Optional[str],
        stage: str,
        timestamp: datetime,
        ocr_text: Optional[str],
        decision: Optional[str],
        frame_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        if not frame_path:
            return None
        from vms.backend.models import VehicleEventFrame

        try:
            row = VehicleEventFrame(
                event_id=int(event_id),
                frame_path=frame_path,
                timestamp=timestamp,
                stage=str(stage or "full_frame"),
                ocr_text=ocr_text,
                decision=decision,
                frame_meta=frame_meta or {},
            )
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return int(row.id)
        except Exception:
            self.db.rollback()
            return None

    def _bbox_to_dict(self, bbox: Optional[tuple[int, int, int, int]]) -> Optional[Dict[str, int]]:
        if bbox is None:
            return None
        x, y, w, h = bbox
        return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}

    def _combine_confidence(
        self,
        vehicle_confidence: float,
        plate_confidence: float,
        classifier_confidence: float,
        has_plate: bool,
    ) -> float:
        if not has_plate:
            return round(float(max(0.0, min(1.0, 0.70 * vehicle_confidence))), 4)
        score = (0.30 * vehicle_confidence) + (0.45 * plate_confidence) + (0.25 * classifier_confidence)
        return round(float(max(0.0, min(1.0, score))), 4)

    def _merge_severity(self, primary: str, secondary: str) -> str:
        order = {"info": 1, "low": 1, "warning": 2, "medium": 2, "high": 3, "critical": 4}
        p = str(primary or "info").lower()
        s = str(secondary or "info").lower()
        return p if order.get(p, 1) >= order.get(s, 1) else s

    def _build_cache_key(
        self,
        *,
        frame_bgr: np.ndarray,
        camera_id: int,
        zone_id: Optional[int],
        gate_id: Optional[str],
        direction: str,
        save_snapshot: bool,
    ) -> str:
        digest = hashlib.sha1(frame_bgr.tobytes()).hexdigest()
        return json.dumps(
            {
                "cam": int(camera_id),
                "zone": int(zone_id) if zone_id is not None else None,
                "gate": str(gate_id or ""),
                "direction": str(direction or "IN").upper(),
                "save_snapshot": bool(save_snapshot),
                "digest": digest,
            },
            sort_keys=True,
        )

    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        now = datetime.utcnow().timestamp()
        with self._result_cache_lock:
            row = self._result_cache.get(key)
            if row is None:
                return None
            expires_at = float(row.get("_expires_at", 0))
            if now > expires_at:
                self._result_cache.pop(key, None)
                return None
            payload = dict(row.get("payload", {}))
            payload["cache_hit"] = True
            return payload

    def _cache_set(self, key: str, payload: Dict[str, Any]) -> None:
        now = datetime.utcnow().timestamp()
        with self._result_cache_lock:
            if len(self._result_cache) >= self.cache_max_entries:
                # Remove oldest entry.
                oldest_key = min(self._result_cache, key=lambda k: float(self._result_cache[k].get("_saved_at", now)))
                self._result_cache.pop(oldest_key, None)
            self._result_cache[key] = {
                "_saved_at": now,
                "_expires_at": now + max(0.1, self.cache_ttl_sec),
                "payload": dict(payload),
            }
