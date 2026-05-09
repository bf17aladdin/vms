# vms/backend/routers/employees.py - API endpoints for employee management (company mode)

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
import logging

from ..core.database import get_db
from ..core.security import get_current_user
from ..models import User, Employee

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/employees",
    tags=["employees"]
)


@router.get("", summary="Get employees")
async def get_employees(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all employees for the current user"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.application_mode != "company":
        raise HTTPException(status_code=400, detail="Employee management is only available in company mode")

    employees = db.query(Employee).filter(Employee.user_id == user.id).all()

    return {
        "employees": [
            {
                "id": employee.id,
                "first_name": employee.first_name,
                "last_name": employee.last_name,
                "full_name": employee.full_name,
                "employee_id": employee.employee_id,
                "department": employee.department,
                "position": employee.position,
                "email": employee.email,
                "phone": employee.phone,
                "hire_date": employee.hire_date.isoformat() if employee.hire_date else None,
                "termination_date": employee.termination_date.isoformat() if employee.termination_date else None,
                "is_active": employee.is_active,
                "is_authorized": employee.is_authorized,
                "notes": employee.notes,
                "created_at": employee.created_at.isoformat(),
                "updated_at": employee.updated_at.isoformat()
            }
            for employee in employees
        ]
    }


@router.post("", summary="Add employee")
async def add_employee(
    first_name: str = Query(..., description="First name"),
    last_name: str = Query(..., description="Last name"),
    employee_id: Optional[str] = Query(None, description="Employee ID"),
    department: Optional[str] = Query(None, description="Department"),
    position: Optional[str] = Query(None, description="Job position"),
    email: Optional[str] = Query(None, description="Email address"),
    phone: Optional[str] = Query(None, description="Phone number"),
    hire_date: Optional[str] = Query(None, description="Hire date (YYYY-MM-DD)"),
    is_authorized: bool = Query(True, description="Whether employee is authorized"),
    notes: Optional[str] = Query(None, description="Additional notes"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a new employee"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.application_mode != "company":
        raise HTTPException(status_code=400, detail="Employee management is only available in company mode")

    # Parse hire date
    hire = None
    if hire_date:
        try:
            from datetime import datetime
            hire = datetime.fromisoformat(hire_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid hire date format. Use YYYY-MM-DD")

    # Check for duplicate employee_id
    if employee_id:
        existing = db.query(Employee).filter(
            Employee.employee_id == employee_id,
            Employee.user_id == user.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Employee ID already exists")

    # Create employee
    employee = Employee(
        user_id=user.id,
        first_name=first_name,
        last_name=last_name,
        full_name=f"{first_name} {last_name}",
        employee_id=employee_id,
        department=department,
        position=position,
        email=email,
        phone=phone,
        hire_date=hire,
        is_authorized=is_authorized,
        notes=notes
    )

    db.add(employee)
    db.commit()
    db.refresh(employee)

    logger.info(f"Added employee {employee.id} for user {user.id}")

    return {
        "success": True,
        "employee": {
            "id": employee.id,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "full_name": employee.full_name,
            "employee_id": employee.employee_id,
            "department": employee.department,
            "position": employee.position,
            "is_authorized": employee.is_authorized
        }
    }


@router.put("/{employee_id}", summary="Update employee")
async def update_employee(
    employee_id: int,
    first_name: Optional[str] = Query(None, description="First name"),
    last_name: Optional[str] = Query(None, description="Last name"),
    emp_id: Optional[str] = Query(None, description="Employee ID"),
    department: Optional[str] = Query(None, description="Department"),
    position: Optional[str] = Query(None, description="Job position"),
    email: Optional[str] = Query(None, description="Email address"),
    phone: Optional[str] = Query(None, description="Phone number"),
    hire_date: Optional[str] = Query(None, description="Hire date (YYYY-MM-DD)"),
    termination_date: Optional[str] = Query(None, description="Termination date (YYYY-MM-DD)"),
    is_active: Optional[bool] = Query(None, description="Whether employee is active"),
    is_authorized: Optional[bool] = Query(None, description="Whether employee is authorized"),
    notes: Optional[str] = Query(None, description="Additional notes"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing employee"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.user_id == user.id
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Check for duplicate employee_id if changing
    if emp_id and emp_id != employee.employee_id:
        existing = db.query(Employee).filter(
            Employee.employee_id == emp_id,
            Employee.user_id == user.id,
            Employee.id != employee_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Employee ID already exists")

    # Update fields
    if first_name is not None:
        employee.first_name = first_name
    if last_name is not None:
        employee.last_name = last_name
        employee.full_name = f"{employee.first_name} {last_name}"

    if emp_id is not None:
        employee.employee_id = emp_id
    if department is not None:
        employee.department = department
    if position is not None:
        employee.position = position
    if email is not None:
        employee.email = email
    if phone is not None:
        employee.phone = phone

    if hire_date is not None:
        try:
            from datetime import datetime
            employee.hire_date = datetime.fromisoformat(hire_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid hire date format. Use YYYY-MM-DD")

    if termination_date is not None:
        try:
            from datetime import datetime
            employee.termination_date = datetime.fromisoformat(termination_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid termination date format. Use YYYY-MM-DD")

    if is_active is not None:
        employee.is_active = is_active
    if is_authorized is not None:
        employee.is_authorized = is_authorized
    if notes is not None:
        employee.notes = notes

    db.commit()
    db.refresh(employee)

    logger.info(f"Updated employee {employee.id}")

    return {
        "success": True,
        "employee": {
            "id": employee.id,
            "first_name": employee.first_name,
            "last_name": employee.last_name,
            "full_name": employee.full_name,
            "employee_id": employee.employee_id,
            "department": employee.department,
            "position": employee.position,
            "is_active": employee.is_active,
            "is_authorized": employee.is_authorized
        }
    }


@router.delete("/{employee_id}", summary="Delete employee")
async def delete_employee(
    employee_id: int,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete an employee"""
    user = db.query(User).filter(User.id == current_user["user_id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    employee = db.query(Employee).filter(
        Employee.id == employee_id,
        Employee.user_id == user.id
    ).first()

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    db.delete(employee)
    db.commit()

    logger.info(f"Deleted employee {employee_id}")

    return {"success": True, "message": "Employee deleted"}