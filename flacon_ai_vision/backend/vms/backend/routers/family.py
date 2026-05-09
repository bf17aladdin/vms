# vms/backend/routers/family.py - API endpoints for family member management (home mode)

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from ..core.database import get_db
from ..core.security import get_current_user
from ..models import User, FamilyMember

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/family",
    tags=["family"]
)


@router.get("/members", summary="Get family members")
async def get_family_members(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all family members for the current user"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.application_mode != "home":
        raise HTTPException(status_code=400, detail="Family management is only available in home mode")

    members = db.query(FamilyMember).filter(FamilyMember.user_id == user.id).all()

    return {
        "members": [
            {
                "id": member.id,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "full_name": member.full_name,
                "relationship": member.family_relationship,
                "date_of_birth": member.date_of_birth.isoformat() if member.date_of_birth else None,
                "gender": member.gender,
                "email": member.email,
                "phone": member.phone,
                "is_active": member.is_active,
                "is_authorized": member.is_authorized,
                "notes": member.notes,
                "created_at": member.created_at.isoformat(),
                "updated_at": member.updated_at.isoformat()
            }
            for member in members
        ]
    }


@router.post("/members", summary="Add family member")
async def add_family_member(
    first_name: str = Query(..., description="First name"),
    last_name: str = Query(..., description="Last name"),
    relationship: Optional[str] = Query(None, description="Relationship to user"),
    date_of_birth: Optional[str] = Query(None, description="Date of birth (YYYY-MM-DD)"),
    gender: Optional[str] = Query(None, description="Gender"),
    email: Optional[str] = Query(None, description="Email address"),
    phone: Optional[str] = Query(None, description="Phone number"),
    is_authorized: bool = Query(True, description="Whether member is authorized"),
    notes: Optional[str] = Query(None, description="Additional notes"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a new family member"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.application_mode != "home":
        raise HTTPException(status_code=400, detail="Family management is only available in home mode")

    # Parse date of birth
    dob = None
    if date_of_birth:
        try:
            from datetime import datetime
            dob = datetime.fromisoformat(date_of_birth)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    # Create family member
    member = FamilyMember(
        user_id=user.id,
        first_name=first_name,
        last_name=last_name,
        full_name=f"{first_name} {last_name}",
        family_relationship=relationship,
        date_of_birth=dob,
        gender=gender,
        email=email,
        phone=phone,
        is_authorized=is_authorized,
        notes=notes
    )

    db.add(member)
    db.commit()
    db.refresh(member)

    logger.info(f"Added family member {member.id} for user {user.id}")

    return {
        "success": True,
        "member": {
            "id": member.id,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "full_name": member.full_name,
            "relationship": member.family_relationship,
            "is_authorized": member.is_authorized
        }
    }


@router.put("/members/{member_id}", summary="Update family member")
async def update_family_member(
    member_id: int,
    first_name: Optional[str] = Query(None, description="First name"),
    last_name: Optional[str] = Query(None, description="Last name"),
    relationship: Optional[str] = Query(None, description="Relationship to user"),
    date_of_birth: Optional[str] = Query(None, description="Date of birth (YYYY-MM-DD)"),
    gender: Optional[str] = Query(None, description="Gender"),
    email: Optional[str] = Query(None, description="Email address"),
    phone: Optional[str] = Query(None, description="Phone number"),
    is_authorized: Optional[bool] = Query(None, description="Whether member is authorized"),
    notes: Optional[str] = Query(None, description="Additional notes"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing family member"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    member = db.query(FamilyMember).filter(
        FamilyMember.id == member_id,
        FamilyMember.user_id == user.id
    ).first()

    if not member:
        raise HTTPException(status_code=404, detail="Family member not found")

    # Update fields
    if first_name is not None:
        member.first_name = first_name
    if last_name is not None:
        member.last_name = last_name
        member.full_name = f"{member.first_name} {last_name}"

    if relationship is not None:
        member.family_relationship = relationship

    if date_of_birth is not None:
        try:
            from datetime import datetime
            member.date_of_birth = datetime.fromisoformat(date_of_birth)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    if gender is not None:
        member.gender = gender
    if email is not None:
        member.email = email
    if phone is not None:
        member.phone = phone
    if is_authorized is not None:
        member.is_authorized = is_authorized
    if notes is not None:
        member.notes = notes

    db.commit()
    db.refresh(member)

    logger.info(f"Updated family member {member.id}")

    return {
        "success": True,
        "member": {
            "id": member.id,
            "first_name": member.first_name,
            "last_name": member.last_name,
            "full_name": member.full_name,
            "relationship": member.family_relationship,
            "is_authorized": member.is_authorized
        }
    }


@router.delete("/members/{member_id}", summary="Delete family member")
async def delete_family_member(
    member_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a family member"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    member = db.query(FamilyMember).filter(
        FamilyMember.id == member_id,
        FamilyMember.user_id == user.id
    ).first()

    if not member:
        raise HTTPException(status_code=404, detail="Family member not found")

    db.delete(member)
    db.commit()

    logger.info(f"Deleted family member {member_id}")

    return {"success": True, "message": "Family member deleted"}