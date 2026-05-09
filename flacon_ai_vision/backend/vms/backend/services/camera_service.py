# vms/backend/services/camera_service.py - Service métier pour caméras

from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Iterable, Tuple
from datetime import datetime
import base64
import ipaddress
import os
import socket
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, urlunparse, quote

try:
    import cv2  # type: ignore
    _HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore
    _HAS_CV2 = False

from .. import crud
from .. import models
from .. import schemas
from ..services.mediamtx_service import check_mediamtx_rtsp
from ..services.stream_service import StreamService
from ..services.onvif_service import probe_onvif_device

logger = logging.getLogger(__name__)

class CameraService:
    DEFAULT_RTSP_PATHS = [
        "/Streaming/Channels/101",
        "/h264/ch1/main/av_stream",
        "/live.sdp",
        "/cam/realmonitor?channel=1&subtype=0",
        "/stream",
        "/",
    ]
    DEFAULT_SCAN_PORTS = [80, 554, 8554, 6688]
    DEFAULT_RTSP_PORTS = [554, 8554, 6688]
    DEFAULT_ONVIF_PORTS = [80, 8000, 8080, 8899]
    """Service pour gérer les caméras - couche métier"""
    
    @staticmethod
    def get_all_cameras(db: Session, skip: int = 0, limit: int = 100, owner_id: Optional[int] = None, tenant_id: Optional[int] = None) -> List[dict]:
        """R?cup?rer toutes les cam?ras"""
        cameras = crud.get_all_cameras(db, skip=skip, limit=limit, owner_id=owner_id, tenant_id=tenant_id)
        return [CameraService._format_camera(cam) for cam in cameras]
    @staticmethod
    def get_active_cameras(db: Session, tenant_id: Optional[int] = None) -> List[dict]:
        """R?cup?rer les cam?ras actives"""
        cameras = crud.get_active_cameras(db, tenant_id=tenant_id)
        return [CameraService._format_camera(cam) for cam in cameras]
    @staticmethod
    def get_camera(db: Session, camera_id: int, tenant_id: Optional[int] = None) -> Optional[dict]:
        """R?cup?rer une cam?ra par ID"""
        camera = crud.get_camera_by_id(db, camera_id, tenant_id=tenant_id) if tenant_id is not None else crud.get_camera_by_id(db, camera_id)
        if not camera:
            return None
        return CameraService._format_camera(camera)
    @staticmethod
    def get_cameras_by_zone(db: Session, zone_name: str, tenant_id: Optional[int] = None) -> List[dict]:
        """R?cup?rer les cam?ras d'une zone"""
        cameras = crud.get_cameras_by_zone(db, zone_name, tenant_id=tenant_id)
        return [CameraService._format_camera(cam) for cam in cameras]
    @staticmethod
    def get_cameras_by_site(db: Session, site_id: int, active_only: bool = False, tenant_id: Optional[int] = None) -> List[dict]:
        """R?cup?rer les cam?ras d'un site."""
        cameras = crud.get_cameras_by_site(db, site_id=site_id, active_only=active_only, tenant_id=tenant_id)
        return [CameraService._format_camera(cam) for cam in cameras]
    @staticmethod
    def create_camera(db: Session, camera_data: schemas.CameraCreate, owner_id: int, tenant_id: Optional[int] = None) -> dict:
        """Cr?er une nouvelle cam?ra"""
        normalized = camera_data
        resolved_rtsp = CameraService._resolve_rtsp_url_value(
            rtsp_url=camera_data.rtsp_url,
            ip_address=camera_data.ip_address,
            port=camera_data.port,
            username=getattr(camera_data, "username", None),
            password=getattr(camera_data, "password", None),
        )
        if resolved_rtsp and resolved_rtsp != camera_data.rtsp_url:
            normalized = camera_data.model_copy(update={"rtsp_url": resolved_rtsp})

        camera = crud.create_camera(db, normalized, owner_id, tenant_id=tenant_id)
        return CameraService._format_camera(camera)
    @staticmethod
    def update_camera(db: Session, camera_id: int, camera_update: schemas.CameraUpdate, tenant_id: Optional[int] = None) -> Optional[dict]:
        """Mettre ? jour une cam?ra"""
        existing = crud.get_camera_by_id(db, camera_id, tenant_id=tenant_id) if tenant_id is not None else crud.get_camera_by_id(db, camera_id)
        if not existing:
            return None

        will_enable = False
        if camera_update.is_enabled is True and not existing.is_enabled:
            will_enable = True
        if camera_update.streaming_enabled is True and not existing.streaming_enabled:
            will_enable = True

        if will_enable:
            test_payload = schemas.CameraTestConnectionRequest(
                rtsp_url=camera_update.rtsp_url,
                ip_address=camera_update.ip_address,
                port=camera_update.port,
            )
            result = CameraService.test_camera_connection(db, camera_id, test_payload, tenant_id=tenant_id)
            if result.get("status") != "connected":
                raise ValueError("Camera connection failed. Test RTSP connectivity before enabling.")

        update_payload = camera_update
        normalized_password = camera_update.password
        if isinstance(normalized_password, str) and not normalized_password.strip():
            update_payload = update_payload.model_copy(update={"password": None})
        effective_rtsp = update_payload.rtsp_url if update_payload.rtsp_url is not None else existing.rtsp_url
        effective_ip = update_payload.ip_address if update_payload.ip_address is not None else existing.ip_address
        effective_port = update_payload.port if update_payload.port is not None else existing.port
        effective_user = update_payload.username if update_payload.username is not None else existing.username
        effective_pass = update_payload.password if update_payload.password is not None else existing.password

        resolved_rtsp = CameraService._resolve_rtsp_url_value(
            rtsp_url=effective_rtsp,
            ip_address=effective_ip,
            port=effective_port,
            username=effective_user,
            password=effective_pass,
        )
        if resolved_rtsp and resolved_rtsp != effective_rtsp:
            update_payload = update_payload.model_copy(update={"rtsp_url": resolved_rtsp})

        camera = crud.update_camera(db, camera_id, update_payload)
        if not camera:
            return None
        return CameraService._format_camera(camera)
    @staticmethod
    def delete_camera(db: Session, camera_id: int, tenant_id: Optional[int] = None) -> bool:
        """Supprimer une cam?ra"""
        existing = crud.get_camera_by_id(db, camera_id, tenant_id=tenant_id) if tenant_id is not None else crud.get_camera_by_id(db, camera_id)
        if not existing:
            return False
        return crud.delete_camera(db, camera_id)
    @staticmethod
    def update_camera_activity(db: Session, camera_id: int, tenant_id: Optional[int] = None) -> Optional[dict]:
        """Mettre ? jour l'activit? de la cam?ra"""
        existing = crud.get_camera_by_id(db, camera_id, tenant_id=tenant_id) if tenant_id is not None else crud.get_camera_by_id(db, camera_id)
        if not existing:
            return None
        camera = crud.update_camera_activity(db, camera_id)
        if not camera:
            return None
        return CameraService._format_camera(camera)
    @staticmethod
    def test_camera_connection(
        db: Session,
        camera_id: int,
        test_data: schemas.CameraTestConnectionRequest,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Tester la connexion ? une cam?ra
        Utilise les donn?es fournies ou celles de la cam?ra existante
        """
        camera = crud.get_camera_by_id(db, camera_id, tenant_id=tenant_id) if tenant_id is not None else crud.get_camera_by_id(db, camera_id)
        if not camera:
            return {
                "status": "error",
                "message": "Camera not found",
                "latency_ms": None,
                "camera_info": None,
            }

        ip_address = test_data.ip_address or camera.ip_address
        port = test_data.port or camera.port or 554
        username = test_data.username if test_data.username is not None else camera.username
        password = test_data.password if test_data.password is not None else camera.password

        fields_set = getattr(test_data, "model_fields_set", set()) or set()
        base_rtsp = test_data.rtsp_url or camera.rtsp_url
        candidates: List[str] = []
        if base_rtsp:
            injected = CameraService._inject_rtsp_auth(base_rtsp, username, password)
            if injected:
                candidates.append(injected)

        if not candidates and ip_address:
            candidates = CameraService._build_rtsp_candidates(
                ip_address=str(ip_address),
                port=int(port),
                rtsp_paths=CameraService._normalize_rtsp_paths(None),
                username=username,
                password=password,
            )
            if "port" not in fields_set:
                for alt_port in CameraService.DEFAULT_RTSP_PORTS:
                    if int(alt_port) == int(port):
                        continue
                    candidates.extend(
                        CameraService._build_rtsp_candidates(
                            ip_address=str(ip_address),
                            port=int(alt_port),
                            rtsp_paths=CameraService._normalize_rtsp_paths(None),
                            username=username,
                            password=password,
                        )
                    )
                candidates = CameraService._dedupe_rtsp_candidates(candidates)

        if not candidates:
            return {
                "status": "error",
                "message": "No RTSP URL or IP address configured",
                "latency_ms": None,
                "camera_info": None,
            }
        result = None
        if len(candidates) == 1:
            mediamtx_result = check_mediamtx_rtsp(candidates[0])
            if mediamtx_result.get("status") not in {"unknown", "error"}:
                result = mediamtx_result

        if result is None:
            last_result = None
            for url in candidates[:5]:
                last_result = CameraService._test_rtsp_connection(url, ip_address, int(port))
                if last_result.get("status") == "connected":
                    result = last_result
                    break
            if result is None and last_result is not None:
                result = last_result
            if result is None:
                result = {
                    "status": "error",
                    "message": "RTSP test failed",
                    "latency_ms": None,
                    "camera_info": {"rtsp_candidates": candidates},
                }

        if result.get("camera_info") is None:
            result["camera_info"] = {}
        if isinstance(result.get("camera_info"), dict):
            result["camera_info"].setdefault("rtsp_candidates", candidates)

        try:
            if (
                result.get("status") == "connected"
                and (not camera.rtsp_url or not str(camera.rtsp_url).strip())
                and isinstance(result.get("camera_info"), dict)
            ):
                working = result["camera_info"].get("rtsp_url")
                if working:
                    camera.rtsp_url = str(working)
            camera.connection_status = result.get("status")
            camera.last_connection_check = datetime.utcnow()
            if result.get("status") != "connected":
                camera.connection_error = result.get("message")
            else:
                camera.connection_error = None
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Failed to update connection status: {e}")

        return result
    @staticmethod
    def _test_rtsp_connection(rtsp_url: str, ip_address: Optional[str] = None, port: int = 554) -> Dict[str, Any]:
        """
        Tester la connexion RTSP/IP vers une caméra
        Retourne status, message, latency_ms, camera_info
        """
        start_time = time.time()

        try:
            # Test local camera sources first ("0", "1", "device://0", ...).
            local_source = CameraService._resolve_local_capture_source(rtsp_url)
            if local_source is not None:
                if not _HAS_CV2:
                    return {
                        "status": "error",
                        "message": "OpenCV is not available for local camera test",
                        "latency_ms": (time.time() - start_time) * 1000,
                        "camera_info": None,
                    }

                cap = None
                try:
                    cap = cv2.VideoCapture(local_source)
                    opened = bool(cap is not None and cap.isOpened())
                    latency_ms = (time.time() - start_time) * 1000

                    if not opened:
                        return {
                            "status": "disconnected",
                            "message": f"Failed to open local camera source {local_source}",
                            "latency_ms": round(latency_ms, 2),
                            "camera_info": None,
                        }

                    # Validate that at least one frame can be read.
                    ok, _frame = cap.read()
                    if not ok:
                        return {
                            "status": "degraded",
                            "message": f"Local camera {local_source} opened but frame read failed",
                            "latency_ms": round(latency_ms, 2),
                            "camera_info": {
                                "source_type": "local_device",
                                "device_index": local_source,
                                "rtsp_url": rtsp_url,
                                "response_time_ms": round(latency_ms, 2),
                            },
                        }

                    return {
                        "status": "connected",
                        "message": f"Successfully connected to local camera source {local_source}",
                        "latency_ms": round(latency_ms, 2),
                        "camera_info": {
                            "source_type": "local_device",
                            "device_index": local_source,
                            "rtsp_url": rtsp_url,
                            "response_time_ms": round(latency_ms, 2),
                        },
                    }
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Local camera test error: {str(e)}",
                        "latency_ms": (time.time() - start_time) * 1000,
                        "camera_info": None,
                    }
                finally:
                    try:
                        if cap is not None:
                            cap.release()
                    except Exception:
                        pass

            # Test 1 : Test de connectivité IP basique (ping)
            probe_error = None
            if _HAS_CV2 and rtsp_url:
                probe = StreamService.probe_rtsp_stream(rtsp_url, force_tcp=True)
                if probe.get("ok"):
                    latency_ms = probe.get("latency_ms")
                    return {
                        "status": "connected",
                        "message": "RTSP stream opened and frame read succeeded",
                        "latency_ms": latency_ms,
                        "camera_info": {
                            "rtsp_url": rtsp_url,
                            "response_time_ms": latency_ms,
                            "source_type": "rtsp",
                        },
                    }
                probe_error = str(probe.get("error") or "RTSP frame read failed")

            if ip_address:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    result = sock.connect_ex((ip_address, port))
                    sock.close()
                    
                    latency_ms = (time.time() - start_time) * 1000
                    
                    if result == 0:
                        return {
                            "status": "degraded" if probe_error else "connected",
                            "message": (
                                f"TCP connected to {ip_address}:{port}"
                                if not probe_error
                                else f"TCP connected but stream failed: {probe_error}"
                            ),
                            "latency_ms": round(latency_ms, 2),
                            "camera_info": {
                                "ip": ip_address,
                                "port": port,
                                "rtsp_url": rtsp_url,
                                "response_time_ms": round(latency_ms, 2)
                            }
                        }
                    else:
                        return {
                            "status": "disconnected",
                            "message": f"Failed to connect to {ip_address}:{port} - Connection refused",
                            "latency_ms": (time.time() - start_time) * 1000,
                            "camera_info": None
                        }
                except socket.timeout:
                    return {
                        "status": "timeout",
                        "message": f"Connection timeout to {ip_address}:{port} (5 seconds)",
                        "latency_ms": (time.time() - start_time) * 1000,
                        "camera_info": None
                    }
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Connection error: {str(e)}",
                        "latency_ms": (time.time() - start_time) * 1000,
                        "camera_info": None
                    }
            else:
                # Si pas d'IP, essayer de parser l'URL RTSP
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(rtsp_url)
                    host = parsed.hostname
                    port = parsed.port or 554
                    
                    if host:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(5)
                        result = sock.connect_ex((host, port))
                        sock.close()
                        
                        latency_ms = (time.time() - start_time) * 1000
                        
                        if result == 0:
                            return {
                                "status": "degraded" if probe_error else "connected",
                                "message": (
                                    f"TCP connected to {host}:{port}"
                                    if not probe_error
                                    else f"TCP connected but stream failed: {probe_error}"
                                ),
                                "latency_ms": round(latency_ms, 2),
                                "camera_info": {
                                    "ip": host,
                                    "port": port,
                                    "rtsp_url": rtsp_url,
                                    "response_time_ms": round(latency_ms, 2)
                                }
                            }
                        else:
                            return {
                                "status": "disconnected",
                                "message": f"Failed to connect to {host}:{port}",
                                "latency_ms": latency_ms,
                                "camera_info": None
                            }
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Failed to parse RTSP URL: {str(e)}",
                        "latency_ms": (time.time() - start_time) * 1000,
                        "camera_info": None
                    }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Unexpected error during connection test: {str(e)}",
                "latency_ms": (time.time() - start_time) * 1000,
                "camera_info": None
            }

    @staticmethod
    def _resolve_local_capture_source(rtsp_url: Optional[str]) -> Optional[int]:
        normalized = str(rtsp_url or "").strip()
        if not normalized:
            return None

        if normalized.isdigit():
            return int(normalized)

        lower = normalized.lower()
        prefixes = ("device://", "camera://", "webcam://")
        for prefix in prefixes:
            if lower.startswith(prefix):
                raw = normalized.split("://", 1)[1].strip()
                if raw.isdigit():
                    return int(raw)
        return None

    @staticmethod
    def _mask_rtsp_url(rtsp_url: Optional[str]) -> Optional[str]:
        if not rtsp_url:
            return rtsp_url
        try:
            parsed = urlparse(rtsp_url)
        except Exception:
            return rtsp_url
        if not parsed.username and not parsed.password:
            return rtsp_url
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=host))

    @staticmethod
    def _inject_rtsp_auth(rtsp_url: Optional[str], username: Optional[str], password: Optional[str]) -> Optional[str]:
        if not rtsp_url:
            return rtsp_url
        if not username:
            return rtsp_url
        try:
            parsed = urlparse(rtsp_url)
        except Exception:
            return rtsp_url
        if parsed.username:
            return rtsp_url
        host = parsed.hostname
        if not host:
            return rtsp_url
        userinfo = quote(str(username))
        if password:
            userinfo = f"{userinfo}:{quote(str(password))}"
        netloc = f"{userinfo}@{host}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))

    @staticmethod
    def _build_rtsp_url(
        ip_address: str,
        port: int,
        path: str,
        username: Optional[str],
        password: Optional[str],
    ) -> str:
        return CameraService._inject_rtsp_auth(f"rtsp://{ip_address}:{int(port)}{path}", username, password) or ""

    @staticmethod
    def _resolve_scan_ports(request: schemas.CameraDiscoveryRequest) -> List[int]:
        fields_set = getattr(request, "model_fields_set", set()) or set()
        raw_ports = None
        if "ports" in fields_set and request.ports:
            raw_ports = request.ports
        elif "port" in fields_set:
            raw_ports = [request.port]
        if raw_ports is None:
            raw_ports = list(CameraService.DEFAULT_SCAN_PORTS)
        ports: List[int] = []
        for value in raw_ports:
            try:
                port = int(value)
            except Exception:
                continue
            if 1 <= port <= 65535 and port not in ports:
                ports.append(port)
        return ports or list(CameraService.DEFAULT_SCAN_PORTS)

    @staticmethod
    def _resolve_onvif_ports(request: schemas.CameraDiscoveryRequest) -> List[int]:
        if request.onvif_ports:
            ports: List[int] = []
            for value in request.onvif_ports:
                try:
                    port = int(value)
                except Exception:
                    continue
                if 1 <= port <= 65535 and port not in ports:
                    ports.append(port)
            if ports:
                return ports
        return list(CameraService.DEFAULT_ONVIF_PORTS)

    @staticmethod
    def _dedupe_rtsp_candidates(candidates: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for url in candidates:
            key = str(url or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
        return ordered

    @staticmethod
    def _build_rtsp_candidates(
        *,
        ip_address: str,
        port: int,
        rtsp_paths: List[str],
        username: Optional[str],
        password: Optional[str],
    ) -> List[str]:
        candidates: List[str] = []
        for path in rtsp_paths:
            url = CameraService._build_rtsp_url(ip_address, port, path, username, password)
            if url:
                candidates.append(url)
        return CameraService._dedupe_rtsp_candidates(candidates)

    @staticmethod
    def _probe_rtsp_candidates(
        candidates: List[str],
        *,
        max_tests: int,
        timeout_ms: int,
    ) -> Dict[str, Any]:
        tried = 0
        for url in candidates:
            if tried >= max_tests:
                break
            tried += 1
            probe = StreamService.probe_rtsp_stream(
                url,
                open_timeout_sec=max(0.5, float(timeout_ms) / 1000.0),
                read_timeout_sec=max(0.5, float(timeout_ms) / 1000.0),
                force_tcp=True,
            )
            if probe.get("ok"):
                return {
                    "ok": True,
                    "rtsp_url": url,
                    "latency_ms": probe.get("latency_ms"),
                }
        return {"ok": False}

    @staticmethod
    def _resolve_rtsp_url_value(
        *,
        rtsp_url: Optional[str],
        ip_address: Optional[str],
        port: Optional[int],
        username: Optional[str],
        password: Optional[str],
        rtsp_paths: Optional[List[str]] = None,
    ) -> Optional[str]:
        if rtsp_url and str(rtsp_url).strip():
            return CameraService._inject_rtsp_auth(str(rtsp_url).strip(), username, password)
        if not ip_address:
            return None
        paths = CameraService._normalize_rtsp_paths(rtsp_paths)
        path = paths[0] if paths else "/stream"
        return CameraService._build_rtsp_url(
            ip_address=str(ip_address),
            port=int(port or 554),
            path=path,
            username=username,
            password=password,
        )

    @staticmethod
    def resolve_camera_stream_source(
        db: Session,
        camera_id: int,
        tenant_id: Optional[int] = None,
    ) -> Optional[str]:
        camera = crud.get_camera_by_id(db, camera_id, tenant_id=tenant_id) if tenant_id is not None else crud.get_camera_by_id(db, camera_id)
        if not camera:
            return None
        return CameraService._resolve_rtsp_url_value(
            rtsp_url=camera.rtsp_url,
            ip_address=camera.ip_address,
            port=camera.port,
            username=camera.username,
            password=camera.password,
        )

    @staticmethod
    def _get_camera_by_ip_port(
        db: Session,
        *,
        ip_address: str,
        port: int,
        tenant_id: Optional[int] = None,
    ) -> Optional[models.Camera]:
        query = db.query(models.Camera).filter(models.Camera.ip_address == str(ip_address).strip())
        if tenant_id is not None:
            query = query.filter(models.Camera.tenant_id == tenant_id)
        row = query.filter(models.Camera.port == int(port)).first()
        if row is not None:
            return row
        return query.order_by(models.Camera.id.asc()).first()

    @staticmethod
    def _infer_discovered_device_kind(candidate: Dict[str, Any]) -> str:
        onvif = candidate.get("onvif")
        device = onvif.get("device") if isinstance(onvif, dict) else {}
        hostname = str(device.get("hostname") or "").strip().lower()
        model = str(device.get("model") or "").strip().lower()
        manufacturer = str(device.get("manufacturer") or "").strip().lower()
        haystack = " ".join(value for value in [hostname, model, manufacturer] if value)
        if any(token in haystack for token in (" nvr", "nvr", "dvr", "xvr", "recorder")):
            return "nvr"
        return "camera"

    @staticmethod
    def _build_discovered_display_name(candidate: Dict[str, Any]) -> str:
        kind = CameraService._infer_discovered_device_kind(candidate)
        onvif = candidate.get("onvif")
        device = onvif.get("device") if isinstance(onvif, dict) else {}
        manufacturer = str(device.get("manufacturer") or "").strip()
        model = str(device.get("model") or "").strip()
        hostname = str(device.get("hostname") or "").strip()
        ip_address = str(candidate.get("ip_address") or "").strip()

        parts = [part for part in [manufacturer, model] if part]
        if parts:
            return " ".join(parts)
        if hostname:
            return hostname
        if kind == "nvr":
            return f"NVR {ip_address}".strip()
        return f"Camera {ip_address}".strip()

    @staticmethod
    def _build_discovered_location(candidate: Dict[str, Any], default_location: Optional[str] = None) -> str:
        if default_location and str(default_location).strip():
            return str(default_location).strip()
        kind = CameraService._infer_discovered_device_kind(candidate)
        return "NVR auto-detected" if kind == "nvr" else "Camera auto-detected"

    @staticmethod
    def _pick_discovered_rtsp_url(candidate: Dict[str, Any]) -> Optional[str]:
        working = str(candidate.get("rtsp_working_url") or "").strip()
        if working:
            return working

        raw_candidates = candidate.get("rtsp_candidates")
        if isinstance(raw_candidates, list):
            for item in raw_candidates:
                value = str(item or "").strip()
                if value:
                    return value

        ip_address = str(candidate.get("ip_address") or "").strip()
        if not ip_address:
            return None
        try:
            port = int(candidate.get("port") or 554)
        except Exception:
            port = 554
        return CameraService._resolve_rtsp_url_value(
            rtsp_url=None,
            ip_address=ip_address,
            port=port,
            username=candidate.get("username"),
            password=candidate.get("password"),
        )

    @staticmethod
    def _format_discovery_health_message(status: str, frame_loss_percent: Optional[float]) -> str:
        normalized = str(status or "").strip().lower()
        if normalized == "connected":
            if frame_loss_percent is not None and float(frame_loss_percent) > 0:
                return f"Live preview OK, frame loss {float(frame_loss_percent):.1f}%"
            return "Live preview OK"
        if normalized == "degraded":
            if frame_loss_percent is not None:
                return f"Stream reachable, but frame loss is {float(frame_loss_percent):.1f}%"
            return "Stream reachable, but preview quality is degraded"
        if normalized == "disconnected":
            return "Device detected, but Falcon could not read frames from the stream"
        return "Preview health unavailable"

    @staticmethod
    def analyze_discovered_cameras(
        db: Session,
        request: schemas.CameraDiscoveryAnalyzeRequest,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        analyzed: List[Dict[str, Any]] = []
        sample_frames = max(1, int(request.sample_frames or 4))
        seen: set[Tuple[str, int]] = set()

        for item in request.items:
            ip_address = str(item.ip_address or "").strip()
            if not ip_address:
                continue
            port = int(item.port or 554)
            key = (ip_address, port)
            if key in seen:
                continue
            seen.add(key)

            candidate = item.model_dump()
            candidate["ip_address"] = ip_address
            candidate["port"] = port
            rtsp_url = CameraService._pick_discovered_rtsp_url(candidate)
            existing = CameraService._get_camera_by_ip_port(
                db,
                ip_address=ip_address,
                port=port,
                tenant_id=tenant_id,
            )
            display_name = str(item.name or "").strip() or CameraService._build_discovered_display_name(candidate)
            device_kind = CameraService._infer_discovered_device_kind(candidate)

            preview_data_url = None
            latency_ms = None
            frame_loss_percent = None
            frames_read = 0
            frames_sampled = sample_frames
            status = "offline"
            message = "No RTSP candidate available for preview"

            if rtsp_url:
                probe = StreamService.inspect_rtsp_stream(
                    rtsp_url,
                    open_timeout_sec=max(0.5, 0.9 * float(os.getenv("CAMERA_OPEN_TIMEOUT_SEC", "4.0"))),
                    read_timeout_sec=max(0.5, 0.9 * float(os.getenv("CAMERA_READ_TIMEOUT_SEC", "4.0"))),
                    force_tcp=True,
                    sample_frames=sample_frames,
                    include_preview=bool(request.include_preview),
                )
                status = str(probe.get("status") or "offline").strip().lower()
                latency_ms = probe.get("latency_ms")
                frame_loss_percent = probe.get("frame_loss_percent")
                frames_read = int(probe.get("frames_read") or 0)
                frames_sampled = int(probe.get("frames_sampled") or sample_frames)
                if request.include_preview:
                    preview_jpeg = probe.get("preview_jpeg")
                    if isinstance(preview_jpeg, (bytes, bytearray)) and preview_jpeg:
                        encoded = base64.b64encode(bytes(preview_jpeg)).decode("ascii")
                        preview_data_url = f"data:image/jpeg;base64,{encoded}"
                if probe.get("ok"):
                    message = CameraService._format_discovery_health_message(status, frame_loss_percent)
                else:
                    message = str(probe.get("error") or "Preview probe failed")

            analyzed.append(
                {
                    "ip_address": ip_address,
                    "port": port,
                    "display_name": display_name,
                    "device_kind": device_kind,
                    "recommended_rtsp_url": rtsp_url,
                    "known_camera_id": existing.id if existing else None,
                    "known_camera_name": existing.name if existing else None,
                    "connection_status": status,
                    "connection_message": message,
                    "health_status": status,
                    "latency_ms": latency_ms,
                    "frame_loss_percent": frame_loss_percent,
                    "frames_read": frames_read,
                    "frames_sampled": frames_sampled,
                    "preview_data_url": preview_data_url,
                    "preview_available": bool(preview_data_url),
                    "preview_refreshed_at": datetime.utcnow().isoformat(),
                }
            )

        return {
            "count": len(analyzed),
            "items": analyzed,
            "message": "Discovery analysis completed",
        }

    @staticmethod
    def connect_discovered_cameras(
        db: Session,
        request: schemas.CameraDiscoveryConnectRequest,
        owner_id: int,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        created = 0
        updated = 0
        skipped = 0
        connected = 0
        degraded = 0
        results: List[Dict[str, Any]] = []
        seen: set[Tuple[str, int]] = set()

        for item in request.items:
            ip_address = str(item.ip_address or "").strip()
            if not ip_address:
                skipped += 1
                continue

            port = int(item.port or 554)
            dedupe_key = (ip_address, port)
            if dedupe_key in seen:
                skipped += 1
                continue
            seen.add(dedupe_key)

            candidate = item.model_dump()
            if candidate.get("rtsp_candidates") is None:
                candidate["rtsp_candidates"] = []
            candidate["ip_address"] = ip_address
            candidate["port"] = port

            existing = None
            if item.known_camera_id is not None:
                existing = (
                    crud.get_camera_by_id(db, int(item.known_camera_id), tenant_id=tenant_id)
                    if tenant_id is not None
                    else crud.get_camera_by_id(db, int(item.known_camera_id))
                )
            if existing is None:
                existing = CameraService._get_camera_by_ip_port(
                    db,
                    ip_address=ip_address,
                    port=port,
                    tenant_id=tenant_id,
                )
            desired_rtsp = CameraService._pick_discovered_rtsp_url(candidate)
            desired_name = str(item.name or "").strip() or CameraService._build_discovered_display_name(candidate)
            desired_location = str(item.location or "").strip() or CameraService._build_discovered_location(
                candidate,
                request.default_location,
            )
            desired_zone = str(item.zone_name or "").strip() or str(request.default_zone_name or "").strip() or None

            effective_streaming_enabled = (
                request.streaming_enabled if item.streaming_enabled is None else bool(item.streaming_enabled)
            )
            effective_ai_enabled = request.ai_enabled if item.ai_enabled is None else bool(item.ai_enabled)
            effective_motion_enabled = (
                request.motion_detection_enabled
                if item.motion_detection_enabled is None
                else bool(item.motion_detection_enabled)
            )
            effective_object_enabled = (
                request.object_detection_enabled
                if item.object_detection_enabled is None
                else bool(item.object_detection_enabled)
            )
            effective_sensitivity = (
                request.detection_sensitivity
                if item.detection_sensitivity is None
                else int(item.detection_sensitivity)
            )

            action = "skipped"
            db_camera: Optional[models.Camera] = None

            if existing is not None:
                if request.update_existing:
                    update_data: Dict[str, Any] = {}
                    if desired_rtsp and desired_rtsp != str(existing.rtsp_url or "").strip():
                        update_data["rtsp_url"] = desired_rtsp
                    if ip_address and ip_address != str(existing.ip_address or "").strip():
                        update_data["ip_address"] = ip_address
                    elif not str(existing.ip_address or "").strip():
                        update_data["ip_address"] = ip_address
                    if int(existing.port or 0) != port:
                        update_data["port"] = port
                    username = str(item.username or "").strip()
                    if username and username != str(existing.username or "").strip():
                        update_data["username"] = username
                    if item.password is not None and str(item.password) != str(existing.password or ""):
                        update_data["password"] = item.password
                    if desired_zone and not str(existing.zone_name or "").strip():
                        update_data["zone_name"] = desired_zone
                    if desired_location and not str(existing.location or "").strip():
                        update_data["location"] = desired_location
                    if not str(existing.name or "").strip():
                        update_data["name"] = desired_name
                    if bool(existing.streaming_enabled) != bool(effective_streaming_enabled):
                        update_data["streaming_enabled"] = effective_streaming_enabled
                    if bool(existing.motion_detection_enabled) != bool(effective_motion_enabled):
                        update_data["motion_detection_enabled"] = effective_motion_enabled
                    if bool(existing.object_detection_enabled) != bool(effective_object_enabled):
                        update_data["object_detection_enabled"] = effective_object_enabled
                    if bool(existing.ai_enabled) != bool(effective_ai_enabled):
                        update_data["ai_enabled"] = effective_ai_enabled
                    if int(existing.detection_sensitivity or 0) != int(effective_sensitivity):
                        update_data["detection_sensitivity"] = effective_sensitivity

                    if update_data:
                        crud.update_camera(db, existing.id, schemas.CameraUpdate(**update_data))
                        updated += 1
                        action = "updated"
                    else:
                        skipped += 1
                else:
                    skipped += 1
                db_camera = (
                    crud.get_camera_by_id(db, existing.id, tenant_id=tenant_id)
                    if tenant_id is not None
                    else crud.get_camera_by_id(db, existing.id)
                )
            else:
                created_camera = CameraService.create_camera(
                    db,
                    schemas.CameraCreate(
                        name=desired_name,
                        description=f"Auto-detected via Falcon network scan ({CameraService._infer_discovered_device_kind(candidate)})",
                        ip_address=ip_address,
                        port=port,
                        rtsp_url=desired_rtsp,
                        username=item.username,
                        password=item.password,
                        location=desired_location,
                        zone_name=desired_zone,
                        streaming_enabled=effective_streaming_enabled,
                        is_active=True,
                        motion_detection_enabled=effective_motion_enabled,
                        object_detection_enabled=effective_object_enabled,
                        detection_sensitivity=effective_sensitivity,
                        ai_enabled=effective_ai_enabled,
                    ),
                    owner_id,
                    tenant_id=tenant_id,
                )
                created += 1
                action = "created"
                db_camera = crud.get_camera_by_id(
                    db,
                    int(created_camera["id"]),
                    tenant_id=tenant_id,
                ) if tenant_id is not None else crud.get_camera_by_id(db, int(created_camera["id"]))

            if db_camera is None:
                results.append(
                    {
                        "action": action,
                        "ip_address": ip_address,
                        "port": port,
                        "connection_status": "error",
                        "message": "Camera could not be persisted",
                    }
                )
                degraded += 1
                continue

            connection_status = str(item.connection_status or "").strip().lower()
            if desired_rtsp and connection_status in {"connected", "online"}:
                db_camera.connection_status = "connected"
                db_camera.last_connection_check = datetime.utcnow()
                db_camera.connection_error = None
                db.commit()
                db.refresh(db_camera)
                connected += 1
            elif desired_rtsp and request.auto_test:
                probe = CameraService.test_camera_connection(
                    db,
                    int(db_camera.id),
                    schemas.CameraTestConnectionRequest(
                        rtsp_url=desired_rtsp,
                        ip_address=ip_address,
                        port=port,
                        username=item.username,
                        password=item.password,
                    ),
                    tenant_id=tenant_id,
                )
                if str(probe.get("status") or "").lower() in {"connected", "online"}:
                    connected += 1
                else:
                    degraded += 1
            else:
                current_status = str(db_camera.connection_status or "").strip().lower()
                if current_status in {"connected", "online"}:
                    connected += 1
                else:
                    degraded += 1

            results.append(
                {
                    "action": action,
                    "camera_id": int(db_camera.id),
                    "camera_name": db_camera.name,
                    "ip_address": ip_address,
                    "port": int(db_camera.port or port),
                    "connection_status": db_camera.connection_status,
                    "camera": CameraService._format_camera(db_camera),
                }
            )

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "connected": connected,
            "degraded": degraded,
            "cameras": results,
            "message": "Discovery connect completed",
        }

    @staticmethod
    def discover_cameras(
        db: Session,
        request: schemas.CameraDiscoveryRequest,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Discover camera candidates by scanning TCP on common camera ports."""
        started = time.time()
        hosts = CameraService._resolve_discovery_hosts(request)
        if not hosts:
            return {
                "scanned": 0,
                "found": 0,
                "cameras": [],
                "duration_ms": 0,
                "message": "No hosts to scan",
            }

        timeout_sec = max(0.1, float(request.timeout_ms) / 1000.0)
        ports = CameraService._resolve_scan_ports(request)
        rtsp_paths = CameraService._normalize_rtsp_paths(request.rtsp_paths)
        onvif_ports = CameraService._resolve_onvif_ports(request)
        username = request.username
        password = request.password
        probe_rtsp = bool(request.probe_rtsp)
        max_rtsp_tests = max(1, int(request.max_rtsp_tests or 4))

        existing = crud.get_all_cameras(db, skip=0, limit=5000, tenant_id=tenant_id)
        known_by_ip: Dict[str, Any] = {}
        known_by_ip_port: Dict[Tuple[str, int], Any] = {}
        for cam in existing:
            ip = (cam.ip_address or "").strip()
            if not ip:
                continue
            known_by_ip[ip] = cam
            known_by_ip_port[(ip, int(cam.port or 554))] = cam

        def probe_port(ip: str, port: int) -> Optional[Tuple[str, int, float]]:
            probe_start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_sec)
            try:
                code = sock.connect_ex((ip, port))
            except Exception:
                return None
            finally:
                sock.close()
            if code != 0:
                return None
            latency_ms = round((time.time() - probe_start) * 1000, 2)
            return (ip, port, latency_ms)

        open_by_ip: Dict[str, Dict[int, float]] = {}
        max_workers = min(128, max(8, len(hosts)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for ip in hosts:
                for port in ports:
                    futures[executor.submit(probe_port, ip, int(port))] = (ip, port)
            for future in as_completed(futures):
                result = future.result()
                if not result:
                    continue
                ip, port, latency_ms = result
                open_by_ip.setdefault(ip, {})[int(port)] = float(latency_ms)

        discovered: List[Dict[str, Any]] = []
        for ip, port_latencies in open_by_ip.items():
            open_ports = [p for p in ports if p in port_latencies]
            if not open_ports:
                continue
            rtsp_ports = [p for p in open_ports if p not in onvif_ports]
            primary_port = rtsp_ports[0] if rtsp_ports else open_ports[0]
            latency_ms = port_latencies.get(primary_port) or min(port_latencies.values())
            known = known_by_ip_port.get((ip, primary_port)) or known_by_ip.get(ip)

            rtsp_candidates = CameraService._build_rtsp_candidates(
                ip_address=ip,
                port=int(primary_port),
                rtsp_paths=rtsp_paths,
                username=username,
                password=password,
            )

            onvif_payload = None
            onvif_port = None
            if bool(request.onvif) and any(p in open_ports for p in onvif_ports):
                onvif_port = next((p for p in open_ports if p in onvif_ports), None)
                if onvif_port is not None:
                    onvif_payload = probe_onvif_device(
                        ip_address=ip,
                        port=int(onvif_port),
                        username=username,
                        password=password,
                        timeout_sec=min(4.0, timeout_sec * 2),
                    )
                    if onvif_payload and onvif_payload.get("streams"):
                        onvif_urls = []
                        for stream in onvif_payload.get("streams") or []:
                            uri = stream.get("rtsp_uri")
                            if uri:
                                onvif_urls.append(
                                    CameraService._inject_rtsp_auth(uri, username, password)
                                    or str(uri)
                                )
                        rtsp_candidates = CameraService._dedupe_rtsp_candidates(onvif_urls + rtsp_candidates)

            rtsp_working_url = None
            rtsp_probe = None
            if probe_rtsp and rtsp_candidates:
                rtsp_probe = CameraService._probe_rtsp_candidates(
                    rtsp_candidates,
                    max_tests=max_rtsp_tests,
                    timeout_ms=int(request.timeout_ms),
                )
                if rtsp_probe.get("ok"):
                    rtsp_working_url = rtsp_probe.get("rtsp_url")

            candidate: Dict[str, Any] = {
                "ip_address": ip,
                "port": int(primary_port),
                "open_ports": open_ports,
                "rtsp_ports": rtsp_ports,
                "onvif_port": onvif_port,
                "latency_ms": latency_ms,
                "rtsp_candidates": rtsp_candidates,
                "rtsp_working_url": rtsp_working_url,
                "onvif": onvif_payload,
                "known_camera_id": known.id if known else None,
                "known_camera_name": known.name if known else None,
            }
            device_kind = CameraService._infer_discovered_device_kind(candidate)
            display_name = CameraService._build_discovered_display_name(candidate)
            recommended_rtsp_url = rtsp_working_url or CameraService._pick_discovered_rtsp_url(candidate)
            connection_status = "connected" if rtsp_working_url else ("degraded" if rtsp_candidates else "offline")
            connection_message = (
                "RTSP stream verified"
                if rtsp_working_url
                else "Device detected, but Falcon could not verify a working RTSP stream automatically"
                if rtsp_candidates
                else "Open device found without a usable RTSP candidate"
            )

            discovered.append(
                {
                    **candidate,
                    "device_kind": device_kind,
                    "display_name": display_name,
                    "recommended_rtsp_url": recommended_rtsp_url,
                    "discovery_source": "onvif" if onvif_payload and onvif_payload.get("status") == "connected" else "rtsp_scan",
                    "connection_status": connection_status,
                    "connection_message": connection_message,
                }
            )

        discovered.sort(
            key=lambda row: (
                0 if row.get("known_camera_id") is not None else 1,
                float(row.get("latency_ms") or 999999),
                row.get("ip_address") or "",
            )
        )

        return {
            "scanned": len(hosts),
            "found": len(discovered),
            "cameras": discovered,
            "duration_ms": round((time.time() - started) * 1000, 2),
            "message": "Camera discovery completed",
        }

    @staticmethod
    def _resolve_discovery_hosts(request: schemas.CameraDiscoveryRequest) -> List[str]:
        max_hosts = max(1, min(int(request.max_hosts), 4096))
        hosts: List[str] = []

        subnet = (request.subnet or "").strip()
        start_ip = (request.start_ip or "").strip()
        end_ip = (request.end_ip or "").strip()

        if start_ip and end_ip:
            hosts = list(CameraService._expand_ip_range(start_ip, end_ip, max_hosts=max_hosts))
        elif subnet:
            hosts = list(CameraService._expand_subnet(subnet, max_hosts=max_hosts))
        else:
            local_ip = CameraService._detect_local_private_ipv4()
            if local_ip:
                default_subnet = str(ipaddress.ip_network(f"{local_ip}/24", strict=False))
                hosts = list(CameraService._expand_subnet(default_subnet, max_hosts=max_hosts))

        unique_hosts: List[str] = []
        seen = set()
        for ip in hosts:
            if ip in seen:
                continue
            seen.add(ip)
            unique_hosts.append(ip)
            if len(unique_hosts) >= max_hosts:
                break
        return unique_hosts

    @staticmethod
    def _expand_subnet(subnet: str, max_hosts: int) -> Iterable[str]:
        try:
            network = ipaddress.ip_network(subnet, strict=False)
        except Exception:
            return []

        hosts = []
        for host in network.hosts():
            if len(hosts) >= max_hosts:
                break
            hosts.append(str(host))
        return hosts

    @staticmethod
    def _expand_ip_range(start_ip: str, end_ip: str, max_hosts: int) -> Iterable[str]:
        try:
            start = int(ipaddress.IPv4Address(start_ip))
            end = int(ipaddress.IPv4Address(end_ip))
        except Exception:
            return []

        if end < start:
            start, end = end, start

        result = []
        for value in range(start, end + 1):
            if len(result) >= max_hosts:
                break
            result.append(str(ipaddress.IPv4Address(value)))
        return result

    @staticmethod
    def _detect_local_private_ipv4() -> Optional[str]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            sock.close()

            parsed = ipaddress.ip_address(ip)
            if parsed.version == 4 and parsed.is_private:
                return ip
        except Exception:
            pass
        return None

    @staticmethod
    def _normalize_rtsp_paths(paths: Optional[List[str]]) -> List[str]:
        raw_paths = paths or CameraService.DEFAULT_RTSP_PATHS
        normalized: List[str] = []
        for path in raw_paths:
            value = str(path or "").strip()
            if not value:
                continue
            if not value.startswith("/"):
                value = "/" + value
            normalized.append(value)
        return normalized or CameraService.DEFAULT_RTSP_PATHS
    
    @staticmethod
    def _format_camera(camera) -> dict:
        """Formater une caméra pour la réponse API"""
        return {
            "id": camera.id,
            "tenant_id": getattr(camera, "tenant_id", None),
            "site_id": camera.site_id,
            "zone_id": camera.zone_id,
            "name": camera.name,
            "description": camera.description,
            "rtsp_url": CameraService._mask_rtsp_url(camera.rtsp_url),
            "ip_address": camera.ip_address,
            "port": camera.port,
            "username": camera.username,
            "camera_type": camera.camera_type,
            "is_enabled": bool(getattr(camera, "is_enabled", True)),
            "location": camera.location,
            "zone_name": camera.zone_name,
            "status": "online" if camera.is_active else "offline",
            "connection_status": camera.connection_status or ("online" if camera.is_active else "offline"),
            "last_connection_check": camera.last_connection_check.isoformat() if camera.last_connection_check else None,
            "connection_error": camera.connection_error,
            "is_active": camera.is_active,
            "is_recording": camera.is_recording,
            "streaming_enabled": camera.streaming_enabled,
            "motion_detection_enabled": camera.motion_detection_enabled,
            "object_detection_enabled": camera.object_detection_enabled,
            "detection_sensitivity": camera.detection_sensitivity,
            "ai_enabled": camera.ai_enabled,
            "selection_role": getattr(camera, "selection_role", None),
            "selection_score": getattr(camera, "selection_score", None),
            "stream_validation_status": getattr(camera, "stream_validation_status", None),
            "stream_validation_message": getattr(camera, "stream_validation_message", None),
            "stream_codec": getattr(camera, "stream_codec", None),
            "stream_width": getattr(camera, "stream_width", None),
            "stream_height": getattr(camera, "stream_height", None),
            "stream_fps": getattr(camera, "stream_fps", None),
            "analysis_metadata": getattr(camera, "analysis_metadata", None),
            "last_snapshot_path": getattr(camera, "last_snapshot_path", None),
            "latitude": camera.latitude,
            "longitude": camera.longitude,
            "last_activity": camera.last_activity.isoformat() if camera.last_activity else None,
            "created_at": camera.created_at.isoformat() if camera.created_at else None,
            "updated_at": camera.updated_at.isoformat() if camera.updated_at else None
        }
