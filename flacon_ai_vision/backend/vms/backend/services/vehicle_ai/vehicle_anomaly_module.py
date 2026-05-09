from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict, List


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


@dataclass(frozen=True)
class AnomalyThresholds:
    medium: float = 0.60
    high: float = 0.45
    critical: float = 0.30
    mismatch_high_count: int = 2


class VehicleAnomalyModule:
    """
    Rule-based anomaly engine.
    Inputs: only consistency score + consistency flags.
    No ML. Deterministic and explainable.
    """

    _LEVEL_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    _MISMATCH_FLAGS = {"brand_mismatch_registry", "color_mismatch_registry", "plate_type_mismatch"}

    def __init__(self):
        self.enabled = str(os.getenv("VEHICLE_ANOMALY_ENABLE", "true")).strip().lower() == "true"
        self.thresholds = AnomalyThresholds(
            medium=_to_float(os.getenv("VEHICLE_ANOMALY_MEDIUM_SCORE", "0.60"), 0.60),
            high=_to_float(os.getenv("VEHICLE_ANOMALY_HIGH_SCORE", "0.45"), 0.45),
            critical=_to_float(os.getenv("VEHICLE_ANOMALY_CRITICAL_SCORE", "0.30"), 0.30),
            mismatch_high_count=max(1, int(_to_float(os.getenv("VEHICLE_ANOMALY_MISMATCH_HIGH_COUNT", "2"), 2))),
        )

    def evaluate(self, *, consistency: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return self._none(anomaly_score=0.0, reason="anomaly_engine_disabled")

        score = _clamp01(_to_float(consistency.get("consistency_score"), 0.0))
        flags = sorted(set(str(item).strip() for item in (consistency.get("flags") or []) if str(item).strip()))

        # Explicit bypass for non-detection flow.
        if score <= 0.0 and flags == ["no_vehicle_detected"]:
            return self._none(anomaly_score=0.0, reason="no_vehicle_detected")

        level = "none"
        reason = "none"
        rules_triggered: List[str] = []

        if score < self.thresholds.critical:
            level = "critical"
            reason = "critical_low_consistency"
            rules_triggered.append("score_below_critical")
        elif score < self.thresholds.high:
            level = "high"
            reason = "high_low_consistency"
            rules_triggered.append("score_below_high")
        elif score < self.thresholds.medium:
            level = "medium"
            reason = "medium_low_consistency"
            rules_triggered.append("score_below_medium")

        mismatch_count = len(self._MISMATCH_FLAGS.intersection(set(flags)))
        if mismatch_count >= self.thresholds.mismatch_high_count:
            level = self._max_level(level, "high")
            if reason == "none":
                reason = "multi_registry_mismatch"
            rules_triggered.append("multi_registry_mismatch")
        elif mismatch_count == 1 and score < 0.75:
            level = self._max_level(level, "medium")
            if reason == "none":
                reason = "single_registry_mismatch"
            rules_triggered.append("single_registry_mismatch")

        if "low_ocr_stability" in flags and "tracker_unstable" in flags:
            level = self._max_level(level, "medium")
            if reason == "none":
                reason = "ocr_tracker_unstable"
            rules_triggered.append("ocr_tracker_unstable")

        detected = self._LEVEL_ORDER[level] > 0
        anomaly_score = self._build_anomaly_score(score=score, flags=flags)

        return {
            "detected": bool(detected),
            "level": level,
            "reason": reason,
            "flags": flags,
            "rules_triggered": sorted(set(rules_triggered)),
            "anomaly_score": round(float(anomaly_score), 4),
        }

    def _build_anomaly_score(self, *, score: float, flags: List[str]) -> float:
        flag_penalty = min(1.0, float(len(flags)) / 4.0)
        anomaly_score = ((1.0 - score) * 0.80) + (flag_penalty * 0.20)
        return _clamp01(anomaly_score)

    def _max_level(self, left: str, right: str) -> str:
        return left if self._LEVEL_ORDER.get(left, 0) >= self._LEVEL_ORDER.get(right, 0) else right

    def _none(self, *, anomaly_score: float, reason: str) -> Dict[str, Any]:
        return {
            "detected": False,
            "level": "none",
            "reason": str(reason or "none"),
            "flags": [],
            "rules_triggered": [],
            "anomaly_score": round(float(_clamp01(anomaly_score)), 4),
        }

