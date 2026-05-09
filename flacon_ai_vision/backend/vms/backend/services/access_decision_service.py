from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from vms.backend.models import Personnel, VehicleRegistry


DecisionType = str
DetectionType = str


@dataclass(frozen=True)
class PolicyCheck:
    code: str
    passed: bool
    message: str
    severity: str = "info"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "passed": bool(self.passed),
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class AccessDecisionRequest:
    detection_type: DetectionType
    confidence: float = 0.0
    camera_id: Optional[int] = None
    detected_at: Optional[datetime] = None
    personnel_id: Optional[int] = None
    vehicle_registry_id: Optional[int] = None
    plate_number: Optional[str] = None
    unknown_detection_id: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccessDecisionResult:
    decision: DecisionType
    reason_code: str
    explanation: str
    detection_type: DetectionType
    entity_type: str
    entity_id: Optional[int]
    matched: bool
    confidence: float
    unknown_queue_action: str
    reference_label: Optional[str]
    checks: List[PolicyCheck] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "reason_code": self.reason_code,
            "explanation": self.explanation,
            "detection_type": self.detection_type,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "matched": bool(self.matched),
            "confidence": float(self.confidence),
            "unknown_queue_action": self.unknown_queue_action,
            "reference_label": self.reference_label,
            "checks": [check.to_dict() for check in self.checks],
        }


class AccessDecisionService:
    """
    Business-rule decision engine.

    This service receives normalized AI outputs and applies business rules.
    It intentionally does not run face or vehicle inference itself.
    """

    def __init__(self, db: Session):
        self.db = db

    def evaluate(self, request: AccessDecisionRequest) -> AccessDecisionResult:
        detection_type = str(request.detection_type or "").strip().lower()
        if detection_type == "face":
            return self._evaluate_face(request)
        if detection_type == "vehicle":
            return self._evaluate_vehicle(request)
        raise ValueError(f"Unsupported detection_type '{request.detection_type}'")

    def _evaluate_face(self, request: AccessDecisionRequest) -> AccessDecisionResult:
        if request.personnel_id is None:
            checks = [
                PolicyCheck(
                    code="identity_resolved",
                    passed=False,
                    message="Aucun personnel reconnu par l'IA.",
                    severity="warning",
                )
            ]
            return self._decision(
                decision="unknown",
                reason_code="personnel_unrecognized",
                explanation=(
                    "Aucun personnel reconnu. La detection doit rester dans la unknown queue "
                    "avant toute decision manuelle ou incident."
                ),
                detection_type="face",
                entity_type="unknown",
                entity_id=None,
                matched=False,
                confidence=request.confidence,
                unknown_queue_action=self._unknown_queue_action(request, required=True),
                reference_label=None,
                checks=checks,
            )

        personnel = self.db.query(Personnel).filter(Personnel.id == int(request.personnel_id)).first()
        if personnel is None:
            checks = [
                PolicyCheck(
                    code="identity_resolved",
                    passed=False,
                    message=f"Le personnel #{int(request.personnel_id)} n'existe pas dans l'annuaire.",
                    severity="warning",
                )
            ]
            return self._decision(
                decision="unknown",
                reason_code="personnel_missing_in_directory",
                explanation=(
                    "Le personnel reconnu n'existe pas dans l'annuaire. La detection doit etre "
                    "renvoyee dans la unknown queue au lieu d'etre acceptee aveuglement."
                ),
                detection_type="face",
                entity_type="unknown",
                entity_id=None,
                matched=False,
                confidence=request.confidence,
                unknown_queue_action=self._unknown_queue_action(request, required=True),
                reference_label=None,
                checks=checks,
            )

        checks = [
            PolicyCheck(
                code="identity_resolved",
                passed=True,
                message=f"Personnel reconnu: {self._personnel_label(personnel)}.",
            )
        ]

        is_active = bool(personnel.is_active)
        checks.append(
            PolicyCheck(
                code="personnel_active",
                passed=is_active,
                message=(
                    "Le personnel est actif dans l'annuaire."
                    if is_active
                    else "Le personnel est inactif dans l'annuaire."
                ),
                severity="critical" if not is_active else "info",
            )
        )

        not_blacklisted = not bool(personnel.is_blacklisted)
        checks.append(
            PolicyCheck(
                code="personnel_not_blacklisted",
                passed=not_blacklisted,
                message=(
                    "Le personnel n'est pas blackliste."
                    if not_blacklisted
                    else "Le personnel est blackliste."
                ),
                severity="critical" if not not_blacklisted else "info",
            )
        )

        camera_allowed = self._is_camera_allowed(
            allowed_camera_ids=getattr(personnel, "allowed_camera_ids", None),
            camera_id=request.camera_id,
        )
        checks.append(
            PolicyCheck(
                code="camera_authorized",
                passed=camera_allowed,
                message=(
                    "La camera courante est autorisee pour ce personnel."
                    if camera_allowed
                    else "La camera courante n'est pas autorisee pour ce personnel."
                ),
                severity="warning" if not camera_allowed else "info",
            )
        )

        schedule_allowed = self._is_within_schedule(
            detected_at=request.detected_at,
            start=getattr(personnel, "authorized_hours_start", None),
            end=getattr(personnel, "authorized_hours_end", None),
        )
        checks.append(
            PolicyCheck(
                code="within_authorized_schedule",
                passed=schedule_allowed,
                message=(
                    "La detection est dans la plage horaire autorisee."
                    if schedule_allowed
                    else "La detection est hors plage horaire autorisee."
                ),
                severity="warning" if not schedule_allowed else "info",
            )
        )

        failed_codes = {check.code for check in checks if not check.passed}
        if "personnel_not_blacklisted" in failed_codes:
            return self._decision(
                decision="deny",
                reason_code="personnel_blacklisted",
                explanation=(
                    f"Acces refuse pour {self._personnel_label(personnel)}: le personnel est "
                    "blackliste dans l'annuaire."
                ),
                detection_type="face",
                entity_type="personnel",
                entity_id=int(personnel.id),
                matched=True,
                confidence=request.confidence,
                unknown_queue_action="not_needed",
                reference_label=self._personnel_label(personnel),
                checks=checks,
            )

        if "personnel_active" in failed_codes:
            return self._decision(
                decision="deny",
                reason_code="personnel_inactive",
                explanation=(
                    f"Acces refuse pour {self._personnel_label(personnel)}: le profil est inactif "
                    "dans l'annuaire."
                ),
                detection_type="face",
                entity_type="personnel",
                entity_id=int(personnel.id),
                matched=True,
                confidence=request.confidence,
                unknown_queue_action="not_needed",
                reference_label=self._personnel_label(personnel),
                checks=checks,
            )

        if "camera_authorized" in failed_codes:
            return self._decision(
                decision="deny",
                reason_code="camera_not_authorized",
                explanation=(
                    f"Acces refuse pour {self._personnel_label(personnel)}: la camera "
                    f"{request.camera_id or '-'} ne fait pas partie des points autorises."
                ),
                detection_type="face",
                entity_type="personnel",
                entity_id=int(personnel.id),
                matched=True,
                confidence=request.confidence,
                unknown_queue_action="not_needed",
                reference_label=self._personnel_label(personnel),
                checks=checks,
            )

        if "within_authorized_schedule" in failed_codes:
            return self._decision(
                decision="deny",
                reason_code="outside_authorized_hours",
                explanation=(
                    f"Acces refuse pour {self._personnel_label(personnel)}: la detection est en dehors "
                    "de la plage horaire autorisee."
                ),
                detection_type="face",
                entity_type="personnel",
                entity_id=int(personnel.id),
                matched=True,
                confidence=request.confidence,
                unknown_queue_action="not_needed",
                reference_label=self._personnel_label(personnel),
                checks=checks,
            )

        return self._decision(
            decision="allow",
            reason_code="personnel_authorized",
            explanation=(
                f"Acces autorise pour {self._personnel_label(personnel)}: profil actif, non blackliste, "
                "camera conforme et horaire valide."
            ),
            detection_type="face",
            entity_type="personnel",
            entity_id=int(personnel.id),
            matched=True,
            confidence=request.confidence,
            unknown_queue_action="not_needed",
            reference_label=self._personnel_label(personnel),
            checks=checks,
        )

    def _evaluate_vehicle(self, request: AccessDecisionRequest) -> AccessDecisionResult:
        normalized_plate = self._normalize_plate(request.plate_number)
        checks: List[PolicyCheck] = []

        has_plate_signal = bool(normalized_plate) or request.vehicle_registry_id is not None
        checks.append(
            PolicyCheck(
                code="plate_or_registry_reference_present",
                passed=has_plate_signal,
                message=(
                    "Une plaque ou un identifiant de registre est disponible."
                    if has_plate_signal
                    else "Aucune plaque ni reference de registre n'est disponible."
                ),
                severity="warning" if not has_plate_signal else "info",
            )
        )

        if not has_plate_signal:
            return self._decision(
                decision="unknown",
                reason_code="vehicle_unidentified",
                explanation=(
                    "Le vehicule n'est pas suffisamment identifie. Il doit etre envoye dans la unknown queue "
                    "avant toute decision d'acces."
                ),
                detection_type="vehicle",
                entity_type="unknown",
                entity_id=None,
                matched=False,
                confidence=request.confidence,
                unknown_queue_action=self._unknown_queue_action(request, required=True),
                reference_label=None,
                checks=checks,
            )

        vehicle = self._resolve_vehicle(
            vehicle_registry_id=request.vehicle_registry_id,
            normalized_plate=normalized_plate,
        )

        if vehicle is None:
            checks.append(
                PolicyCheck(
                    code="vehicle_in_registry",
                    passed=False,
                    message="Aucun vehicule correspondant n'a ete trouve dans le registre.",
                    severity="critical",
                )
            )
            return self._decision(
                decision="deny",
                reason_code="vehicle_not_in_registry",
                explanation=(
                    f"Acces refuse pour le vehicule {request.plate_number or '(sans plaque lisible)'}: "
                    "aucune correspondance dans le registre. La detection doit aussi etre envoyee "
                    "dans la unknown queue."
                ),
                detection_type="vehicle",
                entity_type="unknown",
                entity_id=None,
                matched=False,
                confidence=request.confidence,
                unknown_queue_action=self._unknown_queue_action(request, required=True),
                reference_label=request.plate_number,
                checks=checks,
            )

        checks.append(
            PolicyCheck(
                code="vehicle_in_registry",
                passed=True,
                message=f"Vehicule reconnu dans le registre: {self._vehicle_label(vehicle)}.",
            )
        )

        vehicle_active = str(vehicle.statut or "").strip().lower() == "actif"
        checks.append(
            PolicyCheck(
                code="vehicle_active",
                passed=vehicle_active,
                message=(
                    "Le vehicule est actif dans le registre."
                    if vehicle_active
                    else f"Le vehicule est en statut '{vehicle.statut}'."
                ),
                severity="critical" if not vehicle_active else "info",
            )
        )

        vehicle_not_blacklisted = not bool(vehicle.is_blacklisted)
        checks.append(
            PolicyCheck(
                code="vehicle_not_blacklisted",
                passed=vehicle_not_blacklisted,
                message=(
                    "Le vehicule n'est pas blackliste."
                    if vehicle_not_blacklisted
                    else "Le vehicule est blackliste."
                ),
                severity="critical" if not vehicle_not_blacklisted else "info",
            )
        )

        vehicle_not_flagged = not bool(vehicle.is_flagged)
        checks.append(
            PolicyCheck(
                code="vehicle_not_flagged",
                passed=vehicle_not_flagged,
                message=(
                    "Le vehicule n'est pas signale."
                    if vehicle_not_flagged
                    else "Le vehicule est signale pour verification manuelle."
                ),
                severity="warning" if not vehicle_not_flagged else "info",
            )
        )

        failed_codes = {check.code for check in checks if not check.passed}
        if "vehicle_not_blacklisted" in failed_codes:
            return self._decision(
                decision="deny",
                reason_code="vehicle_blacklisted",
                explanation=(
                    f"Acces refuse pour {self._vehicle_label(vehicle)}: le vehicule est blackliste."
                ),
                detection_type="vehicle",
                entity_type="vehicle_registry",
                entity_id=int(vehicle.id),
                matched=True,
                confidence=request.confidence,
                unknown_queue_action="not_needed",
                reference_label=self._vehicle_label(vehicle),
                checks=checks,
            )

        if "vehicle_active" in failed_codes:
            return self._decision(
                decision="deny",
                reason_code="vehicle_inactive",
                explanation=(
                    f"Acces refuse pour {self._vehicle_label(vehicle)}: le statut '{vehicle.statut}' "
                    "n'autorise pas le passage."
                ),
                detection_type="vehicle",
                entity_type="vehicle_registry",
                entity_id=int(vehicle.id),
                matched=True,
                confidence=request.confidence,
                unknown_queue_action="not_needed",
                reference_label=self._vehicle_label(vehicle),
                checks=checks,
            )

        if "vehicle_not_flagged" in failed_codes:
            return self._decision(
                decision="review",
                reason_code="vehicle_flagged_for_review",
                explanation=(
                    f"Verification manuelle requise pour {self._vehicle_label(vehicle)}: le vehicule est "
                    "signale dans le registre."
                ),
                detection_type="vehicle",
                entity_type="vehicle_registry",
                entity_id=int(vehicle.id),
                matched=True,
                confidence=request.confidence,
                unknown_queue_action="not_needed",
                reference_label=self._vehicle_label(vehicle),
                checks=checks,
            )

        return self._decision(
            decision="allow",
            reason_code="vehicle_authorized",
            explanation=(
                f"Acces autorise pour {self._vehicle_label(vehicle)}: vehicule present dans le registre, "
                "actif et non blackliste."
            ),
            detection_type="vehicle",
            entity_type="vehicle_registry",
            entity_id=int(vehicle.id),
            matched=True,
            confidence=request.confidence,
            unknown_queue_action="not_needed",
            reference_label=self._vehicle_label(vehicle),
            checks=checks,
        )

    def _decision(
        self,
        *,
        decision: DecisionType,
        reason_code: str,
        explanation: str,
        detection_type: DetectionType,
        entity_type: str,
        entity_id: Optional[int],
        matched: bool,
        confidence: float,
        unknown_queue_action: str,
        reference_label: Optional[str],
        checks: List[PolicyCheck],
    ) -> AccessDecisionResult:
        return AccessDecisionResult(
            decision=str(decision),
            reason_code=str(reason_code),
            explanation=str(explanation).strip(),
            detection_type=str(detection_type),
            entity_type=str(entity_type),
            entity_id=entity_id,
            matched=bool(matched),
            confidence=float(max(0.0, min(1.0, confidence))),
            unknown_queue_action=str(unknown_queue_action),
            reference_label=str(reference_label).strip() if reference_label else None,
            checks=checks,
        )

    def _unknown_queue_action(self, request: AccessDecisionRequest, *, required: bool) -> str:
        if not required:
            return "not_needed"
        if request.unknown_detection_id is not None:
            return "linked"
        return "required"

    def _resolve_vehicle(
        self,
        *,
        vehicle_registry_id: Optional[int],
        normalized_plate: Optional[str],
    ) -> Optional[VehicleRegistry]:
        if vehicle_registry_id is not None:
            return (
                self.db.query(VehicleRegistry)
                .filter(VehicleRegistry.id == int(vehicle_registry_id))
                .first()
            )

        if not normalized_plate:
            return None

        rows = self.db.query(VehicleRegistry).all()
        for row in rows:
            if self._normalize_plate(row.matricule) == normalized_plate:
                return row
        return None

    def _personnel_label(self, personnel: Personnel) -> str:
        full_name = str(personnel.full_name or "").strip()
        if full_name:
            return full_name
        return " ".join(
            part for part in [str(personnel.prenom or "").strip(), str(personnel.nom or "").strip()] if part
        ) or f"Personnel #{int(personnel.id)}"

    def _vehicle_label(self, vehicle: VehicleRegistry) -> str:
        plate = str(vehicle.matricule or "").strip() or f"Vehicule #{int(vehicle.id)}"
        brand = " ".join(
            part for part in [str(vehicle.marque or "").strip(), str(vehicle.modele or "").strip()] if part
        )
        return f"{plate}{f' ({brand})' if brand else ''}"

    def _is_camera_allowed(self, *, allowed_camera_ids: Any, camera_id: Optional[int]) -> bool:
        if camera_id is None:
            return True
        if not allowed_camera_ids:
            return True
        if not isinstance(allowed_camera_ids, (list, tuple, set)):
            return True

        camera_tokens = {str(item).strip() for item in allowed_camera_ids if str(item).strip()}
        return str(int(camera_id)) in camera_tokens

    def _is_within_schedule(
        self,
        *,
        detected_at: Optional[datetime],
        start: Optional[str],
        end: Optional[str],
    ) -> bool:
        if not start or not end:
            return True

        try:
            start_time = self._parse_clock(start)
            end_time = self._parse_clock(end)
        except ValueError:
            return True

        current_dt = detected_at or datetime.utcnow()
        current_time = current_dt.time().replace(tzinfo=None)

        if start_time <= end_time:
            return start_time <= current_time <= end_time
        return current_time >= start_time or current_time <= end_time

    def _parse_clock(self, value: str) -> time:
        raw = str(value or "").strip()
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid time '{value}'")
        hour = int(parts[0])
        minute = int(parts[1])
        return time(hour=hour, minute=minute)

    def _normalize_plate(self, value: Optional[str]) -> Optional[str]:
        raw = str(value or "").strip().upper()
        if not raw:
            return None
        compact = re.sub(r"[^A-Z0-9]", "", raw)
        return compact or None
