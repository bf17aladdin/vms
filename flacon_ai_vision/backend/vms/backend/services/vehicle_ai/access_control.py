from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

from vms.backend.core.media_paths import to_public_media_path

from .plate_normalizer import PlateNormalizer


@dataclass
class VehicleAccessDecision:
    decision: str
    reason: str
    severity: str
    requires_manual_review: bool
    is_priority: bool
    should_alert: bool
    alert_type: Optional[str]
    alert_message: Optional[str]
    confidence_score: float
    registry_vehicle_id: Optional[int]
    registry_matched: bool
    security_tag: Optional[str]
    normalized_plate: Optional[str]
    dominant_color: Optional[str]
    visual_consistency: float
    flags: List[str] = field(default_factory=list)


class VehicleAccessController:
    """Access-control decision engine for high-security vehicle gates."""

    def __init__(self, db: Session, normalizer: Optional[PlateNormalizer] = None):
        self.db = db
        self.normalizer = normalizer or PlateNormalizer()

        self.allow_threshold = float(os.getenv("VEHICLE_ACCESS_MIN_CONF_ALLOW", "0.85"))
        self.review_threshold = float(os.getenv("VEHICLE_ACCESS_MIN_CONF_REVIEW", "0.65"))
        self.require_registry = os.getenv("VEHICLE_ACCESS_REQUIRE_REGISTRY", "true").lower() == "true"
        self.unknown_policy = str(os.getenv("VEHICLE_ACCESS_UNKNOWN_POLICY", "deny")).strip().lower()
        self.enable_visual_check = os.getenv("VEHICLE_ACCESS_ENABLE_VISUAL_CHECK", "true").lower() == "true"
        self.visual_mismatch_threshold = float(os.getenv("VEHICLE_ACCESS_VISUAL_MISMATCH_THRESHOLD", "0.40"))
        self.signal_window_minutes = max(1, int(os.getenv("VEHICLE_ACCESS_VISUAL_WINDOW_MINUTES", "120")))

    def evaluate(
        self,
        *,
        plate_number: Optional[str],
        plate_type: str,
        confidence: float,
        plate_confidence: float,
        vehicle_type: Optional[str],
        vehicle_bbox: Optional[Tuple[int, int, int, int]],
        frame_bgr: Optional[np.ndarray],
        classifier_security_tag: Optional[str],
        classifier_registry_match: bool,
    ) -> VehicleAccessDecision:
        normalized_plate = None
        if plate_number:
            normalized = self.normalizer.normalize(plate_number)
            normalized_plate = normalized.compact_text or normalized.normalized_text.replace(" ", "")

        registry_vehicle = self._find_registry_vehicle(normalized_plate=normalized_plate)

        flags: List[str] = []
        registry_matched = registry_vehicle is not None or bool(classifier_registry_match)

        if not normalized_plate:
            flags.append("plate_missing")
        elif registry_vehicle is None and self.require_registry:
            flags.append("not_in_registry")

        if registry_vehicle is not None:
            if self._is_registry_blacklisted(registry_vehicle):
                flags.append("blacklist")

            reg_category = self._normalize_registry_category(getattr(registry_vehicle, "categorie", "civil"))
            if reg_category == "military" and plate_type == "civil":
                flags.append("category_mismatch")
            if reg_category == "civil" and plate_type == "military":
                flags.append("category_mismatch")

        if confidence < self.review_threshold or plate_confidence < (self.review_threshold - 0.08):
            flags.append("low_confidence")
        elif confidence < self.allow_threshold:
            flags.append("borderline_confidence")

        dominant_color = self._extract_dominant_color(frame_bgr=frame_bgr, vehicle_bbox=vehicle_bbox)
        visual_consistency = 1.0
        if self.enable_visual_check and normalized_plate:
            visual_consistency = self._compute_visual_consistency(
                normalized_plate=normalized_plate,
                current_color=dominant_color,
            )
            if visual_consistency < self.visual_mismatch_threshold:
                flags.append("visual_mismatch")

        decision, reason, severity, requires_review = self._resolve_decision(flags=flags)
        is_priority = bool(
            decision in {"denied", "review_required"}
            or plate_type == "military"
            or "blacklist" in flags
            or "visual_mismatch" in flags
        )

        security_tag = classifier_security_tag
        if security_tag is None and registry_vehicle is not None:
            if self._normalize_registry_category(getattr(registry_vehicle, "categorie", "civil")) == "military":
                security_tag = "military_vehicle"

        alert_type = None
        alert_message = None
        should_alert = False
        if "blacklist" in flags:
            alert_type = "blacklist"
            alert_message = "Blacklisted or suspended vehicle detected"
            should_alert = True
        elif "visual_mismatch" in flags:
            alert_type = "mismatch"
            alert_message = "Visual mismatch against historical profile"
            should_alert = True
        elif "low_confidence" in flags:
            alert_type = "low_confidence"
            alert_message = "Recognition confidence below secure threshold"
            should_alert = True
        elif "not_in_registry" in flags:
            alert_type = "unknown_plate"
            alert_message = "Plate not found in secured registry"
            should_alert = True
        elif "category_mismatch" in flags:
            alert_type = "mismatch"
            alert_message = "Classified plate type conflicts with registry category"
            should_alert = True

        return VehicleAccessDecision(
            decision=decision,
            reason=reason,
            severity=severity,
            requires_manual_review=requires_review,
            is_priority=is_priority,
            should_alert=should_alert,
            alert_type=alert_type,
            alert_message=alert_message,
            confidence_score=float(max(0.0, min(1.0, confidence))),
            registry_vehicle_id=int(registry_vehicle.id) if registry_vehicle is not None else None,
            registry_matched=registry_matched,
            security_tag=security_tag,
            normalized_plate=normalized_plate,
            dominant_color=dominant_color,
            visual_consistency=float(max(0.0, min(1.0, visual_consistency))),
            flags=flags,
        )

    def persist_access_decision(
        self,
        *,
        decision: VehicleAccessDecision,
        event_id: Optional[int],
        plate_number: Optional[str],
        plate_type: str,
        camera_id: int,
        site_id: Optional[int],
        gate_id: Optional[str],
        direction: str,
        timestamp: datetime,
        snapshot_path: Optional[str],
        vehicle_detected: bool,
        vehicle_type: Optional[str],
        plate_confidence: float,
    ) -> tuple[Optional[int], List[int]]:
        from vms.backend.models import SecurityAlert, VehicleAccessLog

        try:
            resolved_site_id = site_id if site_id is not None else self._resolve_site_id(camera_id=camera_id)
            row = VehicleAccessLog(
                event_id=event_id,
                plate_number=plate_number,
                normalized_plate=decision.normalized_plate,
                plate_type=(plate_type or "unknown"),
                camera_id=int(camera_id),
                site_id=resolved_site_id,
                gate_id=gate_id,
                timestamp=timestamp,
                direction=self._normalize_direction(direction),
                decision=decision.decision,
                confidence_score=decision.confidence_score,
                vehicle_detected=bool(vehicle_detected),
                vehicle_type=vehicle_type,
                plate_confidence=float(max(0.0, min(1.0, plate_confidence))),
                security_tag=decision.security_tag,
                reason=decision.reason,
                snapshot_path=snapshot_path,
                registry_vehicle_id=decision.registry_vehicle_id,
                dominant_color=decision.dominant_color,
                visual_consistency=decision.visual_consistency,
                audit_meta={
                    "flags": decision.flags,
                    "requires_manual_review": decision.requires_manual_review,
                },
            )
            self.db.add(row)
            self.db.flush()

            alert_ids: List[int] = []
            if decision.should_alert and decision.alert_type:
                alert = SecurityAlert(
                    type=decision.alert_type,
                    plate_number=plate_number,
                    normalized_plate=decision.normalized_plate,
                    camera_id=int(camera_id),
                    site_id=resolved_site_id,
                    gate_id=gate_id,
                    timestamp=timestamp,
                    severity_level=self._severity_to_level(decision.severity),
                    resolution_status="open",
                    message=decision.alert_message,
                    event_id=event_id,
                    access_log_id=row.id,
                    snapshot_path=snapshot_path,
                    details={
                        "decision": decision.decision,
                        "reason": decision.reason,
                        "flags": decision.flags,
                        "security_tag": decision.security_tag,
                    },
                )
                self.db.add(alert)
                self.db.flush()
                alert_ids.append(int(alert.id))

            self.db.commit()
            return int(row.id), alert_ids
        except Exception:
            self.db.rollback()
            return None, []

    def list_access_logs(
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
        from vms.backend.models import VehicleAccessLog

        query = self.db.query(VehicleAccessLog)
        cutoff = datetime.utcnow() - timedelta(hours=max(1, int(from_hours)))
        query = query.filter(VehicleAccessLog.timestamp >= cutoff)

        if camera_id is not None:
            query = query.filter(VehicleAccessLog.camera_id == int(camera_id))
        if gate_id:
            query = query.filter(VehicleAccessLog.gate_id == gate_id)
        if decision:
            query = query.filter(VehicleAccessLog.decision == str(decision).lower())
        if direction:
            query = query.filter(VehicleAccessLog.direction == self._normalize_direction(direction))
        if plate_number:
            normalized = self.normalizer.normalize(plate_number)
            compact = normalized.compact_text
            if compact:
                query = query.filter(VehicleAccessLog.normalized_plate.ilike(f"%{compact}%"))
            else:
                query = query.filter(VehicleAccessLog.plate_number.ilike(f"%{plate_number}%"))

        rows = (
            query.order_by(VehicleAccessLog.timestamp.desc())
            .offset(max(0, skip))
            .limit(max(1, limit))
            .all()
        )

        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": row.id,
                    "event_id": row.event_id,
                    "plate_number": row.plate_number,
                    "normalized_plate": row.normalized_plate,
                    "plate_type": row.plate_type,
                    "camera_id": row.camera_id,
                    "site_id": row.site_id,
                    "gate_id": row.gate_id,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                    "direction": row.direction,
                    "decision": row.decision,
                    "confidence_score": float(row.confidence_score or 0.0),
                    "plate_confidence": float(row.plate_confidence or 0.0),
                    "security_tag": row.security_tag,
                    "reason": row.reason,
                    "snapshot_path": to_public_media_path(row.snapshot_path),
                    "registry_vehicle_id": row.registry_vehicle_id,
                    "operator_id": row.operator_id,
                    "operator_note": row.operator_note,
                    "dominant_color": row.dominant_color,
                    "visual_consistency": float(row.visual_consistency or 0.0),
                    "audit_meta": row.audit_meta or {},
                }
            )
        return out

    def list_alerts(
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
        from vms.backend.models import SecurityAlert

        query = self.db.query(SecurityAlert)
        cutoff = datetime.utcnow() - timedelta(hours=max(1, int(from_hours)))
        query = query.filter(SecurityAlert.timestamp >= cutoff)

        if camera_id is not None:
            query = query.filter(SecurityAlert.camera_id == int(camera_id))
        if resolution_status:
            query = query.filter(SecurityAlert.resolution_status == str(resolution_status).lower())
        if severity_level:
            query = query.filter(SecurityAlert.severity_level == str(severity_level).lower())
        if alert_type:
            query = query.filter(SecurityAlert.type == str(alert_type).lower())

        rows = (
            query.order_by(SecurityAlert.timestamp.desc())
            .offset(max(0, skip))
            .limit(max(1, limit))
            .all()
        )

        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": row.id,
                    "type": row.type,
                    "plate_number": row.plate_number,
                    "normalized_plate": row.normalized_plate,
                    "camera_id": row.camera_id,
                    "site_id": row.site_id,
                    "gate_id": row.gate_id,
                    "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                    "severity_level": row.severity_level,
                    "resolution_status": row.resolution_status,
                    "message": row.message,
                    "event_id": row.event_id,
                    "access_log_id": row.access_log_id,
                    "handled_by": row.handled_by,
                    "handled_at": row.handled_at.isoformat() if row.handled_at else None,
                    "snapshot_path": to_public_media_path(row.snapshot_path),
                    "details": row.details or {},
                }
            )
        return out

    def manual_override(
        self,
        *,
        access_log_id: Optional[int],
        event_id: Optional[int],
        operator_id: int,
        operator_username: Optional[str],
        forced_decision: str,
        note: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        from vms.backend.models import SecurityAlert, VehicleAccessLog

        query = self.db.query(VehicleAccessLog)
        if access_log_id is not None:
            query = query.filter(VehicleAccessLog.id == int(access_log_id))
        elif event_id is not None:
            query = query.filter(VehicleAccessLog.event_id == int(event_id))
        else:
            return None

        row = query.order_by(VehicleAccessLog.timestamp.desc()).first()
        if row is None:
            return None

        normalized_forced = str(forced_decision or "").strip().lower()
        if normalized_forced not in {"allowed", "denied"}:
            normalized_forced = "allowed"

        try:
            previous_decision = row.decision
            row.decision = "manual_override"
            row.operator_id = int(operator_id)
            row.operator_note = (note or "").strip()[:500] or None
            meta = dict(row.audit_meta or {})
            meta.update(
                {
                    "override_applied_at": datetime.utcnow().isoformat(),
                    "override_by": operator_username or f"user:{operator_id}",
                    "override_from": previous_decision,
                    "override_to": normalized_forced,
                }
            )
            row.audit_meta = meta

            open_alerts = (
                self.db.query(SecurityAlert)
                .filter(SecurityAlert.access_log_id == row.id)
                .filter(SecurityAlert.resolution_status.in_(["open", "in_review"]))
                .all()
            )
            for alert in open_alerts:
                alert.resolution_status = "resolved"
                alert.handled_by = int(operator_id)
                alert.handled_at = datetime.utcnow()
                details = dict(alert.details or {})
                details["manual_override_to"] = normalized_forced
                details["manual_override_note"] = row.operator_note
                alert.details = details

            self.db.commit()
            self.db.refresh(row)
        except Exception:
            self.db.rollback()
            return None

        return {
            "id": row.id,
            "event_id": row.event_id,
            "site_id": row.site_id,
            "decision": row.decision,
            "operator_id": row.operator_id,
            "operator_note": row.operator_note,
            "audit_meta": row.audit_meta or {},
        }

    def _resolve_site_id(self, *, camera_id: int) -> Optional[int]:
        from vms.backend.models import Camera

        row = self.db.query(Camera.site_id).filter(Camera.id == int(camera_id)).first()
        if not row:
            return None
        return row[0]

    def _resolve_decision(self, *, flags: List[str]) -> tuple[str, str, str, bool]:
        if "blacklist" in flags:
            return "denied", "blacklist_hit", "critical", False
        if "visual_mismatch" in flags:
            return "denied", "visual_mismatch", "critical", False
        if "plate_missing" in flags:
            return "denied", "plate_missing", "high", False
        if "not_in_registry" in flags:
            if self.unknown_policy == "review":
                return "review_required", "not_in_registry", "high", True
            return "denied", "not_in_registry", "high", False
        if "category_mismatch" in flags:
            return "review_required", "category_mismatch", "high", True
        if "low_confidence" in flags:
            return "review_required", "low_confidence", "high", True
        if "borderline_confidence" in flags:
            return "review_required", "borderline_confidence", "medium", True
        return "allowed", "policy_pass", "info", False

    def _find_registry_vehicle(self, *, normalized_plate: Optional[str]):
        if not normalized_plate:
            return None
        from vms.backend.models import VehicleRegistry

        rows = self.db.query(VehicleRegistry).all()
        for row in rows:
            compact = re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", str(row.matricule or "").strip().upper())
            if not compact:
                continue
            if compact == normalized_plate:
                return row

        best_row = None
        best_score = 0
        for row in rows:
            compact = re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", str(row.matricule or "").strip().upper())
            if not compact:
                continue
            if compact in normalized_plate or normalized_plate in compact:
                score = min(len(compact), len(normalized_plate))
                if score > best_score:
                    best_score = score
                    best_row = row
        return best_row if best_score >= 4 else None

    def _is_registry_blacklisted(self, row: Any) -> bool:
        if bool(getattr(row, "is_blacklisted", False)):
            return True
        if bool(getattr(row, "is_flagged", False)):
            return True
        status = str(getattr(row, "statut", "") or "").strip().lower()
        blocked = {"suspendu", "revoked", "revoke", "bloque", "blocked", "hors_service", "maintenance", "inactive"}
        return status in blocked

    def _normalize_registry_category(self, value: Optional[str]) -> str:
        raw = str(value or "civil").strip().lower()
        if raw.startswith("mil"):
            return "military"
        return "civil"

    def _extract_dominant_color(
        self,
        *,
        frame_bgr: Optional[np.ndarray],
        vehicle_bbox: Optional[Tuple[int, int, int, int]],
    ) -> Optional[str]:
        if frame_bgr is None or frame_bgr.size == 0:
            return None

        h, w = frame_bgr.shape[:2]
        if vehicle_bbox is None:
            x1, y1, x2, y2 = 0, 0, w, h
        else:
            x, y, bw, bh = vehicle_bbox
            x1 = max(0, int(x))
            y1 = max(0, int(y))
            x2 = min(w, int(x + bw))
            y2 = min(h, int(y + bh))
        roi = frame_bgr[y1:y2, x1:x2]
        if roi is None or roi.size == 0:
            return None
        sample = roi.reshape(-1, 3).astype(np.float32)
        b, g, r = sample.mean(axis=0).tolist()
        return self._map_rgb_to_color_name(r=r, g=g, b=b)

    def _map_rgb_to_color_name(self, *, r: float, g: float, b: float) -> str:
        brightness = (r + g + b) / 3.0
        spread = max(r, g, b) - min(r, g, b)

        if brightness < 45:
            return "black"
        if brightness > 215 and spread < 18:
            return "white"
        if spread < 22:
            return "gray"
        if r > 145 and g > 120 and b < 120:
            return "yellow"
        if r > g * 1.12 and r > b * 1.12:
            return "red"
        if g > r * 1.10 and g > b * 1.10:
            return "green"
        if b > r * 1.08 and b > g * 1.08:
            return "blue"
        return "other"

    def _compute_visual_consistency(self, *, normalized_plate: str, current_color: Optional[str]) -> float:
        if not current_color:
            return 1.0
        from vms.backend.models import VehicleAccessLog

        cutoff = datetime.utcnow() - timedelta(minutes=self.signal_window_minutes)
        rows = (
            self.db.query(VehicleAccessLog)
            .filter(VehicleAccessLog.normalized_plate == normalized_plate)
            .filter(VehicleAccessLog.timestamp >= cutoff)
            .filter(VehicleAccessLog.dominant_color.isnot(None))
            .order_by(VehicleAccessLog.timestamp.desc())
            .limit(8)
            .all()
        )
        if not rows:
            return 1.0

        matches = 0
        total = 0
        for row in rows:
            prev = str(row.dominant_color or "").strip().lower()
            if not prev:
                continue
            total += 1
            if prev == current_color:
                matches += 1
            elif {prev, current_color}.issubset({"black", "gray"}):
                matches += 1
            elif {prev, current_color}.issubset({"white", "gray"}):
                matches += 1
        if total == 0:
            return 1.0
        return float(matches / total)

    def _normalize_direction(self, direction: Optional[str]) -> str:
        raw = str(direction or "IN").strip().upper()
        if raw in {"IN", "OUT"}:
            return raw
        return "UNKNOWN"

    def _severity_to_level(self, severity: str) -> str:
        raw = str(severity or "medium").strip().lower()
        if raw in {"critical", "high", "medium", "low"}:
            return raw
        if raw == "warning":
            return "high"
        if raw == "info":
            return "low"
        return "medium"
