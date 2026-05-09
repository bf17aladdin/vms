from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from vms.backend.core.audit import write_audit_log
from vms.backend.core.database import get_db
from vms.backend.core.security import require_operator
from vms.backend.services.access_decision_service import AccessDecisionRequest, AccessDecisionService


router = APIRouter(prefix="/api/access-decisions", tags=["Access Decisions"])


class AccessDecisionEvaluatePayload(BaseModel):
    detection_type: Literal["face", "vehicle"]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    camera_id: Optional[int] = Field(default=None, ge=1)
    detected_at: Optional[datetime] = None
    personnel_id: Optional[int] = Field(default=None, ge=1)
    vehicle_registry_id: Optional[int] = Field(default=None, ge=1)
    plate_number: Optional[str] = Field(default=None, max_length=120)
    unknown_detection_id: Optional[int] = Field(default=None, ge=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AccessDecisionCheckOut(BaseModel):
    code: str
    passed: bool
    message: str
    severity: str


class AccessDecisionResponse(BaseModel):
    decision: Literal["allow", "deny", "review", "unknown"]
    reason_code: str
    explanation: str
    detection_type: Literal["face", "vehicle"]
    entity_type: str
    entity_id: Optional[int] = None
    matched: bool
    confidence: float
    unknown_queue_action: Literal["required", "linked", "not_needed"]
    reference_label: Optional[str] = None
    checks: List[AccessDecisionCheckOut]


def _coerce_user_id(current_user: Dict[str, Any]) -> Optional[int]:
    raw = current_user.get("user_id")
    if raw is None:
        return None
    try:
        user_id = int(raw)
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


def _coerce_username(current_user: Dict[str, Any]) -> Optional[str]:
    text = str(current_user.get("sub") or current_user.get("username") or "").strip()
    return text or None


@router.post("/evaluate", response_model=AccessDecisionResponse)
def evaluate_access_decision(
    payload: AccessDecisionEvaluatePayload,
    request: Request,
    current_user: Dict[str, Any] = Depends(require_operator),
    db: Session = Depends(get_db),
):
    service = AccessDecisionService(db)

    try:
        result = service.evaluate(
            AccessDecisionRequest(
                detection_type=payload.detection_type,
                confidence=payload.confidence,
                camera_id=payload.camera_id,
                detected_at=payload.detected_at,
                personnel_id=payload.personnel_id,
                vehicle_registry_id=payload.vehicle_registry_id,
                plate_number=payload.plate_number,
                unknown_detection_id=payload.unknown_detection_id,
                metadata=payload.metadata,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    write_audit_log(
        event_type="access_decision",
        action=f"evaluate_{payload.detection_type}",
        method=request.method,
        path=request.url.path,
        status_code=200,
        user_id=_coerce_user_id(current_user),
        username=_coerce_username(current_user),
        ip_address=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
        request_id=getattr(request.state, "request_id", None),
        details={
            "decision": result.decision,
            "reason_code": result.reason_code,
            "entity_type": result.entity_type,
            "entity_id": result.entity_id,
            "confidence": result.confidence,
            "unknown_queue_action": result.unknown_queue_action,
            "matched": result.matched,
        },
    )

    return AccessDecisionResponse(**result.to_dict())
