# vms/backend/routers/setup.py - API endpoints for application setup and mode selection

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
import logging
from pydantic import BaseModel

from ..core.database import get_db
from ..core.security import get_current_user
from ..models import User, SetupConfig, FamilyMember, Employee, Vehicle as UserVehicle
from ..core.config import settings
from ..services.setup_config_service import get_setup_config_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/setup",
    tags=["setup"]
)

class SetupModePayload(BaseModel):
    mode: Optional[str] = None
    application_mode: Optional[str] = None
    operation_mode: Optional[str] = None


class SetupCountryPayload(BaseModel):
    country_code: Optional[str] = None
    region_code: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    license_plate_format: Optional[str] = None


@router.get("/status", summary="Get setup status")
async def get_setup_status(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Get the current setup status for the authenticated user"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    setup_config = db.query(SetupConfig).filter(SetupConfig.user_id == user.id).first()
    runtime_config = get_setup_config_service().get_config()
    configured_flag = bool(runtime_config.get("configured") or user.setup_completed)

    license_plate_format = None
    if setup_config and isinstance(setup_config.license_plate_config, dict):
        license_plate_format = (
            setup_config.license_plate_config.get("selected_format")
            or setup_config.license_plate_config.get("format")
        )
    if license_plate_format:
        runtime_config = {**runtime_config, "license_plate_format": license_plate_format}
    runtime_config = {
        **runtime_config,
        "country_code": user.country_code,
        "timezone": user.timezone,
        "application_mode": user.application_mode,
    }

    # Count entities based on mode
    family_count = 0
    employee_count = 0
    vehicle_count = 0

    if user.application_mode == "home":
        family_count = db.query(FamilyMember).filter(FamilyMember.user_id == user.id).count()
    elif user.application_mode == "company":
        employee_count = db.query(Employee).filter(Employee.user_id == user.id).count()

    vehicle_count = db.query(UserVehicle).filter(UserVehicle.owner_id == user.id).count()

    return {
        "configured": configured_flag,
        "config": runtime_config,
        "setup_completed": user.setup_completed,
        "application_mode": user.application_mode,
        "country_code": user.country_code,
        "timezone": user.timezone,
        "has_setup_config": setup_config is not None,
        "entity_counts": {
            "family_members": family_count,
            "employees": employee_count,
            "vehicles": vehicle_count
        },
        "next_steps": _get_next_steps(user, setup_config)
    }


@router.post("/mode", summary="Select application mode")
async def select_application_mode(
    payload: Optional[SetupModePayload] = Body(default=None),
    mode: Optional[str] = Query(None, description="Application mode: 'home' or 'company'"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Select the application mode (home or company)"""
    raw_mode = None
    if payload:
        raw_mode = payload.application_mode or payload.mode or payload.operation_mode
    if not raw_mode:
        raw_mode = mode
    if not raw_mode:
        raise HTTPException(status_code=400, detail="Mode is required")

    normalized = str(raw_mode).strip().lower()
    if normalized in ["family", "home"]:
        normalized = "home"
    elif normalized in ["enterprise", "company", "business"]:
        normalized = "company"

    if normalized not in ["home", "company"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Must be 'home' or 'company'")

    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update user mode
    user.application_mode = normalized
    db.commit()

    logger.info(f"User {user.id} selected mode: {normalized}")

    return {
        "success": True,
        "application_mode": normalized,
        "message": f"Application mode set to {normalized}"
    }


@router.post("/country", summary="Set country and location")
async def set_country_location(
    payload: Optional[SetupCountryPayload] = Body(default=None),
    country_code: Optional[str] = Query(None, description="ISO 3166-1 alpha-3 country code"),
    region_code: Optional[str] = Query(None, description="Region/state code"),
    city: Optional[str] = Query(None, description="City name"),
    latitude: Optional[float] = Query(None, description="GPS latitude"),
    longitude: Optional[float] = Query(None, description="GPS longitude"),
    timezone: Optional[str] = Query(None, description="Timezone identifier"),
    license_plate_format: Optional[str] = Query(None, description="License plate format pattern"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Set country and location for license plate auto-detection"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    data = payload.model_dump(exclude_none=True) if payload else {}
    resolved_country = data.get("country_code") or country_code
    resolved_region = data.get("region_code") or region_code
    resolved_city = data.get("city") or city
    resolved_latitude = data.get("latitude") if "latitude" in data else latitude
    resolved_longitude = data.get("longitude") if "longitude" in data else longitude
    resolved_timezone = data.get("timezone") or timezone
    resolved_plate_format = data.get("license_plate_format") or license_plate_format

    # Validate country code (basic check)
    if not resolved_country or len(resolved_country) != 3 or not resolved_country.isalpha():
        raise HTTPException(status_code=400, detail="Invalid country code format (must be 3 letters)")

    # Update user
    user.country_code = resolved_country.upper()
    if resolved_timezone:
        user.timezone = resolved_timezone

    # Create or update setup config
    setup_config = db.query(SetupConfig).filter(SetupConfig.user_id == user.id).first()
    if not setup_config:
        setup_config = SetupConfig(user_id=user.id)

    setup_config.country_code = resolved_country.upper()
    setup_config.region_code = resolved_region
    setup_config.city = resolved_city
    setup_config.latitude = resolved_latitude
    setup_config.longitude = resolved_longitude
    setup_config.manually_set = True
    setup_config.detected_at = None  # Clear auto-detection timestamp

    if resolved_plate_format:
        existing = setup_config.license_plate_config
        if isinstance(existing, dict):
            updated_config = dict(existing)
        else:
            updated_config = {}
        updated_config["selected_format"] = resolved_plate_format
        setup_config.license_plate_config = updated_config

    if not setup_config.id:
        db.add(setup_config)

    db.commit()

    logger.info(f"User {user.id} set country: {resolved_country}")

    return {
        "success": True,
        "country_code": resolved_country.upper(),
        "region_code": resolved_region,
        "city": resolved_city,
        "timezone": resolved_timezone,
        "license_plate_format": resolved_plate_format,
        "coordinates": {"lat": resolved_latitude, "lng": resolved_longitude}
        if resolved_latitude and resolved_longitude
        else None
    }


@router.get("/license-plates/formats", summary="Get license plate formats")
async def get_license_plate_formats(
    country_code: Optional[str] = Query(None, description="ISO country code to get formats for"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get license plate format information for a country"""
    # Use provided country_code or user's configured country
    target_country = country_code
    if not target_country:
        user = db.query(User).filter(User.id == current_user["user_id"]).first()
        if user:
            target_country = user.country_code

    if not target_country:
        raise HTTPException(status_code=400, detail="No country specified and user has no country configured")

    # For now, return basic format info (this would be expanded with real data)
    formats = _get_license_plate_formats(target_country.upper())

    return {
        "country_code": target_country.upper(),
        "formats": formats,
        "examples": _get_format_examples(target_country.upper())
    }


@router.post("/complete", summary="Mark setup as complete")
async def complete_setup(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Mark the setup process as complete"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate that required setup is complete
    if not user.application_mode:
        raise HTTPException(status_code=400, detail="Application mode must be selected")

    if not user.country_code:
        raise HTTPException(status_code=400, detail="Country must be configured")

    user.setup_completed = True
    db.commit()

    logger.info(f"User {user.id} completed setup")

    return {
        "success": True,
        "setup_completed": True,
        "application_mode": user.application_mode,
        "message": "Setup completed successfully"
    }


def _get_next_steps(user: User, setup_config: Optional[SetupConfig]) -> List[str]:
    """Determine the next steps for setup completion"""
    steps = []

    if not user.application_mode:
        steps.append("select_application_mode")

    if not user.country_code:
        steps.append("configure_country")

    if user.application_mode and user.country_code and not user.setup_completed:
        steps.append("complete_setup")

    return steps


def _get_license_plate_formats(country_code: str) -> List[Dict]:
    """Get license plate format patterns for a country (simplified example)"""
    # This would be replaced with a real database/API of license plate formats
    formats = {
        "USA": [
            {"pattern": "AAA-1234", "description": "Standard US format"},
            {"pattern": "123-ABC", "description": "Alternative US format"}
        ],
        "FRA": [
            {"pattern": "AB-123-CD", "description": "French format"},
            {"pattern": "1234-AB-56", "description": "French format"}
        ],
        "DEU": [
            {"pattern": "ABC-DE-1234", "description": "German format"}
        ],
        "GBR": [
            {"pattern": "AB12-CDE", "description": "UK format"}
        ]
    }

    return formats.get(country_code, [{"pattern": "UNKNOWN", "description": "Format not configured"}])


def _get_format_examples(country_code: str) -> List[str]:
    """Get example license plates for a country"""
    examples = {
        "USA": ["ABC-1234", "NY-123-AB", "CA-XYZ-789"],
        "FRA": ["AB-123-CD", "AA-001-BB"],
        "DEU": ["ABC-DE-1234", "B-XY-5678"],
        "GBR": ["AB12-CDE", "LK34-MNO"]
    }

    return examples.get(country_code, ["UNKNOWN-FORMAT"])
