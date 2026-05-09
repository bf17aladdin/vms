from __future__ import annotations

from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator

from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_user
from vms.backend.models import Tenant, SetupConfig
from vms.backend.services.setup_config_service import get_setup_config_service

router = APIRouter(prefix="/api/setup", tags=["Setup"])

UsageType = Literal["maison", "magasin", "entreprise", "parking", "securite_avancee"]
ProjectType = Literal["home", "business", "soc"]
OperationMode = Literal["family", "enterprise"]
DetectionType = Literal["person", "vehicle"]
AlertType = Literal["motion", "person", "vehicle", "face", "alarm", "system"]
AlertChannel = Literal["ui", "email", "sms", "webhook", "siren"]
PersonnelFieldKey = Literal[
    "last_name",
    "first_name",
    "id_number",
    "reference_id",
    "role",
    "category",
    "unit",
    "email",
    "phone",
]


class PersonnelCustomField(BaseModel):
    key: str = Field(..., min_length=1, max_length=50)
    label: str = Field(..., min_length=1, max_length=100)
    type: Literal["text", "number", "date", "select", "boolean"] = "text"
    required: bool = False
    options: List[str] | None = None

    @field_validator("key", "label")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return str(value).strip()


class SetupConfigPayload(BaseModel):
    usage_type: UsageType
    project_type: ProjectType | None = None
    operation_mode: OperationMode | None = None
    camera_limit: int = Field(1, ge=1, le=512)
    detection_types: List[DetectionType] = Field(default_factory=list, min_items=1)
    alert_types: List[AlertType] | None = None
    alert_channels: List[AlertChannel] = Field(default_factory=list)
    ui_preset: str
    connect_email: str | None = None
    personnel_custom_fields: List[PersonnelCustomField] | None = None
    personnel_visible_fields: List[PersonnelFieldKey] | None = None

    @field_validator("personnel_visible_fields")
    @classmethod
    def normalize_visible_fields(cls, value: List[PersonnelFieldKey] | None) -> List[str] | None:
        if value is None:
            return None
        cleaned: List[str] = []
        for item in value:
            key = str(item or "").strip()
            if not key:
                continue
            if key not in cleaned:
                cleaned.append(key)
        return cleaned


@router.get("/config", summary="Get setup configuration")
async def get_setup_config(current_user=Depends(get_current_user)):
    service = get_setup_config_service()
    config = service.get_config()
    return {"status": "success", "configured": bool(config.get("configured")), "config": config}


@router.get("/presets", summary="Get setup presets")
async def get_setup_presets(current_user=Depends(get_current_user)):
    service = get_setup_config_service()
    return {"status": "success", "presets": service.get_presets()}


@router.post("/config", summary="Save setup configuration")
async def save_setup_config(
    payload: SetupConfigPayload,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.detection_types:
        raise HTTPException(status_code=400, detail="detection_types must not be empty")
    if payload.alert_types is not None and not payload.alert_types:
        raise HTTPException(status_code=400, detail="alert_types must not be empty")

    service = get_setup_config_service()
    updated = service.update_config(payload.model_dump())
    tenant_id = current_user.get("tenant_id")
    project_type = updated.get("project_type")
    if tenant_id and project_type:
        tenant = db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
        if tenant:
            tenant.project_type = str(project_type)
            db.add(tenant)

    user_id = current_user.get("user_id")
    if user_id:
        setup_row = db.query(SetupConfig).filter(SetupConfig.user_id == int(user_id)).first()
        if not setup_row:
            setup_row = SetupConfig(user_id=int(user_id))
            db.add(setup_row)
        existing = setup_row.license_plate_config
        if isinstance(existing, dict):
            merged = dict(existing)
        else:
            merged = {}
        merged["setup_summary"] = {
            "usage_type": updated.get("usage_type"),
            "project_type": updated.get("project_type"),
            "operation_mode": updated.get("operation_mode"),
            "ui_preset": updated.get("ui_preset"),
            "camera_limit": updated.get("camera_limit"),
            "detection_types": list(updated.get("detection_types") or []),
            "alert_channels": list(updated.get("alert_channels") or []),
        }
        setup_row.license_plate_config = merged

    db.commit()
    return {"status": "success", "configured": True, "config": updated}
