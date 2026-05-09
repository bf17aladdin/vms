from __future__ import annotations

import io
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from PIL import Image, ImageDraw
from vms.backend.core.config import settings

try:
    import cv2  # type: ignore
    import numpy as np

    _HAS_CV2 = True
except Exception:
    cv2 = None
    np = None
    _HAS_CV2 = False


@dataclass
class _CaptureState:
    source: str
    capture: object
    last_frame: Optional["np.ndarray"]
    last_read_at: float
    last_success_at: float
    last_reopen_at: float = 0.0
    last_error: Optional[str] = None
    failures: int = 0


class StreamService:
    """Camera stream helper for thumbnails and frame capture (RTSP-first)."""

    _lock = threading.Lock()
    _captures: Dict[str, _CaptureState] = {}
    _cache_ttl_sec = float(os.getenv("CAMERA_FRAME_CACHE_TTL_SEC", "0.35"))
    _reopen_after_failures = int(getattr(settings, "STREAM_RETRY", os.getenv("CAMERA_REOPEN_AFTER_FAILURES", "3")))
    _dead_stream_sec = float(getattr(settings, "CAMERA_STREAM_STALE_SEC", os.getenv("CAMERA_STREAM_STALE_SEC", "6.0")))
    _reopen_cooldown_sec = float(getattr(settings, "CAMERA_REOPEN_COOLDOWN_SEC", os.getenv("CAMERA_REOPEN_COOLDOWN_SEC", "1.0")))
    _open_timeout_sec = float(os.getenv("CAMERA_OPEN_TIMEOUT_SEC", "4.0"))
    _read_timeout_sec = float(os.getenv("CAMERA_READ_TIMEOUT_SEC", "4.0"))
    _force_rtsp_tcp = str(os.getenv("CAMERA_FORCE_RTSP_TCP", "true")).strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    _frame_max_width = int(os.getenv("CAMERA_FRAME_MAX_WIDTH", "0") or 0)
    _frame_max_height = int(os.getenv("CAMERA_FRAME_MAX_HEIGHT", "0") or 0)

    @classmethod
    def get_camera_frame(cls, camera_id: int, rtsp_url: Optional[str] = None) -> Optional["np.ndarray"]:
        """Return a BGR frame from RTSP source, or None if unavailable."""
        if not _HAS_CV2:
            return None

        source = cls._normalize_source(rtsp_url)
        if not source:
            return None

        now = time.time()
        with cls._lock:
            state = cls._captures.get(source)
            if state is None or not cls._is_capture_opened(state):
                state = cls._open_capture(source)
                if state is None:
                    return None
                cls._captures[source] = state

            if cls._is_stale(state, now):
                state = cls._attempt_reopen(source, state, now)
                cls._captures[source] = state

            if state.last_frame is not None and (now - state.last_read_at) <= cls._cache_ttl_sec:
                return state.last_frame.copy()

            frame = cls._read_frame(state)
            if frame is not None:
                frame = cls._resize_frame(frame)
                state.last_frame = frame
                state.last_read_at = now
                state.last_success_at = now
                state.failures = 0
                state.last_error = None
                return frame.copy()

            state.failures += 1
            state.last_error = "read_failed"
            if cls._should_reopen(state, now):
                state = cls._attempt_reopen(source, state, now)
                cls._captures[source] = state
                if state.last_frame is not None:
                    return state.last_frame.copy()

            if state.last_frame is not None:
                return state.last_frame.copy()

        return None

    @classmethod
    def get_camera_thumbnail(cls, camera_id: int, rtsp_url: Optional[str] = None) -> bytes:
        """Get camera thumbnail as JPEG bytes (RTSP frame or placeholder)."""
        frame = cls.get_camera_frame(camera_id=camera_id, rtsp_url=rtsp_url)
        if frame is None:
            return cls._create_placeholder_image(camera_id, reason="No RTSP frame")
        return cls._frame_to_jpeg(frame)

    @classmethod
    def frame_to_jpeg(cls, frame_bgr: "np.ndarray", quality: int = 85) -> bytes:
        return cls._frame_to_jpeg(frame_bgr, quality=quality)

    @classmethod
    def close_all(cls) -> None:
        with cls._lock:
            for state in list(cls._captures.values()):
                cls._release_capture(state)
            cls._captures.clear()

    @classmethod
    def release_camera_stream(cls, rtsp_url: Optional[str] = None) -> bool:
        """
        Release one cached camera capture by source.
        Returns True when a capture was found and released, False otherwise.
        """
        source = cls._normalize_source(rtsp_url)
        if not source:
            return False
        with cls._lock:
            state = cls._captures.pop(source, None)
            if state is None:
                return False
            cls._release_capture(state)
            return True

    @classmethod
    def active_stream_count(cls) -> int:
        with cls._lock:
            return len(cls._captures)

    @classmethod
    def convert_rtsp_to_mjpeg(cls, rtsp_url: str) -> bytes:
        return cls.get_camera_thumbnail(camera_id=0, rtsp_url=rtsp_url)

    @classmethod
    def _normalize_source(cls, rtsp_url: Optional[str]) -> Optional[str]:
        if not rtsp_url:
            return None
        source = rtsp_url.strip()
        return source or None

    @classmethod
    def _open_capture(cls, source: str) -> Optional[_CaptureState]:
        if not _HAS_CV2:
            return None

        open_timeout_ms = cls._seconds_to_ms(cls._open_timeout_sec, default_ms=4000)
        read_timeout_ms = cls._seconds_to_ms(cls._read_timeout_sec, default_ms=4000)

        capture = cls._create_capture_with_timeouts(
            source=source,
            open_timeout_ms=open_timeout_ms,
            read_timeout_ms=read_timeout_ms,
            force_tcp=cls._force_rtsp_tcp,
        )
        if capture is None:
            return None

        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        if not capture.isOpened():
            capture.release()
            return None

        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            return None
        frame = cls._resize_frame(frame)
        now = time.time()
        return _CaptureState(
            source=source,
            capture=capture,
            last_frame=frame,
            last_read_at=now,
            last_success_at=now,
            failures=0,
        )

    @classmethod
    def _create_capture_with_timeouts(
        cls,
        source: str,
        open_timeout_ms: int,
        read_timeout_ms: int,
        force_tcp: bool = False,
    ):
        capture_input = cls._resolve_capture_input(source)
        capture = None
        ffmpeg_api = getattr(cv2, "CAP_FFMPEG", None)
        open_prop = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
        read_prop = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
        if force_tcp and cls._is_rtsp_source(capture_input):
            cls._ensure_ffmpeg_tcp_options()

        if isinstance(capture_input, str) and ffmpeg_api is not None:
            try:
                if open_prop is not None and read_prop is not None:
                    capture = cv2.VideoCapture(
                        capture_input,
                        ffmpeg_api,
                        [int(open_prop), open_timeout_ms, int(read_prop), read_timeout_ms],
                    )
                else:
                    capture = cv2.VideoCapture(capture_input, ffmpeg_api)
            except Exception:
                capture = None

        if capture is None:
            try:
                capture = cv2.VideoCapture(capture_input)
            except Exception:
                return None

        for prop_name, value in (
            ("CAP_PROP_OPEN_TIMEOUT_MSEC", open_timeout_ms),
            ("CAP_PROP_READ_TIMEOUT_MSEC", read_timeout_ms),
        ):
            prop = getattr(cv2, prop_name, None)
            if prop is None:
                continue
            try:
                capture.set(prop, value)
            except Exception:
                pass

        return capture

    @classmethod
    def _resolve_capture_input(cls, source: str):
        """
        Resolve stream source into OpenCV capture input.

        Supported local camera formats:
        - "0", "1", ...
        - "device://0", "device://1", ...
        """
        normalized = str(source or "").strip()
        if not normalized:
            return source

        if normalized.isdigit():
            return int(normalized)

        if normalized.lower().startswith("device://"):
            index_raw = normalized.split("://", 1)[1].strip()
            if index_raw.isdigit():
                return int(index_raw)

        return source

    @classmethod
    def _seconds_to_ms(cls, value: float, default_ms: int) -> int:
        try:
            return max(250, int(float(value) * 1000))
        except Exception:
            return default_ms

    @classmethod
    def _is_rtsp_source(cls, source: object) -> bool:
        if not isinstance(source, str):
            return False
        return source.lower().startswith("rtsp://")

    @classmethod
    def _ensure_ffmpeg_tcp_options(cls) -> None:
        """Force TCP transport for RTSP when using FFmpeg backend."""
        existing = os.getenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "").strip()
        if existing:
            return
        # stimeout is in microseconds for FFmpeg.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000|max_delay;500000"

    @classmethod
    def _resize_frame(cls, frame_bgr: "np.ndarray") -> "np.ndarray":
        if not _HAS_CV2:
            return frame_bgr
        max_w = int(cls._frame_max_width or 0)
        max_h = int(cls._frame_max_height or 0)
        if max_w <= 0 and max_h <= 0:
            return frame_bgr
        try:
            height, width = frame_bgr.shape[:2]
        except Exception:
            return frame_bgr
        target_w = width
        target_h = height
        if max_w > 0 and width > max_w:
            ratio = max_w / float(width)
            target_w = max_w
            target_h = int(height * ratio)
        if max_h > 0 and target_h > max_h:
            ratio = max_h / float(target_h)
            target_h = max_h
            target_w = int(target_w * ratio)
        if target_w == width and target_h == height:
            return frame_bgr
        try:
            return cv2.resize(frame_bgr, (target_w, target_h))
        except Exception:
            return frame_bgr

    @classmethod
    def probe_rtsp_stream(
        cls,
        rtsp_url: str,
        *,
        open_timeout_sec: Optional[float] = None,
        read_timeout_sec: Optional[float] = None,
        force_tcp: Optional[bool] = None,
    ) -> Dict[str, object]:
        """Open RTSP stream once and read a frame to validate auth/URL."""
        if not _HAS_CV2:
            return {"ok": False, "error": "OpenCV not available", "latency_ms": None}
        source = cls._normalize_source(rtsp_url)
        if not source:
            return {"ok": False, "error": "Missing RTSP source", "latency_ms": None}

        start = time.time()
        open_timeout_ms = cls._seconds_to_ms(
            open_timeout_sec if open_timeout_sec is not None else cls._open_timeout_sec,
            default_ms=4000,
        )
        read_timeout_ms = cls._seconds_to_ms(
            read_timeout_sec if read_timeout_sec is not None else cls._read_timeout_sec,
            default_ms=4000,
        )
        capture = None
        try:
            capture = cls._create_capture_with_timeouts(
                source=source,
                open_timeout_ms=open_timeout_ms,
                read_timeout_ms=read_timeout_ms,
                force_tcp=cls._force_rtsp_tcp if force_tcp is None else bool(force_tcp),
            )
            if capture is None or not capture.isOpened():
                return {
                    "ok": False,
                    "error": "Failed to open RTSP stream",
                    "latency_ms": round((time.time() - start) * 1000, 2),
                }
            ok, frame = capture.read()
            if not ok or frame is None:
                return {
                    "ok": False,
                    "error": "Opened RTSP stream but frame read failed",
                    "latency_ms": round((time.time() - start) * 1000, 2),
                }
            return {
                "ok": True,
                "error": None,
                "latency_ms": round((time.time() - start) * 1000, 2),
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "latency_ms": round((time.time() - start) * 1000, 2),
            }
        finally:
            try:
                if capture is not None:
                    capture.release()
            except Exception:
                pass

    @classmethod
    def inspect_rtsp_stream(
        cls,
        rtsp_url: str,
        *,
        open_timeout_sec: Optional[float] = None,
        read_timeout_sec: Optional[float] = None,
        force_tcp: Optional[bool] = None,
        sample_frames: int = 4,
        include_preview: bool = False,
    ) -> Dict[str, object]:
        """Inspect a stream and estimate preview health from a short frame sample."""
        if not _HAS_CV2:
            return {
                "ok": False,
                "status": "error",
                "error": "OpenCV not available",
                "latency_ms": None,
                "frames_sampled": 0,
                "frames_read": 0,
                "frame_loss_percent": None,
                "preview_jpeg": None,
            }

        source = cls._normalize_source(rtsp_url)
        if not source:
            return {
                "ok": False,
                "status": "error",
                "error": "Missing RTSP source",
                "latency_ms": None,
                "frames_sampled": 0,
                "frames_read": 0,
                "frame_loss_percent": None,
                "preview_jpeg": None,
            }

        started = time.time()
        open_timeout_ms = cls._seconds_to_ms(
            open_timeout_sec if open_timeout_sec is not None else cls._open_timeout_sec,
            default_ms=4000,
        )
        read_timeout_ms = cls._seconds_to_ms(
            read_timeout_sec if read_timeout_sec is not None else cls._read_timeout_sec,
            default_ms=4000,
        )
        capture = None
        frames_sampled = max(1, int(sample_frames or 1))
        frames_read = 0
        preview_frame = None

        try:
            capture = cls._create_capture_with_timeouts(
                source=source,
                open_timeout_ms=open_timeout_ms,
                read_timeout_ms=read_timeout_ms,
                force_tcp=cls._force_rtsp_tcp if force_tcp is None else bool(force_tcp),
            )
            if capture is None or not capture.isOpened():
                return {
                    "ok": False,
                    "status": "disconnected",
                    "error": "Failed to open RTSP stream",
                    "latency_ms": round((time.time() - started) * 1000, 2),
                    "frames_sampled": frames_sampled,
                    "frames_read": 0,
                    "frame_loss_percent": 100.0,
                    "preview_jpeg": None,
                }

            for index in range(frames_sampled):
                ok, frame = capture.read()
                if not ok or frame is None:
                    continue
                frame = cls._resize_frame(frame)
                frames_read += 1
                if preview_frame is None or index == frames_sampled - 1:
                    preview_frame = frame

            latency_ms = round((time.time() - started) * 1000, 2)
            frame_loss_percent = round(((frames_sampled - frames_read) / float(frames_sampled)) * 100.0, 2)
            if frames_read <= 0 or preview_frame is None:
                return {
                    "ok": False,
                    "status": "disconnected",
                    "error": "Opened RTSP stream but frame read failed",
                    "latency_ms": latency_ms,
                    "frames_sampled": frames_sampled,
                    "frames_read": frames_read,
                    "frame_loss_percent": 100.0,
                    "preview_jpeg": None,
                }

            status = "connected" if frames_read >= frames_sampled else "degraded"
            preview_jpeg = cls._frame_to_jpeg(preview_frame) if include_preview else None
            return {
                "ok": True,
                "status": status,
                "error": None,
                "latency_ms": latency_ms,
                "frames_sampled": frames_sampled,
                "frames_read": frames_read,
                "frame_loss_percent": frame_loss_percent,
                "preview_jpeg": preview_jpeg,
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "error",
                "error": str(exc),
                "latency_ms": round((time.time() - started) * 1000, 2),
                "frames_sampled": frames_sampled,
                "frames_read": frames_read,
                "frame_loss_percent": None,
                "preview_jpeg": None,
            }
        finally:
            try:
                if capture is not None:
                    capture.release()
            except Exception:
                pass

    @classmethod
    def _is_capture_opened(cls, state: _CaptureState) -> bool:
        try:
            return bool(state.capture is not None and state.capture.isOpened())
        except Exception:
            return False

    @classmethod
    def _is_stale(cls, state: _CaptureState, now: float) -> bool:
        if cls._dead_stream_sec <= 0:
            return False
        try:
            return (now - float(state.last_success_at)) >= float(cls._dead_stream_sec)
        except Exception:
            return False

    @classmethod
    def _should_reopen(cls, state: _CaptureState, now: float) -> bool:
        if state.failures >= cls._reopen_after_failures:
            return True
        return cls._is_stale(state, now)

    @classmethod
    def _attempt_reopen(cls, source: str, state: _CaptureState, now: float) -> _CaptureState:
        if (now - float(state.last_reopen_at or 0.0)) < float(cls._reopen_cooldown_sec):
            return state
        cls._release_capture(state)
        state.capture = None
        state.last_reopen_at = now
        new_state = cls._open_capture(source)
        if new_state is None:
            state.last_error = "reopen_failed"
            return state
        return new_state

    @classmethod
    def _read_frame(cls, state: _CaptureState) -> Optional["np.ndarray"]:
        try:
            ok, frame = state.capture.read()
            if ok and frame is not None:
                return frame
        except Exception:
            return None
        return None

    @classmethod
    def _release_capture(cls, state: _CaptureState) -> None:
        try:
            if state.capture is not None:
                state.capture.release()
        except Exception:
            pass

    @classmethod
    def _frame_to_jpeg(cls, frame_bgr: "np.ndarray", quality: int = 85) -> bytes:
        if _HAS_CV2:
            ok, encoded = cv2.imencode(
                ".jpg",
                frame_bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), max(50, min(98, int(quality)))],
            )
            if ok:
                return encoded.tobytes()

        rgb = frame_bgr[:, :, ::-1]
        image = Image.fromarray(rgb)
        with io.BytesIO() as buffer:
            image.save(buffer, format="JPEG", quality=max(50, min(98, int(quality))))
            return buffer.getvalue()

    @classmethod
    def _create_placeholder_image(cls, camera_id: int, reason: str = "No stream available") -> bytes:
        width, height = 640, 360
        hue = random.randint(0, 360)
        color = cls._hsl_to_rgb(hue, 45, 30)

        img = Image.new("RGB", (width, height), color=color)
        draw = ImageDraw.Draw(img)

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        text = f"Camera {camera_id}\n{reason}\n{timestamp}"

        draw.rectangle([(12, 12), (width - 12, 110)], fill=(0, 0, 0), outline=(255, 255, 255))
        draw.text((24, 24), text, fill=(255, 255, 255))

        with io.BytesIO() as jpeg_buffer:
            img.save(jpeg_buffer, format="JPEG", quality=80)
            jpeg_buffer.seek(0)
            return jpeg_buffer.getvalue()

    @classmethod
    def _hsl_to_rgb(cls, h: int, s: int, l: int) -> tuple[int, int, int]:
        s = s / 100.0
        l = l / 100.0
        c = (1 - abs(2 * l - 1)) * s
        h_prime = h / 60.0
        x = c * (1 - abs((h_prime % 2) - 1))

        if h_prime < 1:
            r, g, b = c, x, 0
        elif h_prime < 2:
            r, g, b = x, c, 0
        elif h_prime < 3:
            r, g, b = 0, c, x
        elif h_prime < 4:
            r, g, b = 0, x, c
        elif h_prime < 5:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x

        m = l - c / 2
        return (
            max(0, min(255, int((r + m) * 255))),
            max(0, min(255, int((g + m) * 255))),
            max(0, min(255, int((b + m) * 255))),
        )
