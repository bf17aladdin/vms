from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_current_user
from ..models import User, VehicleEntry
from ..schemas import VehicleEntryCreate, VehicleEntryOut
from ..services.vehicle_entry_service import VehicleEntryService

router = APIRouter(prefix="/api/vehicles-entries", tags=["Vehicle Entries"])


def _parse_iso_or_date(raw: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    try:
        if len(value) == 10:
            parsed_day = date.fromisoformat(value)
            if end_of_day:
                return (
                    datetime.combine(parsed_day, datetime.min.time())
                    + timedelta(days=1)
                    - timedelta(microseconds=1)
                )
            return datetime.combine(parsed_day, datetime.min.time())
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format '{value}'. Use YYYY-MM-DD or ISO datetime.",
        ) from exc


def _build_csv(rows: List[Dict[str, Any]], fieldnames: List[str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in fieldnames})
    return output.getvalue()


@router.post("/entry", response_model=VehicleEntryOut)
def create_vehicle_entry(
    data: VehicleEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VehicleEntryService.create_entry(db, data)


@router.post("/{entry_id:int}/exit", response_model=VehicleEntryOut)
def log_vehicle_exit(
    entry_id: int,
    exit_camera_id: int,
    exit_confidence: float = Query(..., ge=0.0, le=1.0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = VehicleEntryService.log_exit(db, entry_id, exit_camera_id, exit_confidence)
    if not result:
        raise HTTPException(status_code=404, detail="Entry not found")
    return result


@router.get("/active", response_model=List[VehicleEntryOut])
def get_active_vehicles(
    camera_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VehicleEntryService.get_active_vehicles(db, camera_id)


@router.get("/history", response_model=dict)
def get_vehicle_history_filtered(
    plate: Optional[str] = Query(None),
    camera_id: Optional[int] = Query(None),
    zone_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, pattern="^(active|exited)?$"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD or ISO datetime"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD or ISO datetime"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = VehicleEntryService.get_history(
        db=db,
        plate=plate,
        camera_id=camera_id,
        zone_id=zone_id,
        status=status,
        date_from=_parse_iso_or_date(date_from, end_of_day=False),
        date_to=_parse_iso_or_date(date_to, end_of_day=True),
        skip=skip,
        limit=limit,
    )
    return {
        "status": "ok",
        "total": int(payload.get("total", 0)),
        "items": payload.get("items", []),
    }


@router.get("/plate/{license_plate}", response_model=List[VehicleEntryOut])
def get_plate_history(
    license_plate: str,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VehicleEntryService.get_vehicle_history(db, license_plate, days)


@router.get("/{entry_id:int}", response_model=VehicleEntryOut)
def get_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = VehicleEntryService.get_entry(db, entry_id)
    if not result:
        raise HTTPException(status_code=404, detail="Entry not found")
    return result


@router.delete("/{entry_id:int}", response_model=dict)
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        deleted = VehicleEntryService.delete_entry(db, entry_id)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail="Unable to delete this entry because it is linked to other records.",
        ) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found")

    return {"status": "ok", "deleted_id": entry_id}


@router.get("/stats/daily", response_model=dict)
def get_daily_summary(
    camera_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VehicleEntryService.get_daily_summary(db, camera_id)


@router.get("/stats/day", response_model=dict)
def get_day_summary(
    target_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    camera_id: Optional[int] = Query(None),
    zone_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    parsed_day: Optional[date] = None
    if target_date:
        try:
            parsed_day = date.fromisoformat(str(target_date))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="target_date must be YYYY-MM-DD") from exc
    return VehicleEntryService.get_day_summary(
        db=db,
        target_date=parsed_day,
        camera_id=camera_id,
        zone_id=zone_id,
    )


@router.get("/stats/top-plates", response_model=List[dict])
def get_top_plates(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VehicleEntryService.get_plate_statistics(db, days, limit)


@router.get("/stats/by-type", response_model=dict)
def get_type_statistics(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return VehicleEntryService.get_vehicle_type_statistics(db, days)


@router.get("/stats/peak-hours", response_model=dict)
def get_peak_hours(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {
        "peak_hours": VehicleEntryService.get_peak_hours(db, days),
        "period_days": days,
    }


@router.get("/stats/average-stay", response_model=dict)
def get_average_stay(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = VehicleEntryService.get_average_stay_analysis(db, days)
    result["period_days"] = days
    return result


@router.get("/export/history/csv")
def export_history_csv(
    plate: Optional[str] = Query(None),
    camera_id: Optional[int] = Query(None),
    zone_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, pattern="^(active|exited)?$"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = VehicleEntryService.get_history(
        db=db,
        plate=plate,
        camera_id=camera_id,
        zone_id=zone_id,
        status=status,
        date_from=_parse_iso_or_date(date_from, end_of_day=False),
        date_to=_parse_iso_or_date(date_to, end_of_day=True),
        skip=0,
        limit=100000,
    )
    rows = payload.get("items", [])
    fieldnames = [
        "id",
        "license_plate",
        "vehicle_type",
        "brand",
        "model",
        "color",
        "entry_camera_id",
        "entry_camera_name",
        "entry_zone_id",
        "entry_zone_name",
        "exit_camera_id",
        "exit_camera_name",
        "exit_zone_id",
        "exit_zone_name",
        "entry_time",
        "exit_time",
        "duration_minutes",
        "entry_confidence",
        "exit_confidence",
        "status",
        "notes",
    ]
    csv_content = _build_csv(rows, fieldnames)
    filename = f"vehicle_history_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/json", response_model=dict)
def export_json(
    start_date: str = Query(...),
    end_date: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start = _parse_iso_or_date(start_date, end_of_day=False)
    end = _parse_iso_or_date(end_date, end_of_day=True)
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="start_date and end_date are required")
    data = VehicleEntryService.export_vehicle_log(db, start, end, format="json")
    return {
        "status": "ok",
        "period": {"start": start_date, "end": end_date},
        "total_records": len(data),
        "data": data,
    }


@router.post("/export/csv")
def export_csv(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    start = _parse_iso_or_date(start_date, end_of_day=False)
    end = _parse_iso_or_date(end_date, end_of_day=True)
    if start is None or end is None:
        raise HTTPException(status_code=400, detail="start_date and end_date are required")
    data = VehicleEntryService.export_vehicle_log(db, start, end, format="csv")
    fieldnames = list(data[0].keys()) if data else [
        "id",
        "license_plate",
        "vehicle_type",
        "brand",
        "model",
        "color",
        "entry_time",
        "exit_time",
        "duration_minutes",
        "entry_confidence",
        "exit_confidence",
        "status",
    ]
    return JSONResponse(
        content={
            "status": "ok",
            "filename": f"vehicles_{start_date}_{end_date}.csv",
            "csv": _build_csv(data, fieldnames),
        }
    )


@router.get("/search/by-plate", response_model=Optional[VehicleEntryOut])
def search_by_plate(
    license_plate: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = VehicleEntryService.find_or_create_entry(db, license_plate, camera_id=1)
    if not result:
        raise HTTPException(status_code=404, detail="Plate not found")
    return result


@router.get("/search/by-brand", response_model=List[VehicleEntryOut])
def search_by_brand(
    brand: str,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    threshold_date = datetime.utcnow() - timedelta(days=days)
    return (
        db.query(VehicleEntry)
        .filter(
            and_(
                VehicleEntry.brand.ilike(f"%{brand}%"),
                VehicleEntry.entry_time >= threshold_date,
            )
        )
        .order_by(VehicleEntry.entry_time.desc())
        .limit(limit)
        .all()
    )


@router.get("/health/summary", response_model=dict)
def get_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    active = VehicleEntryService.get_active_vehicles(db)
    daily = VehicleEntryService.get_daily_summary(db)
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "active_vehicles": len(active),
        "daily_summary": daily,
    }
