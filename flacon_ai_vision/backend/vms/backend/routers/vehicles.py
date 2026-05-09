# vms/backend/routers/vehicles.py - API endpoints for vehicle management

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
import logging

from ..core.database import get_db
from ..core.security import get_current_user
from ..models import User, Vehicle as UserVehicle

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/vehicles",
    tags=["vehicles"]
)


@router.get("", summary="Get vehicles")
async def get_vehicles(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all vehicles for the current user"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    vehicles = db.query(UserVehicle).filter(UserVehicle.owner_id == user.id).all()

    return {
        "vehicles": [
            {
                "id": vehicle.id,
                "license_plate": vehicle.license_plate,
                "make": vehicle.make,
                "model": vehicle.model,
                "year": vehicle.year,
                "color": vehicle.color,
                "vehicle_type": vehicle.vehicle_type,
                "category": vehicle.category,
                "is_active": vehicle.is_active,
                "is_authorized": vehicle.is_authorized,
                "is_blacklisted": vehicle.is_blacklisted,
                "blacklist_reason": vehicle.blacklist_reason,
                "registration_date": vehicle.registration_date.isoformat() if vehicle.registration_date else None,
                "notes": vehicle.notes,
                "created_at": vehicle.created_at.isoformat(),
                "updated_at": vehicle.updated_at.isoformat()
            }
            for vehicle in vehicles
        ]
    }


@router.post("", summary="Add vehicle")
async def add_vehicle(
    license_plate: str = Query(..., description="License plate number"),
    make: Optional[str] = Query(None, description="Vehicle make"),
    model: Optional[str] = Query(None, description="Vehicle model"),
    year: Optional[int] = Query(None, description="Vehicle year"),
    color: Optional[str] = Query(None, description="Vehicle color"),
    vehicle_type: str = Query(..., description="Vehicle type: personal/company/employee/visitor"),
    category: str = Query("car", description="Vehicle category: car/truck/motorcycle/van"),
    is_authorized: bool = Query(True, description="Whether vehicle is authorized"),
    notes: Optional[str] = Query(None, description="Additional notes"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a new vehicle"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate vehicle type based on user mode
    valid_types = ["personal", "company", "employee", "visitor"]
    if vehicle_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid vehicle type. Must be one of: {', '.join(valid_types)}")

    # Validate category
    valid_categories = ["car", "truck", "motorcycle", "van"]
    if category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}")

    # Check mode-specific constraints
    if user.application_mode == "home" and vehicle_type not in ["personal", "visitor"]:
        raise HTTPException(status_code=400, detail="Home mode only allows personal and visitor vehicles")

    if user.application_mode == "company" and vehicle_type not in ["company", "employee", "visitor"]:
        raise HTTPException(status_code=400, detail="Company mode only allows company, employee, and visitor vehicles")

    # Check for duplicate license plate (within user's vehicles)
    existing = db.query(UserVehicle).filter(
        UserVehicle.license_plate == license_plate,
        UserVehicle.owner_id == user.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="License plate already exists")

    # Create vehicle
    vehicle = UserVehicle(
        owner_id=user.id,
        license_plate=license_plate.upper(),  # Normalize to uppercase
        make=make,
        model=model,
        year=year,
        color=color,
        vehicle_type=vehicle_type,
        category=category,
        is_authorized=is_authorized,
        notes=notes
    )

    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    logger.info(f"Added vehicle {vehicle.id} ({vehicle.license_plate}) for user {user.id}")

    return {
        "success": True,
        "vehicle": {
            "id": vehicle.id,
            "license_plate": vehicle.license_plate,
            "make": vehicle.make,
            "model": vehicle.model,
            "vehicle_type": vehicle.vehicle_type,
            "category": vehicle.category,
            "is_authorized": vehicle.is_authorized
        }
    }


@router.put("/{vehicle_id}", summary="Update vehicle")
async def update_vehicle(
    vehicle_id: int,
    license_plate: Optional[str] = Query(None, description="License plate number"),
    make: Optional[str] = Query(None, description="Vehicle make"),
    model: Optional[str] = Query(None, description="Vehicle model"),
    year: Optional[int] = Query(None, description="Vehicle year"),
    color: Optional[str] = Query(None, description="Vehicle color"),
    vehicle_type: Optional[str] = Query(None, description="Vehicle type"),
    category: Optional[str] = Query(None, description="Vehicle category"),
    is_active: Optional[bool] = Query(None, description="Whether vehicle is active"),
    is_authorized: Optional[bool] = Query(None, description="Whether vehicle is authorized"),
    is_blacklisted: Optional[bool] = Query(None, description="Whether vehicle is blacklisted"),
    blacklist_reason: Optional[str] = Query(None, description="Blacklist reason"),
    notes: Optional[str] = Query(None, description="Additional notes"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing vehicle"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    vehicle = db.query(UserVehicle).filter(
        UserVehicle.id == vehicle_id,
        UserVehicle.owner_id == user.id
    ).first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Validate vehicle type if changing
    if vehicle_type is not None:
        valid_types = ["personal", "company", "employee", "visitor"]
        if vehicle_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid vehicle type. Must be one of: {', '.join(valid_types)}")

        # Check mode-specific constraints
        if user.application_mode == "home" and vehicle_type not in ["personal", "visitor"]:
            raise HTTPException(status_code=400, detail="Home mode only allows personal and visitor vehicles")

        if user.application_mode == "company" and vehicle_type not in ["company", "employee", "visitor"]:
            raise HTTPException(status_code=400, detail="Company mode only allows company, employee, and visitor vehicles")

    # Validate category if changing
    if category is not None:
        valid_categories = ["car", "truck", "motorcycle", "van"]
        if category not in valid_categories:
            raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}")

    # Check for duplicate license plate if changing
    if license_plate and license_plate.upper() != vehicle.license_plate:
        existing = db.query(UserVehicle).filter(
            UserVehicle.license_plate == license_plate.upper(),
            UserVehicle.owner_id == user.id,
            UserVehicle.id != vehicle_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="License plate already exists")

    # Update fields
    if license_plate is not None:
        vehicle.license_plate = license_plate.upper()
    if make is not None:
        vehicle.make = make
    if model is not None:
        vehicle.model = model
    if year is not None:
        vehicle.year = year
    if color is not None:
        vehicle.color = color
    if vehicle_type is not None:
        vehicle.vehicle_type = vehicle_type
    if category is not None:
        vehicle.category = category
    if is_active is not None:
        vehicle.is_active = is_active
    if is_authorized is not None:
        vehicle.is_authorized = is_authorized
    if is_blacklisted is not None:
        vehicle.is_blacklisted = is_blacklisted
    if blacklist_reason is not None:
        vehicle.blacklist_reason = blacklist_reason
    if notes is not None:
        vehicle.notes = notes

    db.commit()
    db.refresh(vehicle)

    logger.info(f"Updated vehicle {vehicle.id}")

    return {
        "success": True,
        "vehicle": {
            "id": vehicle.id,
            "license_plate": vehicle.license_plate,
            "make": vehicle.make,
            "model": vehicle.model,
            "vehicle_type": vehicle.vehicle_type,
            "category": vehicle.category,
            "is_active": vehicle.is_active,
            "is_authorized": vehicle.is_authorized,
            "is_blacklisted": vehicle.is_blacklisted
        }
    }


@router.delete("/{vehicle_id}", summary="Delete vehicle")
async def delete_vehicle(
    vehicle_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a vehicle"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    vehicle = db.query(UserVehicle).filter(
        UserVehicle.id == vehicle_id,
        UserVehicle.owner_id == user.id
    ).first()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    db.delete(vehicle)
    db.commit()

    logger.info(f"Deleted vehicle {vehicle_id}")

    return {"success": True, "message": "Vehicle deleted"}