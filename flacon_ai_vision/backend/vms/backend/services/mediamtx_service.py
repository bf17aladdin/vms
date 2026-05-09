from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Dict, Optional
from urllib.parse import quote, urlparse


def _parse_rtsp_path(rtsp_url: str) -> Optional[str]:
    if not rtsp_url:
        return None
    try:
        parsed = urlparse(rtsp_url)
    except Exception:
        return None
    path = (parsed.path or "").lstrip("/")
    return path or None


def get_mediamtx_api_base() -> Optional[str]:
    raw = os.getenv("MEDIAMTX_API_BASE", "").strip()
    if not raw:
        return None
    return raw.rstrip("/")


def check_mediamtx_rtsp(rtsp_url: str, *, api_base: Optional[str] = None, timeout_sec: float = 3.0) -> Dict[str, object]:
    start = time.time()
    base = (api_base or get_mediamtx_api_base())
    if not base:
        return {
            "status": "unknown",
            "message": "MediaMTX API not configured",
            "latency_ms": None,
            "camera_info": None,
        }

    path = _parse_rtsp_path(rtsp_url)
    if not path:
        return {
            "status": "error",
            "message": "Unable to parse RTSP path",
            "latency_ms": round((time.time() - start) * 1000, 2),
            "camera_info": {"rtsp_url": rtsp_url},
        }

    url = f"{base}/v3/paths/get/{quote(path, safe='')}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        ready = bool(payload.get("ready"))
        status = "connected" if ready else "disconnected"
        message = "Stream ready in MediaMTX" if ready else "Stream not ready in MediaMTX"
        latency_ms = round((time.time() - start) * 1000, 2)
        return {
            "status": status,
            "message": message,
            "latency_ms": latency_ms,
            "camera_info": {
                "rtsp_url": rtsp_url,
                "path": path,
                "api_url": url,
                "ready": ready,
                "details": payload,
                "response_time_ms": latency_ms,
            },
        }
    except urllib.error.HTTPError as exc:
        latency_ms = round((time.time() - start) * 1000, 2)
        if exc.code == 404:
            return {
                "status": "disconnected",
                "message": "Stream not found in MediaMTX",
                "latency_ms": latency_ms,
                "camera_info": {"rtsp_url": rtsp_url, "path": path, "api_url": url},
            }
        return {
            "status": "error",
            "message": f"MediaMTX API error ({exc.code})",
            "latency_ms": latency_ms,
            "camera_info": {"rtsp_url": rtsp_url, "path": path, "api_url": url},
        }
    except Exception as exc:
        latency_ms = round((time.time() - start) * 1000, 2)
        return {
            "status": "error",
            "message": f"MediaMTX API request failed: {exc}",
            "latency_ms": latency_ms,
            "camera_info": {"rtsp_url": rtsp_url, "path": path, "api_url": url},
        }
