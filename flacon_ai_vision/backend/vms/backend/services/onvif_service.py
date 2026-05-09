from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from onvif import ONVIFCamera  # type: ignore
    _HAS_ONVIF = True
except Exception:
    ONVIFCamera = None  # type: ignore
    _HAS_ONVIF = False


def _safe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _profile_to_dict(profile: Any) -> Dict[str, Any]:
    return {
        "token": getattr(profile, "token", None),
        "name": _safe_str(getattr(profile, "Name", None)),
    }


def _stream_setup_payload(token: str) -> Dict[str, Any]:
    return {
        "StreamSetup": {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
        "ProfileToken": token,
    }


def probe_onvif_device(
    *,
    ip_address: str,
    port: int,
    username: Optional[str] = None,
    password: Optional[str] = None,
    timeout_sec: float = 3.0,
) -> Dict[str, Any]:
    """Attempt ONVIF connection and return device info + media profiles."""
    started = time.time()
    if not _HAS_ONVIF:
        return {
            "status": "unavailable",
            "message": "ONVIF library not installed",
            "latency_ms": None,
            "device": None,
            "profiles": [],
            "streams": [],
        }

    try:
        cam = ONVIFCamera(
            ip_address,
            int(port),
            username or "",
            password or "",
            timeout=max(1, float(timeout_sec)),
        )
        dev_mgmt = cam.create_devicemgmt_service()
        media_service = cam.create_media_service()

        device_info = {}
        try:
            info = dev_mgmt.GetDeviceInformation()
            device_info = {
                "manufacturer": _safe_str(getattr(info, "Manufacturer", None)),
                "model": _safe_str(getattr(info, "Model", None)),
                "firmware": _safe_str(getattr(info, "FirmwareVersion", None)),
                "serial": _safe_str(getattr(info, "SerialNumber", None)),
                "hardware_id": _safe_str(getattr(info, "HardwareId", None)),
            }
        except Exception as exc:
            logger.debug("ONVIF device info failed for %s:%s: %s", ip_address, port, exc)

        try:
            hostname = dev_mgmt.GetHostname()
            if hostname is not None:
                device_info["hostname"] = _safe_str(getattr(hostname, "Name", None))
        except Exception:
            pass

        profiles: List[Dict[str, Any]] = []
        streams: List[Dict[str, Any]] = []
        try:
            raw_profiles = media_service.GetProfiles() or []
            for profile in raw_profiles:
                profile_dict = _profile_to_dict(profile)
                token = profile_dict.get("token")
                profiles.append(profile_dict)
                if not token:
                    continue
                try:
                    uri_resp = media_service.GetStreamUri(_stream_setup_payload(token))
                    uri = _safe_str(getattr(uri_resp, "Uri", None))
                except Exception:
                    uri = None
                streams.append(
                    {
                        "token": token,
                        "name": profile_dict.get("name"),
                        "rtsp_uri": uri,
                    }
                )
        except Exception as exc:
            logger.debug("ONVIF profile fetch failed for %s:%s: %s", ip_address, port, exc)

        latency_ms = round((time.time() - started) * 1000, 2)
        return {
            "status": "connected",
            "message": "ONVIF device detected",
            "latency_ms": latency_ms,
            "device": device_info,
            "profiles": profiles,
            "streams": streams,
        }
    except Exception as exc:
        latency_ms = round((time.time() - started) * 1000, 2)
        return {
            "status": "error",
            "message": f"ONVIF probe failed: {exc}",
            "latency_ms": latency_ms,
            "device": None,
            "profiles": [],
            "streams": [],
        }
