from __future__ import annotations

from datetime import datetime, timezone
import os

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from vms.backend.core.database import get_db
from vms.backend.core.security import get_current_user, require_viewer
from vms.backend.models import Camera, Event, SystemHealthLog
from vms.backend.services.alert_service import get_alert_service, filter_alert_payloads, get_allowed_alert_types

router = APIRouter(prefix="/api", tags=["metrics"])


def _start_of_day_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_iso_timestamp(raw: object) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _resolve_system_load() -> float:
    if psutil is not None:
        try:
            if hasattr(psutil, "getloadavg"):
                return float(psutil.getloadavg()[0])
            return float(psutil.cpu_percent(interval=0.0))
        except Exception:
            pass
    if hasattr(os, "getloadavg"):
        try:
            return float(os.getloadavg()[0])
        except Exception:
            return 0.0
    return 0.0


@router.get("/metrics", summary="Get real-time KPI metrics")
def get_metrics(
    current_user=Depends(require_viewer),
    db: Session = Depends(get_db),
):
    start_day = _start_of_day_utc()
    tenant_id = current_user.get("tenant_id")

    camera_query = db.query(Camera).filter(Camera.is_active == True)  # noqa: E712
    if tenant_id is not None:
        camera_query = camera_query.filter(Camera.tenant_id == tenant_id)
    connected_count = int(
        camera_query.filter(Camera.connection_status == "connected").count()
    )
    active_count = int(camera_query.count())
    cameras_online = connected_count if connected_count > 0 else active_count

    try:
        alerts = filter_alert_payloads(
            get_alert_service().get_alert_history(limit=2000),
            allowed_types=get_allowed_alert_types(),
            tenant_id=tenant_id,
        )
        alerts_today = sum(
            1
            for alert in alerts
            if _parse_iso_timestamp(alert.get("timestamp")) is not None
            and _parse_iso_timestamp(alert.get("timestamp")) >= start_day
        )
    except Exception:
        alerts_today = 0

    event_query = db.query(Event).filter(Event.detected_at >= start_day)
    if tenant_id is not None:
        event_query = event_query.filter(Event.tenant_id == tenant_id)
    total_events = int(event_query.count())
    false_positives = int(
        event_query.filter(Event.decision == "denied").count()
    )
    false_positive_rate = round(false_positives / total_events, 4) if total_events else 0.0

    ai_latency = 0.0
    rows = (
        db.query(SystemHealthLog)
        .filter(
            (SystemHealthLog.service_name.ilike("%ai%"))
            | (SystemHealthLog.service_name.ilike("%inference%"))
        )
        .order_by(SystemHealthLog.created_at.desc())
        .limit(20)
        .all()
    )
    latencies = [float(row.latency_ms) for row in rows if row.latency_ms is not None]
    if latencies:
        ai_latency = sum(latencies) / len(latencies)

    system_load = _resolve_system_load()

    return {
        "cameras_online": cameras_online,
        "alerts_today": alerts_today,
        "false_positive_rate": false_positive_rate,
        "ai_latency": ai_latency,
        "system_load": system_load,
    }
