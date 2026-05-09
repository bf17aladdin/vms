# vms/backend/routers/alerts.py - Endpoints REST pour gestion des alertes

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from ..core.security import get_current_user, require_viewer, require_operator
from ..services.alert_service import (
    get_alert_service,
    AlertType,
    AlertSeverity,
    filter_alert_payloads,
    get_allowed_alert_types,
)

router = APIRouter(
    prefix="/api/alerts",
    tags=["alerts"]
)


def _parse_alert_timestamp(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _rule_label(alert: Dict) -> str:
    data = alert.get("data")
    if isinstance(data, dict):
        rule_type = data.get("rule_type") or data.get("rule_id")
        if rule_type:
            return str(rule_type)
    return str(alert.get("type") or "unknown")

def _normalize_rule_filter(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip().lower()
    return raw if raw else None


def _normalize_severity_filter(value: Optional[str]) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    allowed = {"low", "medium", "high", "critical"}
    return raw if raw in allowed else None


def _camera_label(alert: Dict) -> str:
    camera_name = alert.get("camera_name")
    if camera_name:
        return str(camera_name)
    camera_id = alert.get("camera_id")
    if camera_id is not None:
        return f"Camera {camera_id}"
    return "Unknown"


@router.get("", summary="Recuperer les alertes actives")
@router.get("/", summary="Recuperer les alertes actives")
async def get_active_alerts(
    alert_type: Optional[str] = Query(None, alias="type"),
    camera_id: Optional[int] = Query(None),
    current_user=Depends(require_viewer),
):
    """Recuperer la liste des alertes actives"""
    service = get_alert_service()
    alerts = service.get_active_alerts()
    allowed_types = get_allowed_alert_types()
    tenant_id = current_user.get("tenant_id")
    return filter_alert_payloads(
        alerts,
        allowed_types=allowed_types,
        requested_type=alert_type,
        camera_id=camera_id,
        tenant_id=tenant_id,
    )
@router.get("/history", summary="R?cup?rer l'historique des alertes")
async def get_alert_history(
    limit: int = Query(100, ge=1, le=1000),
    camera_id: Optional[int] = Query(None),
    severity: Optional[str] = Query(None),
    rule: Optional[str] = Query(None),
    hours: Optional[int] = Query(None, ge=1, le=720),
    current_user=Depends(require_viewer),
):
    """
    R?cup?rer l'historique des alertes.

    Parameters:
    - limit: Nombre max d'alertes (1-1000)
    - camera_id: Filtrer par ID cam?ra (optionnel)
    """
    service = get_alert_service()
    tenant_id = current_user.get("tenant_id")
    alerts = service.get_alert_history(limit=limit, camera_id=camera_id)
    filtered = filter_alert_payloads(
        alerts,
        allowed_types=get_allowed_alert_types(),
        camera_id=camera_id,
        tenant_id=tenant_id,
    )

    severity_filter = _normalize_severity_filter(severity)
    rule_filter = _normalize_rule_filter(rule)
    if severity_filter:
        filtered = [
            alert for alert in filtered if str(alert.get("severity") or "").lower() == severity_filter
        ]
    if rule_filter:
        filtered = [
            alert for alert in filtered if _rule_label(alert).strip().lower() == rule_filter
        ]

    if hours:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        recent: List[Dict] = []
        for alert in filtered:
            ts = _parse_alert_timestamp(alert.get("timestamp"))
            if ts is not None and ts >= cutoff:
                recent.append(alert)
        filtered = recent

    return filtered
@router.get("/statistics", summary="Statistiques des alertes")
async def get_alert_statistics(current_user=Depends(require_viewer)):
    """R?cup?rer les statistiques d'alertes"""
    service = get_alert_service()
    # Use the database-driven statistics from AlertService
    stats = service.get_statistics()

    # For now, return the global stats (tenant filtering would require DB-level filtering)
    # TODO: Add tenant filtering to database queries
    return stats


@router.get("/stats", summary="Stats alertes (dashboard)")
async def get_alert_dashboard_stats(
    hours: int = Query(24, ge=1, le=720),
    severity: Optional[str] = Query(None),
    rule: Optional[str] = Query(None),
    camera_id: Optional[int] = Query(None),
    current_user=Depends(require_viewer),
):
    """Statistiques simples pour dashboard (par defaut 24h)."""
    service = get_alert_service()
    tenant_id = current_user.get("tenant_id")
    alerts = filter_alert_payloads(
        service.get_alert_history(limit=5000),
        allowed_types=get_allowed_alert_types(),
        tenant_id=tenant_id,
        camera_id=camera_id,
    )

    now = datetime.utcnow()
    window_start = now - timedelta(hours=hours)
    recent_alerts: List[Dict] = []

    for alert in alerts:
        ts = _parse_alert_timestamp(alert.get("timestamp"))
        if ts is None:
            continue
        if ts >= window_start:
            recent_alerts.append(alert)

    severity_filter = _normalize_severity_filter(severity)
    rule_filter = _normalize_rule_filter(rule)

    if severity_filter:
        recent_alerts = [
            alert for alert in recent_alerts if str(alert.get("severity") or "").lower() == severity_filter
        ]
    if rule_filter:
        recent_alerts = [
            alert for alert in recent_alerts if _rule_label(alert).strip().lower() == rule_filter
        ]

    high_severity = 0
    rule_counts: Dict[str, int] = {}
    camera_counts: Dict[str, int] = {}
    camera_meta: Dict[str, Dict[str, Optional[str]]] = {}
    timeline_counts: Dict[str, int] = {}
    incident_tracker: Dict[str, Dict[str, object]] = {}

    for alert in recent_alerts:
        severity = str(alert.get("severity") or "").lower()
        if severity in {"high", "critical"}:
            high_severity += 1

        rule_key = _rule_label(alert)
        rule_counts[rule_key] = rule_counts.get(rule_key, 0) + 1

        camera_id_value = alert.get("camera_id")
        camera_key = str(camera_id_value or "unknown")
        camera_counts[camera_key] = camera_counts.get(camera_key, 0) + 1
        if camera_key not in camera_meta:
            camera_meta[camera_key] = {
                "camera_id": camera_id_value if camera_id_value is not None else None,
                "camera_name": _camera_label(alert),
            }

        incident_key = f"{rule_key}::{camera_key}"
        incident = incident_tracker.get(incident_key)
        ts_value = _parse_alert_timestamp(alert.get("timestamp"))
        if incident is None:
            incident_tracker[incident_key] = {
                "rule": rule_key,
                "camera_id": camera_id_value,
                "camera_name": camera_meta.get(camera_key, {}).get("camera_name"),
                "count": 1,
                "last_seen": ts_value.isoformat() if ts_value else None,
            }
        else:
            incident["count"] = int(incident.get("count") or 0) + 1
            last_seen = incident.get("last_seen")
            if ts_value is not None:
                last_seen_ts = _parse_alert_timestamp(last_seen) if last_seen else None
                if last_seen_ts is None or ts_value > last_seen_ts:
                    incident["last_seen"] = ts_value.isoformat()

        ts = _parse_alert_timestamp(alert.get("timestamp"))
        if ts is not None:
            bucket = ts.replace(minute=0, second=0, microsecond=0).isoformat()
            timeline_counts[bucket] = timeline_counts.get(bucket, 0) + 1

    start_bucket = window_start.replace(minute=0, second=0, microsecond=0)
    end_bucket = now.replace(minute=0, second=0, microsecond=0)
    bucket_count = int((end_bucket - start_bucket).total_seconds() // 3600) + 1
    timeline: List[Dict[str, object]] = []
    for i in range(max(bucket_count, 1)):
        bucket_time = start_bucket + timedelta(hours=i)
        key = bucket_time.isoformat()
        timeline.append({"bucket": key, "count": timeline_counts.get(key, 0)})

    sorted_rules = sorted(rule_counts.items(), key=lambda item: item[1], reverse=True)
    sorted_cameras = sorted(camera_counts.items(), key=lambda item: item[1], reverse=True)
    sorted_incidents = sorted(
        incident_tracker.values(),
        key=lambda item: (int(item.get("count") or 0), str(item.get("last_seen") or "")),
        reverse=True,
    )

    top_rule = None
    if sorted_rules:
        top_rule = {"rule": sorted_rules[0][0], "count": sorted_rules[0][1]}

    top_camera = None
    if sorted_cameras:
        top_key = sorted_cameras[0][0]
        meta = camera_meta.get(top_key, {})
        top_camera = {
            "camera_id": meta.get("camera_id"),
            "camera_name": meta.get("camera_name"),
            "count": sorted_cameras[0][1],
        }

    # Comparison vs previous window
    prev_start = window_start - timedelta(hours=hours)
    previous_alerts: List[Dict] = []
    for alert in alerts:
        ts = _parse_alert_timestamp(alert.get("timestamp"))
        if ts is None:
            continue
        if prev_start <= ts < window_start:
            previous_alerts.append(alert)

    if severity_filter:
        previous_alerts = [
            alert for alert in previous_alerts if str(alert.get("severity") or "").lower() == severity_filter
        ]
    if rule_filter:
        previous_alerts = [
            alert for alert in previous_alerts if _rule_label(alert).strip().lower() == rule_filter
        ]

    prev_total = len(previous_alerts)
    prev_high = len(
        [alert for alert in previous_alerts if str(alert.get("severity") or "").lower() in {"high", "critical"}]
    )
    total_delta = len(recent_alerts) - prev_total
    high_delta = high_severity - prev_high
    total_delta_pct = (total_delta / prev_total * 100.0) if prev_total > 0 else None
    high_delta_pct = (high_delta / prev_high * 100.0) if prev_high > 0 else None

    return {
        "window_hours": hours,
        "generated_at": now.isoformat(),
        "total_alerts": len(recent_alerts),
        "high_severity": high_severity,
        "top_camera": top_camera,
        "top_rule": top_rule,
        "timeline": timeline,
        "by_rule": [{"rule": key, "count": value} for key, value in sorted_rules],
        "by_camera": [
            {
                "camera_id": camera_meta.get(key, {}).get("camera_id"),
                "camera_name": camera_meta.get(key, {}).get("camera_name"),
                "count": value,
            }
            for key, value in sorted_cameras
        ],
        "top_incidents": sorted_incidents[:8],
        "trend": {
            "total_alerts_prev": prev_total,
            "high_severity_prev": prev_high,
            "total_delta": total_delta,
            "total_delta_pct": total_delta_pct,
            "high_delta": high_delta,
            "high_delta_pct": high_delta_pct,
        },
    }
@router.get("/by-type/{alert_type}", summary="Alertes par type")
async def get_alerts_by_type(alert_type: str, current_user=Depends(require_viewer)):
    """
    R?cup?rer les alertes d'un type sp?cifique.

    Types: motion, vehicle, person, face, alarm, system
    """
    try:
        alert_enum = AlertType(alert_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Type d'alerte invalide: {alert_type}")

    service = get_alert_service()
    tenant_id = current_user.get("tenant_id")
    alerts = service.get_alerts_by_type(alert_enum)
    return filter_alert_payloads(
        alerts,
        allowed_types=get_allowed_alert_types(),
        requested_type=alert_type,
        tenant_id=tenant_id,
    )
@router.post("/{alert_id}/ack", summary="Reconna?tre une alerte")
@router.post("/{alert_id}/acknowledge", summary="Reconna?tre une alerte")
async def acknowledge_alert(alert_id: int, current_user=Depends(require_operator)):
    """Marquer une alerte comme reconnue"""
    service = get_alert_service()
    user_id = current_user.get("user_id")
    if service.acknowledge_alert(alert_id, acknowledged_by=user_id):
        return {"status": "success", "message": f"Alerte {alert_id} reconnue"}
    else:
        raise HTTPException(status_code=404, detail=f"Alerte {alert_id} non trouv?e")
@router.delete("/{alert_id}", summary="Supprimer une alerte")
async def delete_alert(alert_id: int, current_user=Depends(require_operator)):
    """Supprimer une alerte active"""
    service = get_alert_service()
    if service.acknowledge_alert(alert_id):
        return {"status": "success", "message": f"Alerte {alert_id} supprim?e"}
    else:
        raise HTTPException(status_code=404, detail=f"Alerte {alert_id} non trouv?e")
@router.delete("/camera/{camera_id}", summary="Effacer alertes par cam?ra")
async def clear_camera_alerts(camera_id: int, current_user=Depends(require_operator)):
    """Effacer toutes les alertes actives d'une cam?ra"""
    service = get_alert_service()
    count = service.clear_alerts(camera_id=camera_id)
    return {"status": "success", "cleared": count}
@router.delete("/", summary="Effacer toutes les alertes")
async def clear_all_alerts(current_user=Depends(require_operator)):
    """Effacer TOUTES les alertes actives"""
    service = get_alert_service()
    count = service.clear_alerts()
    return {"status": "success", "cleared": count}

@router.post("/cleanup", summary="Nettoyer les anciennes alertes")
async def cleanup_old_alerts(days: int = Query(90, ge=1, le=365), current_user=Depends(require_operator)):
    """Nettoyer les alertes anciennes selon la politique de rétention"""
    service = get_alert_service()
    deleted_count = service.cleanup_old_alerts(days=days)
    return {"status": "success", "deleted": deleted_count, "retention_days": days}
