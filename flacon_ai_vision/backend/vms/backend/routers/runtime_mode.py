from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from vms.backend.core.security import get_current_user
from vms.backend.routers.runtime_guard import get_manual_inference_guard_status
from vms.backend.services.operation_mode_manager import (
    ProductionRuntimeConfig,
    get_operation_mode_manager,
)

router = APIRouter(prefix="/api/runtime", tags=["runtime-mode"])


class ProductionModeStartRequest(BaseModel):
    camera_ids: Optional[list[int]] = None
    sample_interval_ms: int = Field(default=1000, ge=100, le=20000)
    face_enabled: bool = True
    vehicle_enabled: bool = True
    persist_face: bool = True
    persist_vehicle: bool = True
    face_top_k: int = Field(default=5, ge=1, le=20)
    face_max_faces: int = Field(default=10, ge=1, le=64)
    vehicle_direction: str = Field(default="IN", min_length=1, max_length=16)
    vehicle_gate_id: Optional[str] = Field(default=None, max_length=80)
    zone_id: Optional[int] = None
    enforce_camera_profiles: bool = True
    strict_policy_validation: bool = True
    default_camera_profile: str = Field(default="fixed_medium", min_length=3, max_length=32)
    camera_profile_overrides: Optional[dict[int, str]] = None


@router.get("/mode")
def get_runtime_mode(current_user: dict = Depends(get_current_user)):
    manager = get_operation_mode_manager()
    return {
        "success": True,
        **manager.status(),
    }


@router.get("/mode/manual-inference-guard")
def get_manual_inference_guard(current_user: dict = Depends(get_current_user)):
    return {
        "success": True,
        **get_manual_inference_guard_status(),
    }


@router.post("/mode/development")
def set_development_mode(current_user: dict = Depends(get_current_user)):
    manager = get_operation_mode_manager()
    payload = manager.set_development_mode()
    return {
        "success": True,
        "message": "Switched to development mode (enrollment/training).",
        **payload,
    }


@router.post("/mode/production/start")
def start_production_mode(
    body: ProductionModeStartRequest,
    current_user: dict = Depends(get_current_user),
):
    manager = get_operation_mode_manager()

    try:
        cfg = ProductionRuntimeConfig(
            camera_ids=body.camera_ids,
            sample_interval_ms=int(body.sample_interval_ms),
            face_enabled=bool(body.face_enabled),
            vehicle_enabled=bool(body.vehicle_enabled),
            persist_face=bool(body.persist_face),
            persist_vehicle=bool(body.persist_vehicle),
            face_top_k=int(body.face_top_k),
            face_max_faces=int(body.face_max_faces),
            vehicle_direction=str(body.vehicle_direction).upper(),
            vehicle_gate_id=body.vehicle_gate_id,
            zone_id=body.zone_id,
            enforce_camera_profiles=bool(body.enforce_camera_profiles),
            strict_policy_validation=bool(body.strict_policy_validation),
            default_camera_profile=str(body.default_camera_profile or "fixed_medium").strip().lower(),
            camera_profile_overrides=body.camera_profile_overrides,
        )
        payload = manager.start_production_mode(cfg)
        return {
            "success": True,
            "message": "Production mode started: live multi-camera AI runtime is active.",
            **payload,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start production mode: {exc}")


@router.post("/mode/production/stop")
def stop_production_mode(current_user: dict = Depends(get_current_user)):
    manager = get_operation_mode_manager()
    payload = manager.stop_production_mode()
    return {
        "success": True,
        "message": "Production mode stopped.",
        **payload,
    }


@router.post("/mode/production/camera/{camera_id}/stop")
def stop_single_production_camera(
    camera_id: int,
    current_user: dict = Depends(get_current_user),
):
    manager = get_operation_mode_manager()
    try:
        payload = manager.stop_production_camera(int(camera_id))
        return {
            "success": True,
            "message": f"Camera #{camera_id} stopped in production runtime.",
            **payload,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop camera #{camera_id}: {exc}")


@router.get("/mode/production/cameras")
def get_production_cameras(current_user: dict = Depends(get_current_user)):
    manager = get_operation_mode_manager()
    status = manager.status()
    runtime = status.get("production_runtime") or {}
    return {
        "success": True,
        "mode": status.get("mode"),
        "running": bool(runtime.get("running", False)),
        "totals": runtime.get("totals") or {},
        "cameras": runtime.get("cameras") or [],
    }
