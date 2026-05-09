from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vms.backend.core.security import require_operator, require_viewer
from vms.backend.services.rule_engine_service import get_rule_engine_service

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RulePatchPayload(BaseModel):
    enabled: Optional[bool] = None
    conditions: Optional[Dict[str, Any]] = None
    action: Optional[Dict[str, Any]] = None


@router.get("", summary="List rule engine rules")
def list_rules(current_user=Depends(require_viewer)):
    service = get_rule_engine_service()
    tenant_id = current_user.get("tenant_id")
    return {"status": "success", "rules": service.get_rules(tenant_id=tenant_id)}


@router.patch("/{rule_id}", summary="Update rule engine rule")
def update_rule(
    rule_id: str,
    payload: RulePatchPayload,
    current_user=Depends(require_operator),
):
    service = get_rule_engine_service()
    tenant_id = current_user.get("tenant_id")
    try:
        rule = service.update_rule(
            rule_id,
            payload.model_dump(exclude_unset=True),
            tenant_id=tenant_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Rule not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "rule": rule}
