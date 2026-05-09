from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
import logging
from threading import Lock
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from vms.backend.core.database import SessionLocal
from vms.backend.models import Camera, FaceDetection, SystemHealthLog, UnknownDetection, VehicleEvent
from vms.backend.routers.ws import broadcast_analytics
from vms.backend.services.alert_service import get_alert_service
from vms.backend.services.video_recorder import get_video_recorder

logger = logging.getLogger(__name__)

METRICS_START_TIME = datetime.now(timezone.utc)

_HISTORY: deque[Dict[str, Any]] = deque(maxlen=120)
_HISTORY_LOCK = Lock()

_METRICS_TASK: Optional[asyncio.Task] = None
_METRICS_STOP: Optional[asyncio.Event] = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _format_uptime(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _window_cutoff(window_minutes: int) -> datetime:
    return _now_utc() - timedelta(minutes=max(1, int(window_minutes)))


def _build_history_entry(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": summary.get("timestamp"),
        "sla_percent": summary.get("sla_percent"),
        "latency_ms": summary.get("avg_latency_ms"),
        "false_positive_rate": summary.get("false_positive_rate"),
    }


def _history_payload() -> Dict[str, List[Any]]:
    with _HISTORY_LOCK:
        items = list(_HISTORY)
    return {
        "timestamps": [item.get("timestamp") for item in items],
        "sla_percent": [item.get("sla_percent") for item in items],
        "latency_ms": [item.get("latency_ms") for item in items],
        "false_positive_rate": [item.get("false_positive_rate") for item in items],
    }


def _append_history(summary: Dict[str, Any]) -> None:
    entry = _build_history_entry(summary)
    with _HISTORY_LOCK:
        _HISTORY.append(entry)


def _query_detection_stats(
    db: Session,
    model,
    *,
    camera_field,
    time_field,
    confidence_field,
    cutoff: datetime,
) -> Dict[int, Dict[str, float]]:
    rows = (
        db.query(
            camera_field,
            func.count(model.id),
            func.avg(confidence_field),
        )
        .filter(time_field >= cutoff)
        .group_by(camera_field)
        .all()
    )
    stats: Dict[int, Dict[str, float]] = {}
    for camera_id, count, avg_conf in rows:
        if camera_id is None:
            continue
        stats[int(camera_id)] = {
            "count": int(count or 0),
            "avg_confidence": float(avg_conf or 0.0),
        }
    return stats


def _query_unknown_resolution_stats(
    db: Session,
    *,
    cutoff: datetime,
    detection_type: Optional[str] = None,
) -> Dict[int, Dict[str, int]]:
    query = db.query(
        UnknownDetection.camera_id,
        func.sum(case((UnknownDetection.is_resolved.is_(True), 1), else_=0)),
        func.sum(case((UnknownDetection.is_ignored.is_(True), 1), else_=0)),
    ).filter(UnknownDetection.resolved_at >= cutoff)
    if detection_type:
        query = query.filter(UnknownDetection.detection_type == detection_type)
    rows = query.group_by(UnknownDetection.camera_id).all()
    stats: Dict[int, Dict[str, int]] = {}
    for camera_id, resolved, ignored in rows:
        if camera_id is None:
            continue
        stats[int(camera_id)] = {
            "resolved": int(resolved or 0),
            "ignored": int(ignored or 0),
        }
    return stats


def _query_unknown_created(
    db: Session,
    *,
    cutoff: datetime,
    detection_type: Optional[str] = None,
) -> int:
    query = db.query(func.count(UnknownDetection.id)).filter(UnknownDetection.created_at >= cutoff)
    if detection_type:
        query = query.filter(UnknownDetection.detection_type == detection_type)
    return int(query.scalar() or 0)


def _compute_sla_percent(db: Session, cutoff: datetime) -> float:
    rows = (
        db.query(SystemHealthLog.status)
        .filter(SystemHealthLog.last_check >= cutoff)
        .all()
    )
    if not rows:
        return 100.0
    healthy = sum(1 for (status,) in rows if str(status or "").lower() == "healthy")
    return round((healthy / max(1, len(rows))) * 100.0, 2)


def _compute_latency_ms(db: Session, cutoff: datetime) -> float:
    avg_pipeline = (
        db.query(func.avg(SystemHealthLog.latency_ms))
        .filter(SystemHealthLog.service_name == "pipeline")
        .filter(SystemHealthLog.last_check >= cutoff)
        .scalar()
    )
    if avg_pipeline is not None:
        return round(float(avg_pipeline), 2)
    avg_any = (
        db.query(func.avg(SystemHealthLog.latency_ms))
        .filter(SystemHealthLog.last_check >= cutoff)
        .scalar()
    )
    return round(float(avg_any or 0.0), 2)


def get_metrics_snapshot(
    db: Session,
    *,
    window_minutes: int = 60,
    camera_id: Optional[int] = None,
    profile: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now_utc()
    cutoff = _window_cutoff(window_minutes)
    profile_key = str(profile or "all").strip().lower()
    if profile_key not in {"all", "face", "vehicle"}:
        profile_key = "all"

    cameras = db.query(Camera).all()
    camera_lookup = {int(cam.id): cam for cam in cameras}

    face_stats = _query_detection_stats(
        db,
        FaceDetection,
        camera_field=FaceDetection.camera_id,
        time_field=FaceDetection.detected_at,
        confidence_field=FaceDetection.confidence,
        cutoff=cutoff,
    )
    vehicle_stats = _query_detection_stats(
        db,
        VehicleEvent,
        camera_field=VehicleEvent.camera_id,
        time_field=VehicleEvent.timestamp,
        confidence_field=VehicleEvent.confidence,
        cutoff=cutoff,
    )

    unknown_resolutions_all = _query_unknown_resolution_stats(db, cutoff=cutoff)

    recorder_metrics = get_video_recorder().get_recording_metrics()
    fps_by_camera = {
        int(row.get("camera_id") or 0): float(row.get("active_fps_avg") or 0.0)
        for row in recorder_metrics.get("camera_metrics", [])
    }

    alert_service = get_alert_service()
    alert_rows = alert_service.get_alert_history(limit=500)
    alerts_by_camera: Dict[int, int] = {}
    for row in alert_rows:
        cam_id = int(row.get("camera_id") or 0)
        if cam_id <= 0:
            continue
        alerts_by_camera[cam_id] = alerts_by_camera.get(cam_id, 0) + 1

    camera_metrics: List[Dict[str, Any]] = []
    total_detections = 0
    total_fps = 0.0
    healthy_streams = 0

    for cam_id, cam in camera_lookup.items():
        face = face_stats.get(cam_id, {"count": 0, "avg_confidence": 0.0})
        vehicle = vehicle_stats.get(cam_id, {"count": 0, "avg_confidence": 0.0})

        if profile_key == "face":
            detections = face["count"]
            avg_conf = face["avg_confidence"]
        elif profile_key == "vehicle":
            detections = vehicle["count"]
            avg_conf = vehicle["avg_confidence"]
        else:
            detections = int(face["count"]) + int(vehicle["count"])
            weighted_total = (face["avg_confidence"] * face["count"]) + (
                vehicle["avg_confidence"] * vehicle["count"]
            )
            avg_conf = weighted_total / max(1, detections)

        fps = float(fps_by_camera.get(cam_id, 0.0))
        if fps >= 5.0:
            healthy_streams += 1

        resolution = unknown_resolutions_all.get(cam_id, {"resolved": 0, "ignored": 0})
        resolved = int(resolution.get("resolved") or 0)
        ignored = int(resolution.get("ignored") or 0)
        fp_rate = ignored / (resolved + ignored) if (resolved + ignored) > 0 else 0.0

        camera_metrics.append(
            {
                "id": cam_id,
                "name": cam.name,
                "detections": int(detections),
                "confidence": round(float(avg_conf or 0.0), 3),
                "fps": round(fps, 3),
                "alerts": alerts_by_camera.get(cam_id, 0),
                "false_positive_rate": round(fp_rate, 4),
                "latency_ms": None,
            }
        )

        total_detections += int(detections)
        total_fps += float(fps)

    total_cameras = len(camera_metrics)
    stream_health = (
        round((healthy_streams / total_cameras) * 100.0)
        if total_cameras > 0
        else 100
    )

    resolved_unknowns = (
        db.query(func.count(UnknownDetection.id))
        .filter(UnknownDetection.resolved_at >= cutoff)
        .filter(UnknownDetection.is_resolved.is_(True))
        .scalar()
    )
    ignored_unknowns = (
        db.query(func.count(UnknownDetection.id))
        .filter(UnknownDetection.resolved_at >= cutoff)
        .filter(UnknownDetection.is_ignored.is_(True))
        .scalar()
    )
    resolved_unknowns = int(resolved_unknowns or 0)
    ignored_unknowns = int(ignored_unknowns or 0)
    false_positive_rate = (
        ignored_unknowns / (resolved_unknowns + ignored_unknowns)
        if (resolved_unknowns + ignored_unknowns) > 0
        else 0.0
    )

    sla_percent = _compute_sla_percent(db, cutoff)
    avg_latency_ms = _compute_latency_ms(db, cutoff)
    alerts_active = len(alert_service.get_active_alerts())
    uptime_seconds = int((now - METRICS_START_TIME).total_seconds())

    summary = {
        "timestamp": _iso(now),
        "window_minutes": int(window_minutes),
        "sla_percent": sla_percent,
        "false_positive_rate": round(false_positive_rate, 4),
        "avg_latency_ms": avg_latency_ms,
        "uptime_seconds": uptime_seconds,
        "uptime_human": _format_uptime(uptime_seconds),
        "alerts_active": alerts_active,
        "detections_total": total_detections,
        "avg_fps": round(total_fps / max(1, total_cameras), 2) if total_cameras > 0 else 0.0,
        "stream_health": stream_health,
        "camera_count": total_cameras,
    }

    profiles: List[Dict[str, Any]] = []
    for profile_name in ("face", "vehicle"):
        if profile_name == "face":
            detections = sum(item["count"] for item in face_stats.values())
            avg_conf = (
                sum(item["avg_confidence"] * item["count"] for item in face_stats.values())
                / max(1, detections)
            )
            unknowns = _query_unknown_created(db, cutoff=cutoff, detection_type="face")
            resolutions = _query_unknown_resolution_stats(db, cutoff=cutoff, detection_type="face")
        else:
            detections = sum(item["count"] for item in vehicle_stats.values())
            avg_conf = (
                sum(item["avg_confidence"] * item["count"] for item in vehicle_stats.values())
                / max(1, detections)
            )
            unknowns = _query_unknown_created(db, cutoff=cutoff, detection_type="vehicle")
            resolutions = _query_unknown_resolution_stats(db, cutoff=cutoff, detection_type="vehicle")

        resolved = sum(item.get("resolved", 0) for item in resolutions.values())
        ignored = sum(item.get("ignored", 0) for item in resolutions.values())
        fp_rate = ignored / (resolved + ignored) if (resolved + ignored) > 0 else 0.0
        unknown_rate = unknowns / max(1, detections)

        profiles.append(
            {
                "profile": profile_name,
                "detections": int(detections),
                "avg_confidence": round(float(avg_conf or 0.0), 3),
                "unknown_rate": round(float(unknown_rate), 4),
                "false_positive_rate": round(float(fp_rate), 4),
            }
        )

    _append_history(summary)

    return {
        "summary": summary,
        "cameras": camera_metrics,
        "profiles": profiles,
        "history": _history_payload(),
        "filters": {"camera_id": camera_id, "profile": profile_key},
    }


async def _metrics_loop(interval_sec: int) -> None:
    assert _METRICS_STOP is not None
    while not _METRICS_STOP.is_set():
        try:
            db = SessionLocal()
            try:
                snapshot = get_metrics_snapshot(db, window_minutes=60)
            finally:
                db.close()
            await broadcast_analytics(snapshot)
        except Exception as exc:
            logger.error("Metrics broadcast failed: %s", exc)

        try:
            await asyncio.wait_for(_METRICS_STOP.wait(), timeout=max(1, interval_sec))
        except asyncio.TimeoutError:
            continue


async def start_metrics_loop(interval_sec: int = 5) -> None:
    global _METRICS_TASK, _METRICS_STOP
    if _METRICS_TASK is not None and not _METRICS_TASK.done():
        return
    _METRICS_STOP = asyncio.Event()
    _METRICS_TASK = asyncio.create_task(_metrics_loop(interval_sec))
    logger.info("Metrics broadcast loop started (interval=%ss)", interval_sec)


async def stop_metrics_loop() -> None:
    global _METRICS_TASK, _METRICS_STOP
    if _METRICS_STOP is not None:
        _METRICS_STOP.set()
    if _METRICS_TASK is not None:
        try:
            await _METRICS_TASK
        except Exception:
            pass
    _METRICS_TASK = None
    _METRICS_STOP = None
    logger.info("Metrics broadcast loop stopped")

