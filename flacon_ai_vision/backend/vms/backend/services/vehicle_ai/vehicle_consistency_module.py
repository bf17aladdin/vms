from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from threading import Lock
from typing import Any, Dict, Optional


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_plate_compact(value: Any) -> str:
    return re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", str(value or "").strip().upper())


@dataclass(frozen=True)
class ConsistencyWeights:
    ocr_stability: float = 0.25
    tracker_stability: float = 0.15
    brand_consistency: float = 0.20
    color_consistency: float = 0.10
    registry_match: float = 0.20
    plate_vehicle_alignment: float = 0.10

    def as_dict(self) -> Dict[str, float]:
        total = (
            float(self.ocr_stability)
            + float(self.tracker_stability)
            + float(self.brand_consistency)
            + float(self.color_consistency)
            + float(self.registry_match)
            + float(self.plate_vehicle_alignment)
        )
        if total <= 0:
            return {
                "ocr_stability": 0.25,
                "tracker_stability": 0.15,
                "brand_consistency": 0.20,
                "color_consistency": 0.10,
                "registry_match": 0.20,
                "plate_vehicle_alignment": 0.10,
            }
        return {
            "ocr_stability": float(self.ocr_stability) / total,
            "tracker_stability": float(self.tracker_stability) / total,
            "brand_consistency": float(self.brand_consistency) / total,
            "color_consistency": float(self.color_consistency) / total,
            "registry_match": float(self.registry_match) / total,
            "plate_vehicle_alignment": float(self.plate_vehicle_alignment) / total,
        }


class VehicleConsistencyModule:
    """Computes a weighted, explainable and smoothed vehicle consistency score."""

    _state_lock = Lock()
    _stream_state: Dict[str, Dict[str, Any]] = {}

    def __init__(self):
        self.weights = ConsistencyWeights(
            ocr_stability=_to_float(os.getenv("VEHICLE_CONSISTENCY_W_OCR", "0.25"), 0.25),
            tracker_stability=_to_float(os.getenv("VEHICLE_CONSISTENCY_W_TRACKER", "0.15"), 0.15),
            brand_consistency=_to_float(os.getenv("VEHICLE_CONSISTENCY_W_BRAND", "0.20"), 0.20),
            color_consistency=_to_float(os.getenv("VEHICLE_CONSISTENCY_W_COLOR", "0.10"), 0.10),
            registry_match=_to_float(os.getenv("VEHICLE_CONSISTENCY_W_REGISTRY", "0.20"), 0.20),
            plate_vehicle_alignment=_to_float(os.getenv("VEHICLE_CONSISTENCY_W_ALIGNMENT", "0.10"), 0.10),
        )
        self.weight_map = self.weights.as_dict()
        self.smoothing_alpha = _clamp01(_to_float(os.getenv("VEHICLE_CONSISTENCY_SMOOTHING_ALPHA", "0.45"), 0.45))
        self.stream_max_age_sec = max(0.5, _to_float(os.getenv("VEHICLE_CONSISTENCY_STREAM_MAX_AGE_SEC", "4.0"), 4.0))

    def empty_result(self, *, flag: str = "no_vehicle_detected") -> Dict[str, Any]:
        reasons = {
            "ocr_stability": 0.0,
            "tracker_stability": 0.0,
            "brand_consistency": 0.0,
            "color_consistency": 0.0,
            "registry_match": 0.0,
            "plate_vehicle_alignment": 0.0,
        }
        return {
            "consistency_score": 0.0,
            "confidence_level": "low",
            "reasons": reasons,
            "flags": [flag] if flag else [],
            "debug": {
                "raw_score": 0.0,
                "smoothed_score": 0.0,
                "samples": 0,
                "stream_key": None,
                "weights": self.weight_map,
            },
        }

    def compute(
        self,
        *,
        camera_id: int,
        track_id: Optional[int],
        plate_number: Optional[str],
        plate_type: str,
        plate_reliable: bool,
        plate_confidence: float,
        vehicle_detected: bool,
        vehicle_class: Optional[str],
        matched_registry: bool,
        ocr_stabilization: Optional[Dict[str, Any]],
        vehicle_profile: Optional[Dict[str, Any]],
        plate_only_fallback_used: bool,
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = reference_time or datetime.now(timezone.utc)
        now_ts = float(now.timestamp())
        flags: list[str] = []
        profile = vehicle_profile or {}
        registry_category = _normalize_text(profile.get("registry_category"))

        ocr_score = self._score_ocr(
            plate_reliable=plate_reliable,
            plate_confidence=plate_confidence,
            ocr_stabilization=ocr_stabilization,
            flags=flags,
        )
        tracker_score = self._score_tracker(
            camera_id=int(camera_id),
            track_id=track_id,
            vehicle_detected=bool(vehicle_detected),
            now_ts=now_ts,
            flags=flags,
        )
        brand_score = self._score_brand(
            matched_registry=bool(matched_registry),
            vehicle_profile=profile,
            flags=flags,
        )
        color_score = self._score_color(
            matched_registry=bool(matched_registry),
            vehicle_profile=profile,
            flags=flags,
        )
        registry_score = self._score_registry(
            matched_registry=bool(matched_registry),
            plate_number=plate_number,
        )
        alignment_score = self._score_plate_vehicle_alignment(
            plate_type=plate_type,
            vehicle_class=vehicle_class,
            plate_reliable=bool(plate_reliable),
            vehicle_detected=bool(vehicle_detected),
            plate_only_fallback_used=bool(plate_only_fallback_used),
            registry_category=registry_category,
            flags=flags,
        )

        reasons = {
            "ocr_stability": _clamp01(ocr_score),
            "tracker_stability": _clamp01(tracker_score),
            "brand_consistency": _clamp01(brand_score),
            "color_consistency": _clamp01(color_score),
            "registry_match": _clamp01(registry_score),
            "plate_vehicle_alignment": _clamp01(alignment_score),
        }
        raw_score = _clamp01(
            sum(float(reasons[key]) * float(self.weight_map.get(key, 0.0)) for key in reasons.keys())
        )
        stream_key = self._build_stream_key(
            camera_id=int(camera_id),
            track_id=track_id,
            plate_number=plate_number,
        )
        smoothed_score, samples = self._smooth_score(
            stream_key=stream_key,
            raw_score=raw_score,
            now_ts=now_ts,
        )
        level = self._confidence_level(smoothed_score)
        uniq_flags = sorted(set(flag for flag in flags if flag))

        return {
            "consistency_score": round(float(smoothed_score), 4),
            "confidence_level": level,
            "reasons": {key: round(float(value), 3) for key, value in reasons.items()},
            "flags": uniq_flags,
            "debug": {
                "raw_score": round(float(raw_score), 4),
                "smoothed_score": round(float(smoothed_score), 4),
                "samples": int(samples),
                "stream_key": stream_key,
                "weights": self.weight_map,
            },
        }

    def _score_ocr(
        self,
        *,
        plate_reliable: bool,
        plate_confidence: float,
        ocr_stabilization: Optional[Dict[str, Any]],
        flags: list[str],
    ) -> float:
        if ocr_stabilization:
            stability_ratio = _clamp01(_to_float(ocr_stabilization.get("stability_ratio", 0.0), 0.0))
            applied = bool(ocr_stabilization.get("applied", False))
            if applied:
                score = stability_ratio
            else:
                score = max(0.20 if plate_reliable else 0.10, stability_ratio * 0.60)
        else:
            score = (0.35 + (0.65 * _clamp01(plate_confidence))) if plate_reliable else 0.12

        if score < 0.40:
            flags.append("low_ocr_stability")
        return _clamp01(score)

    def _score_tracker(
        self,
        *,
        camera_id: int,
        track_id: Optional[int],
        vehicle_detected: bool,
        now_ts: float,
        flags: list[str],
    ) -> float:
        if not vehicle_detected:
            flags.append("tracker_unstable")
            return 0.20
        if track_id is None:
            flags.append("tracker_unstable")
            return 0.45

        key = f"cam:{int(camera_id)}:track:{int(track_id)}"
        with self._state_lock:
            state = self._stream_state.get(key, {})
            last_seen_ts = _to_float(state.get("last_seen_ts", now_ts), now_ts)
            gap = max(0.0, now_ts - last_seen_ts)

            if state and gap <= self.stream_max_age_sec:
                seen = int(state.get("tracker_seen", 0)) + 1
                continuity = max(0.65, 1.0 - ((gap / self.stream_max_age_sec) * 0.35))
                score = min(1.0, 0.58 + min(0.35, 0.06 * seen)) * continuity
            else:
                seen = 1
                score = 0.58

            state["tracker_seen"] = int(seen)
            state["last_seen_ts"] = float(now_ts)
            state["tracker_score"] = float(score)
            self._stream_state[key] = state

        if score < 0.45:
            flags.append("tracker_unstable")
        return _clamp01(score)

    def _score_brand(
        self,
        *,
        matched_registry: bool,
        vehicle_profile: Dict[str, Any],
        flags: list[str],
    ) -> float:
        brand = _normalize_text(vehicle_profile.get("brand"))
        brand_source = _normalize_text(vehicle_profile.get("brand_source"))
        registry_brand = _normalize_text(vehicle_profile.get("registry_make"))

        if matched_registry:
            if brand_source == "registry":
                return 1.0
            if registry_brand and brand and registry_brand != brand:
                flags.append("brand_mismatch_registry")
                return 0.20
            if brand_source and brand_source not in {"registry", ""}:
                flags.append("brand_mismatch_registry")
                return 0.25
            if brand:
                return 0.78
            return 0.60

        if brand:
            return 0.72
        return 0.50

    def _score_color(
        self,
        *,
        matched_registry: bool,
        vehicle_profile: Dict[str, Any],
        flags: list[str],
    ) -> float:
        color = _normalize_text(vehicle_profile.get("dominant_color"))
        registry_color = _normalize_text(vehicle_profile.get("registry_color"))

        if matched_registry and registry_color:
            if color == registry_color:
                return 1.0
            if self._is_neutral_pair(color, registry_color):
                return 0.80
            if color and color != "unknown":
                flags.append("color_mismatch_registry")
                return 0.25
            return 0.40

        if color and color != "unknown":
            return 0.72
        return 0.50

    def _score_registry(self, *, matched_registry: bool, plate_number: Optional[str]) -> float:
        if matched_registry:
            return 1.0
        if plate_number:
            return 0.30
        return 0.45

    def _score_plate_vehicle_alignment(
        self,
        *,
        plate_type: str,
        vehicle_class: Optional[str],
        plate_reliable: bool,
        vehicle_detected: bool,
        plate_only_fallback_used: bool,
        registry_category: str,
        flags: list[str],
    ) -> float:
        plate_norm = _normalize_text(plate_type)
        vehicle_norm = _normalize_text(vehicle_class)
        registry_norm = "military" if registry_category.startswith("mil") else ("civil" if registry_category else "")

        if vehicle_detected and plate_norm in {"civil", "military"}:
            score = 0.90
        else:
            score = 0.60

        if plate_norm == "unknown":
            score = min(score, 0.50)
        if not plate_reliable:
            score = min(score, 0.45)
        if plate_only_fallback_used:
            score = min(score, 0.55)
        if vehicle_norm in {"", "unknown"}:
            score = min(score, 0.65)

        if registry_norm and plate_norm in {"civil", "military"} and registry_norm != plate_norm:
            flags.append("plate_type_mismatch")
            score = min(score, 0.15)

        return _clamp01(score)

    def _smooth_score(
        self,
        *,
        stream_key: Optional[str],
        raw_score: float,
        now_ts: float,
    ) -> tuple[float, int]:
        if not stream_key:
            return raw_score, 1

        with self._state_lock:
            state = self._stream_state.get(stream_key, {})
            prev_score = state.get("consistency_score")
            prev_ts = _to_float(state.get("consistency_ts", now_ts), now_ts)
            gap = max(0.0, now_ts - prev_ts)

            if prev_score is not None and gap <= self.stream_max_age_sec:
                smoothed = _clamp01(float(prev_score) + (self.smoothing_alpha * (raw_score - float(prev_score))))
                samples = int(state.get("consistency_samples", 0)) + 1
            else:
                smoothed = _clamp01(raw_score)
                samples = 1

            state["consistency_score"] = float(smoothed)
            state["consistency_ts"] = float(now_ts)
            state["consistency_samples"] = int(samples)
            state["last_seen_ts"] = float(now_ts)
            self._stream_state[stream_key] = state

        return smoothed, samples

    def _build_stream_key(
        self,
        *,
        camera_id: int,
        track_id: Optional[int],
        plate_number: Optional[str],
    ) -> Optional[str]:
        if track_id is not None:
            return f"cam:{int(camera_id)}:track:{int(track_id)}"
        plate_compact = _normalize_plate_compact(plate_number)
        if plate_compact:
            return f"cam:{int(camera_id)}:plate:{plate_compact}"
        return None

    def _confidence_level(self, score: float) -> str:
        if score >= 0.80:
            return "high"
        if score >= 0.60:
            return "medium"
        return "low"

    def _is_neutral_pair(self, a: str, b: str) -> bool:
        neutral_groups = ({"black", "gray", "silver"}, {"white", "gray", "silver"})
        for group in neutral_groups:
            if a in group and b in group:
                return True
        return False

