from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _normalize_plate_compact(value: Any) -> str:
    return re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", str(value or "").strip().upper())


@dataclass(frozen=True)
class AlertEngineConfig:
    cooldown_sec: float
    frequency_window_sec: float
    spam_window_sec: float
    spam_max_emits: int
    escalate_high_count: int
    escalate_critical_count: int


class VehicleAlertEngineModule:
    """
    Deterministic alert engine based only on anomaly+consistency signals.
    - Cooldown configurable
    - Anti-spam configurable
    - Frequency escalation
    """

    _state_lock = Lock()
    _anomaly_seen_by_stream: Dict[str, List[float]] = {}
    _alert_emits_by_stream: Dict[str, List[float]] = {}
    _last_emit_by_stream_reason: Dict[Tuple[str, str], float] = {}
    _last_emit_level_by_stream: Dict[str, str] = {}

    _LEVEL_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    _LEVEL_TO_SEVERITY = {"none": "low", "low": "low", "medium": "medium", "high": "high", "critical": "critical"}

    def __init__(self):
        self.enabled = str(os.getenv("VEHICLE_ALERT_ENGINE_ENABLE", "true")).strip().lower() == "true"
        self.config = AlertEngineConfig(
            cooldown_sec=max(0.0, _to_float(os.getenv("VEHICLE_ALERT_COOLDOWN_SEC", "30"), 30.0)),
            frequency_window_sec=max(10.0, _to_float(os.getenv("VEHICLE_ALERT_FREQUENCY_WINDOW_SEC", "300"), 300.0)),
            spam_window_sec=max(10.0, _to_float(os.getenv("VEHICLE_ALERT_SPAM_WINDOW_SEC", "120"), 120.0)),
            spam_max_emits=max(1, int(_to_float(os.getenv("VEHICLE_ALERT_SPAM_MAX_EMITS", "4"), 4))),
            escalate_high_count=max(2, int(_to_float(os.getenv("VEHICLE_ALERT_ESCALATE_HIGH_COUNT", "3"), 3))),
            escalate_critical_count=max(3, int(_to_float(os.getenv("VEHICLE_ALERT_ESCALATE_CRITICAL_COUNT", "6"), 6))),
        )

    def evaluate(
        self,
        *,
        camera_id: int,
        track_id: Optional[int],
        plate_number: Optional[str],
        anomaly: Dict[str, Any],
        consistency: Dict[str, Any],
        reference_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = reference_time or datetime.now(timezone.utc)
        now_ts = float(now.timestamp())
        stream_key = self._build_stream_key(
            camera_id=int(camera_id),
            track_id=track_id,
            plate_number=plate_number,
        )
        anomaly_level = str(anomaly.get("level") or "none").strip().lower()
        anomaly_reason = str(anomaly.get("reason") or "none").strip().lower()
        anomaly_detected = bool(anomaly.get("detected", False))
        consistency_score = _clamp01(_to_float(consistency.get("consistency_score"), 0.0))

        if not self.enabled:
            return self._decision(
                stream_key=stream_key,
                should_emit=False,
                suppressed=True,
                suppression_reason="engine_disabled",
                level="none",
                base_level="none",
                reason="engine_disabled",
                frequency_count=0,
                emit_count_window=0,
                cooldown_remaining_sec=0.0,
                rules_triggered=[],
                anomaly_score=_clamp01(_to_float(anomaly.get("anomaly_score"), 0.0)),
                consistency_score=consistency_score,
            )

        if not anomaly_detected or anomaly_level in {"none", ""}:
            return self._decision(
                stream_key=stream_key,
                should_emit=False,
                suppressed=False,
                suppression_reason="",
                level="none",
                base_level="none",
                reason=anomaly_reason or "none",
                frequency_count=0,
                emit_count_window=0,
                cooldown_remaining_sec=0.0,
                rules_triggered=[],
                anomaly_score=_clamp01(_to_float(anomaly.get("anomaly_score"), 1.0 - consistency_score)),
                consistency_score=consistency_score,
            )

        if stream_key is None:
            stream_key = f"cam:{int(camera_id)}:fallback"

        base_level = anomaly_level if anomaly_level in self._LEVEL_ORDER else "medium"
        rules_triggered: List[str] = []

        with self._state_lock:
            seen = self._anomaly_seen_by_stream.get(stream_key, [])
            seen = [ts for ts in seen if (now_ts - ts) <= self.config.frequency_window_sec]
            seen.append(now_ts)
            self._anomaly_seen_by_stream[stream_key] = seen
            frequency_count = len(seen)

            final_level = base_level
            if frequency_count >= self.config.escalate_critical_count:
                final_level = "critical"
                rules_triggered.append("frequency_escalated_critical")
            elif frequency_count >= self.config.escalate_high_count:
                final_level = self._max_level(final_level, "high")
                if final_level in {"high", "critical"}:
                    rules_triggered.append("frequency_escalated_high")

            emits = self._alert_emits_by_stream.get(stream_key, [])
            emits = [ts for ts in emits if (now_ts - ts) <= self.config.spam_window_sec]
            self._alert_emits_by_stream[stream_key] = emits
            emit_count_window = len(emits)

            cooldown_key = (stream_key, anomaly_reason or "anomaly")
            last_emit_ts = self._last_emit_by_stream_reason.get(cooldown_key)
            cooldown_remaining_sec = 0.0
            cooldown_active = False
            if last_emit_ts is not None:
                delta = now_ts - float(last_emit_ts)
                if delta < self.config.cooldown_sec:
                    cooldown_active = True
                    cooldown_remaining_sec = max(0.0, self.config.cooldown_sec - delta)

            last_level = self._last_emit_level_by_stream.get(stream_key, "none")
            escalation_upgrade = self._LEVEL_ORDER.get(final_level, 0) > self._LEVEL_ORDER.get(last_level, 0)

            if cooldown_active and not escalation_upgrade and final_level != "critical":
                return self._decision(
                    stream_key=stream_key,
                    should_emit=False,
                    suppressed=True,
                    suppression_reason="cooldown",
                    level=final_level,
                    base_level=base_level,
                    reason=anomaly_reason or "anomaly_detected",
                    frequency_count=frequency_count,
                    emit_count_window=emit_count_window,
                    cooldown_remaining_sec=cooldown_remaining_sec,
                    rules_triggered=rules_triggered,
                    anomaly_score=_clamp01(_to_float(anomaly.get("anomaly_score"), 1.0 - consistency_score)),
                    consistency_score=consistency_score,
                )

            if emit_count_window >= self.config.spam_max_emits and final_level in {"low", "medium"}:
                return self._decision(
                    stream_key=stream_key,
                    should_emit=False,
                    suppressed=True,
                    suppression_reason="anti_spam",
                    level=final_level,
                    base_level=base_level,
                    reason=anomaly_reason or "anomaly_detected",
                    frequency_count=frequency_count,
                    emit_count_window=emit_count_window,
                    cooldown_remaining_sec=0.0,
                    rules_triggered=rules_triggered + ["anti_spam_suppressed"],
                    anomaly_score=_clamp01(_to_float(anomaly.get("anomaly_score"), 1.0 - consistency_score)),
                    consistency_score=consistency_score,
                )

            emits.append(now_ts)
            self._alert_emits_by_stream[stream_key] = emits
            self._last_emit_by_stream_reason[cooldown_key] = now_ts
            self._last_emit_level_by_stream[stream_key] = final_level

            return self._decision(
                stream_key=stream_key,
                should_emit=True,
                suppressed=False,
                suppression_reason="",
                level=final_level,
                base_level=base_level,
                reason=anomaly_reason or "anomaly_detected",
                frequency_count=frequency_count,
                emit_count_window=len(emits),
                cooldown_remaining_sec=0.0,
                rules_triggered=rules_triggered,
                anomaly_score=_clamp01(_to_float(anomaly.get("anomaly_score"), 1.0 - consistency_score)),
                consistency_score=consistency_score,
            )

    def _decision(
        self,
        *,
        stream_key: str,
        should_emit: bool,
        suppressed: bool,
        suppression_reason: str,
        level: str,
        base_level: str,
        reason: str,
        frequency_count: int,
        emit_count_window: int,
        cooldown_remaining_sec: float,
        rules_triggered: List[str],
        anomaly_score: float,
        consistency_score: float,
    ) -> Dict[str, Any]:
        resolved_level = level if level in self._LEVEL_ORDER else "none"
        severity = self._LEVEL_TO_SEVERITY.get(resolved_level, "low")
        reason_token = str(reason or "anomaly_detected").replace("_", " ")
        message = (
            f"Vehicle anomaly {resolved_level}: {reason_token} "
            f"(consistency={consistency_score:.2f}, anomaly={anomaly_score:.2f})"
        )
        return {
            "enabled": bool(self.enabled),
            "should_emit": bool(should_emit),
            "suppressed": bool(suppressed),
            "suppression_reason": str(suppression_reason or ""),
            "alert_type": "anomaly_consistency",
            "severity_level": severity,
            "base_level": base_level,
            "level": resolved_level,
            "reason": str(reason or "anomaly_detected"),
            "message": message,
            "rules_triggered": sorted(set(str(rule) for rule in rules_triggered if str(rule).strip())),
            "frequency_count": int(max(0, frequency_count)),
            "emit_count_window": int(max(0, emit_count_window)),
            "cooldown_remaining_sec": round(float(max(0.0, cooldown_remaining_sec)), 3),
            "stream_key": stream_key,
            "anomaly_score": round(float(_clamp01(anomaly_score)), 4),
            "consistency_score": round(float(_clamp01(consistency_score)), 4),
        }

    def _build_stream_key(
        self,
        *,
        camera_id: int,
        track_id: Optional[int],
        plate_number: Optional[str],
    ) -> Optional[str]:
        if track_id is not None:
            return f"cam:{int(camera_id)}:track:{int(track_id)}"
        compact = _normalize_plate_compact(plate_number)
        if compact:
            return f"cam:{int(camera_id)}:plate:{compact}"
        return None

    def _max_level(self, left: str, right: str) -> str:
        return left if self._LEVEL_ORDER.get(left, 0) >= self._LEVEL_ORDER.get(right, 0) else right

