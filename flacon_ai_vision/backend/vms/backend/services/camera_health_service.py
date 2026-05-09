from __future__ import annotations

import logging
import os
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from vms.backend.core.database import SessionLocal
from vms.backend.models import Camera
from vms.backend.services.camera_service import CameraService
from vms.backend.services.stream_service import StreamService

logger = logging.getLogger(__name__)

_MONITOR_THREAD: Optional[threading.Thread] = None
_MONITOR_STOP: Optional[threading.Event] = None


def _bool_env(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _fetch_camera_snapshot(db: Session, max_cameras: int) -> List[Dict[str, object]]:
    query = (
        db.query(Camera)
        .filter(Camera.is_enabled.is_(True))
        .filter(Camera.streaming_enabled.is_(True))
    )
    if max_cameras > 0:
        query = query.limit(int(max_cameras))
    rows = query.all()
    snapshot: List[Dict[str, object]] = []
    for row in rows:
        snapshot.append(
            {
                "id": int(row.id),
                "rtsp_url": row.rtsp_url,
                "ip_address": row.ip_address,
                "port": row.port,
                "username": row.username,
                "password": row.password,
            }
        )
    return snapshot


def _probe_camera(camera: Dict[str, object], timeout_sec: float) -> Dict[str, object]:
    rtsp_url = CameraService._resolve_rtsp_url_value(
        rtsp_url=str(camera.get("rtsp_url") or "") or None,
        ip_address=str(camera.get("ip_address") or "") or None,
        port=int(camera.get("port") or 554),
        username=str(camera.get("username") or "") or None,
        password=str(camera.get("password") or "") or None,
    )
    if not rtsp_url:
        return {
            "id": camera.get("id"),
            "status": "error",
            "error": "No RTSP source configured",
            "latency_ms": None,
            "source": None,
        }
    probe = StreamService.inspect_rtsp_stream(
        rtsp_url,
        open_timeout_sec=timeout_sec,
        read_timeout_sec=timeout_sec,
        force_tcp=True,
        sample_frames=4,
        include_preview=False,
    )
    if probe.get("ok"):
        return {
            "id": camera.get("id"),
            "status": probe.get("status") or "connected",
            "error": None,
            "latency_ms": probe.get("latency_ms"),
            "frame_loss_percent": probe.get("frame_loss_percent"),
            "source": rtsp_url,
        }
    return {
        "id": camera.get("id"),
        "status": probe.get("status") or "disconnected",
        "error": probe.get("error") or "RTSP probe failed",
        "latency_ms": probe.get("latency_ms"),
        "frame_loss_percent": probe.get("frame_loss_percent"),
        "source": rtsp_url,
    }


def _update_camera_status(db: Session, result: Dict[str, object]) -> None:
    camera_id = result.get("id")
    if camera_id is None:
        return
    row = db.query(Camera).filter(Camera.id == int(camera_id)).first()
    if row is None:
        return
    row.connection_status = str(result.get("status") or "unknown")
    row.last_connection_check = datetime.utcnow()
    if result.get("status") == "connected":
        row.connection_error = None
        row.last_activity = datetime.utcnow()
    else:
        row.connection_error = str(result.get("error") or "Connection failed")
        source = result.get("source")
        if source:
            try:
                StreamService.release_camera_stream(rtsp_url=str(source))
            except Exception:
                pass


def _monitor_loop() -> None:
    interval_sec = max(2.0, _float_env("CAMERA_HEALTH_MONITOR_INTERVAL_SEC", 15.0))
    max_workers = max(2, _int_env("CAMERA_HEALTH_MONITOR_MAX_WORKERS", 8))
    timeout_sec = max(1.0, _float_env("CAMERA_HEALTH_MONITOR_TIMEOUT_SEC", 3.0))
    max_cameras = max(0, _int_env("CAMERA_HEALTH_MONITOR_MAX_CAMERAS", 0))

    logger.info("Camera health monitor started (interval=%ss)", interval_sec)

    while _MONITOR_STOP is not None and not _MONITOR_STOP.is_set():
        try:
            with SessionLocal() as db:
                snapshot = _fetch_camera_snapshot(db, max_cameras=max_cameras)
        except Exception as exc:
            logger.warning("Camera health monitor snapshot failed: %s", exc)
            snapshot = []

        results: List[Dict[str, object]] = []
        if snapshot:
            with ThreadPoolExecutor(max_workers=min(max_workers, len(snapshot))) as executor:
                futures = [executor.submit(_probe_camera, cam, timeout_sec) for cam in snapshot]
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        logger.debug("Camera probe failure: %s", exc)

        if results:
            try:
                with SessionLocal() as db:
                    for result in results:
                        _update_camera_status(db, result)
                    db.commit()
            except Exception as exc:
                logger.warning("Camera health monitor update failed: %s", exc)

        if _MONITOR_STOP is not None:
            _MONITOR_STOP.wait(interval_sec)

    logger.info("Camera health monitor stopped")


def start_camera_health_monitor() -> None:
    global _MONITOR_THREAD, _MONITOR_STOP
    if _MONITOR_THREAD and _MONITOR_THREAD.is_alive():
        return
    if not _bool_env("CAMERA_HEALTH_MONITOR_ENABLED", True):
        logger.info("Camera health monitor disabled by env")
        return
    _MONITOR_STOP = threading.Event()
    _MONITOR_THREAD = threading.Thread(target=_monitor_loop, name="camera-health-monitor", daemon=True)
    _MONITOR_THREAD.start()


def stop_camera_health_monitor() -> None:
    global _MONITOR_THREAD, _MONITOR_STOP
    if _MONITOR_STOP is not None:
        _MONITOR_STOP.set()
    if _MONITOR_THREAD is not None:
        _MONITOR_THREAD.join(timeout=3.0)
    _MONITOR_THREAD = None
    _MONITOR_STOP = None
