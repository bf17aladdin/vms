from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_user
from vms.backend.models import SystemHealthLog
from vms.backend.services.system_health_service import SystemHealthService

router = APIRouter(prefix="/api/system", tags=["system-health"])


@router.get("/health/full")
def system_health_full(
    window_minutes: int = Query(60, ge=1, le=24 * 60),
    persist: bool = Query(True),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = SystemHealthService(db)
    return service.get_full_health(persist=bool(persist), window_minutes=int(window_minutes))


@router.get("/health/logs")
def system_health_logs(
    service_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None, pattern="^(healthy|degraded|down|unknown)?$"),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(SystemHealthLog)
    if service_name:
        query = query.filter(SystemHealthLog.service_name == service_name)
    if status:
        query = query.filter(SystemHealthLog.status == status)

    rows = query.order_by(SystemHealthLog.last_check.desc()).limit(int(limit)).all()
    return {
        "success": True,
        "count": len(rows),
        "logs": [
            {
                "id": row.id,
                "service_name": row.service_name,
                "status": row.status,
                "last_check": row.last_check.isoformat() if row.last_check else None,
                "latency_ms": float(row.latency_ms) if row.latency_ms is not None else None,
                "error_count": int(row.error_count or 0),
                "details": row.details or {},
            }
            for row in rows
        ],
    }
