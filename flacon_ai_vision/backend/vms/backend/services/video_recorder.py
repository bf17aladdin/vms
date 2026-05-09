import atexit
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, Dict, List, Optional, Tuple

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    cv2 = None  # type: ignore
    _HAS_CV2 = False

try:
    from vms.backend.core.config import settings
    from vms.backend.core.database import SessionLocal
    from vms.backend.models import Camera
    from vms.backend.services.camera_service import CameraService
    from vms.backend.services.stream_service import StreamService
except Exception:
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.append(str(repo_root))
    from vms.backend.core.config import settings  # type: ignore
    from vms.backend.core.database import SessionLocal  # type: ignore
    from vms.backend.models import Camera  # type: ignore
    from vms.backend.services.camera_service import CameraService  # type: ignore
    from vms.backend.services.stream_service import StreamService  # type: ignore

logger = logging.getLogger(__name__)


def _to_int(value: Any, default: int, minimum: Optional[int] = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    if minimum is not None:
        return max(int(minimum), parsed)
    return parsed


def _to_float(value: Any, default: float, minimum: Optional[float] = None) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    if minimum is not None:
        return max(float(minimum), parsed)
    return parsed


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path.absolute())


def _to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


class RecordingStatus(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass
class _RecordingWorker:
    camera_id: int
    recording_id: str
    source: str
    local_path: Path
    fps: float
    quality: str
    stop_event: Event = field(default_factory=Event)
    pause_event: Event = field(default_factory=Event)
    thread: Optional[Thread] = None
    writer: Optional[object] = None
    frame_size: Optional[Tuple[int, int]] = None  # (width, height)
    frames_written: int = 0
    read_failures: int = 0
    last_error: Optional[str] = None


class VideoRecorder:
    """Real file recorder service (MP4 on disk + metadata)."""

    QUALITY_MAX_RESOLUTION = {
        "480p": (854, 480),
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "2k": (2560, 1440),
        "4k": (3840, 2160),
    }

    def __init__(self, storage_dir: str = "data/recordings"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.active_recordings: Dict[int, Dict] = {}
        self._workers: Dict[int, _RecordingWorker] = {}
        self._camera_operation_metrics: Dict[int, Dict[str, Any]] = {}
        self.recording_lock = Lock()
        self.metadata_file = self.storage_dir / "recordings_metadata.json"
        self.recording_fps = _to_float(os.getenv("VIDEO_RECORDING_FPS", "25"), default=25.0, minimum=1.0)
        self.default_fourcc = str(os.getenv("VIDEO_RECORDING_FOURCC", "mp4v")).strip() or "mp4v"
        self.retention_days = _to_int(
            getattr(settings, "VIDEO_RETENTION_DAYS", os.getenv("VIDEO_RETENTION_DAYS", "30")),
            default=30,
            minimum=0,
        )
        self.auto_purge_enabled = _to_bool(
            getattr(
                settings,
                "VIDEO_AUTO_PURGE_ENABLED",
                os.getenv("VIDEO_AUTO_PURGE_ENABLED", "true"),
            ),
            default=True,
        )
        self.purge_interval_seconds = _to_int(
            getattr(
                settings,
                "VIDEO_PURGE_INTERVAL_SECONDS",
                os.getenv("VIDEO_PURGE_INTERVAL_SECONDS", "3600"),
            ),
            default=3600,
            minimum=60,
        )
        self.orphan_file_grace_seconds = _to_int(
            getattr(
                settings,
                "VIDEO_ORPHAN_FILE_GRACE_SECONDS",
                os.getenv("VIDEO_ORPHAN_FILE_GRACE_SECONDS", "300"),
            ),
            default=300,
            minimum=5,
        )
        self.start_max_retries = _to_int(
            getattr(
                settings,
                "VIDEO_START_MAX_RETRIES",
                os.getenv("VIDEO_START_MAX_RETRIES", "3"),
            ),
            default=3,
            minimum=1,
        )
        self.start_retry_delay_seconds = _to_float(
            getattr(
                settings,
                "VIDEO_START_RETRY_DELAY_SECONDS",
                os.getenv("VIDEO_START_RETRY_DELAY_SECONDS", "0.35"),
            ),
            default=0.35,
            minimum=0.05,
        )
        self._maintenance_stop_event = Event()
        self._maintenance_thread: Optional[Thread] = None
        self._last_maintenance_at: Optional[str] = None
        self._last_maintenance_report: Dict[str, Any] = {}

        self.metadata = self._load_metadata()
        if self.auto_purge_enabled:
            self._maintenance_thread = Thread(
                target=self._maintenance_loop,
                name="video-recorder-maintenance",
                daemon=True,
            )
            self._maintenance_thread.start()

        atexit.register(self.shutdown)

    def _load_metadata(self) -> List[Dict]:
        if not self.metadata_file.exists():
            return []
        try:
            with open(self.metadata_file, "r", encoding="utf-8") as file_handle:
                raw = json.load(file_handle)
            if not isinstance(raw, list):
                return []
            normalized: List[Dict] = []
            for row in raw:
                if isinstance(row, dict):
                    normalized.append(self._normalize_metadata_row(row))
            return normalized
        except Exception as exc:
            logger.warning("Failed to load recording metadata: %s", exc)
            return []

    def _save_metadata(self):
        with open(self.metadata_file, "w", encoding="utf-8") as file_handle:
            json.dump(self.metadata, file_handle, indent=2)

    def shutdown(self) -> None:
        self._maintenance_stop_event.set()
        thread = self._maintenance_thread
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=2.0)
            except Exception:
                pass

    def _maintenance_loop(self) -> None:
        try:
            self.run_maintenance_cycle(trigger="startup")
        except Exception as exc:
            logger.warning("Video maintenance startup cycle failed: %s", exc)

        while not self._maintenance_stop_event.wait(float(self.purge_interval_seconds)):
            try:
                self.run_maintenance_cycle(trigger="scheduler")
            except Exception as exc:
                logger.warning("Video maintenance scheduler cycle failed: %s", exc)

    @staticmethod
    def _sanitize_source(source: str) -> str:
        value = str(source or "").strip()
        if "://" not in value or "@" not in value:
            return value
        scheme, tail = value.split("://", 1)
        auth_host = tail.split("@", 1)
        if len(auth_host) != 2:
            return value
        auth, host = auth_host
        if ":" in auth:
            user = auth.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return f"{scheme}://***@{host}"

    def _resolve_local_path(self, row_or_path: Any) -> Path:
        raw = ""
        if isinstance(row_or_path, dict):
            raw = str(row_or_path.get("filepath") or "").strip()
            if not raw:
                file_path = str(row_or_path.get("file_path") or "").strip()
                if file_path.startswith("/data/recordings/") or file_path.startswith("/media/recordings/"):
                    raw = str(self.storage_dir / Path(file_path).name)
                else:
                    raw = file_path
            if not raw:
                recording_id = str(row_or_path.get("recording_id") or "").strip()
                if recording_id:
                    raw = str(self.storage_dir / f"{recording_id}.mp4")
        else:
            raw = str(row_or_path or "").strip()

        if not raw:
            return self.storage_dir / "unknown.mp4"
        return Path(raw)

    def _update_camera_state(
        self,
        camera_id: int,
        *,
        is_recording: Optional[bool] = None,
        connection_status: Optional[str] = None,
        connection_error: Optional[str] = None,
        update_connection_error: bool = False,
    ) -> None:
        db = SessionLocal()
        try:
            row = db.query(Camera).filter(Camera.id == int(camera_id)).first()
            if row is None:
                return
            if is_recording is not None:
                row.is_recording = bool(is_recording)
            if connection_status is not None:
                row.connection_status = str(connection_status)
            row.last_connection_check = datetime.utcnow()
            if update_connection_error:
                row.connection_error = (
                    str(connection_error)[:500] if str(connection_error or "").strip() else None
                )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _classify_stream_failure(self, source: str) -> str:
        normalized = str(source or "").strip().lower()
        if normalized.startswith("rtsp://"):
            return "rtsp_stream_unavailable_or_timeout"
        if normalized.isdigit() or normalized.startswith("device://"):
            return "local_device_unavailable_or_busy"
        if not normalized:
            return "camera_source_missing"
        return "camera_stream_unavailable"

    def _ensure_camera_metric(self, camera_id: int) -> Dict[str, Any]:
        metric = self._camera_operation_metrics.get(int(camera_id))
        if metric is not None:
            return metric
        metric = {
            "camera_id": int(camera_id),
            "starts_ok": 0,
            "starts_failed": 0,
            "stops_ok": 0,
            "stops_failed": 0,
            "start_total_ms": 0.0,
            "stop_total_ms": 0.0,
            "last_start_ms": 0.0,
            "last_stop_ms": 0.0,
            "last_error": None,
            "last_started_at": None,
            "last_stopped_at": None,
            "frames_written_total": 0,
        }
        self._camera_operation_metrics[int(camera_id)] = metric
        return metric

    def _record_start_metric(
        self,
        camera_id: int,
        *,
        success: bool,
        latency_ms: float,
        error: Optional[str] = None,
    ) -> None:
        with self.recording_lock:
            metric = self._ensure_camera_metric(camera_id)
            metric["start_total_ms"] = float(metric.get("start_total_ms", 0.0)) + float(latency_ms)
            metric["last_start_ms"] = float(latency_ms)
            metric["last_started_at"] = datetime.now().isoformat()
            if success:
                metric["starts_ok"] = int(metric.get("starts_ok", 0)) + 1
                metric["last_error"] = None
            else:
                metric["starts_failed"] = int(metric.get("starts_failed", 0)) + 1
                metric["last_error"] = str(error or "start_failed")

    def _record_stop_metric(
        self,
        camera_id: int,
        *,
        success: bool,
        latency_ms: float,
        frames_written: int = 0,
        error: Optional[str] = None,
    ) -> None:
        with self.recording_lock:
            metric = self._ensure_camera_metric(camera_id)
            metric["stop_total_ms"] = float(metric.get("stop_total_ms", 0.0)) + float(latency_ms)
            metric["last_stop_ms"] = float(latency_ms)
            metric["last_stopped_at"] = datetime.now().isoformat()
            if success:
                metric["stops_ok"] = int(metric.get("stops_ok", 0)) + 1
                metric["frames_written_total"] = int(metric.get("frames_written_total", 0)) + int(
                    max(0, frames_written)
                )
                if not metric.get("last_error"):
                    metric["last_error"] = None
            else:
                metric["stops_failed"] = int(metric.get("stops_failed", 0)) + 1
                metric["last_error"] = str(error or "stop_failed")

    def _read_first_frame_with_retry(self, camera_id: int, source: str) -> Tuple[Optional[Any], List[str]]:
        notes: List[str] = []
        for attempt in range(1, int(self.start_max_retries) + 1):
            frame = StreamService.get_camera_frame(camera_id=int(camera_id), rtsp_url=source)
            if frame is not None:
                notes.append(f"attempt_{attempt}=ok")
                return frame, notes
            notes.append(f"attempt_{attempt}=no_frame")
            if attempt < int(self.start_max_retries):
                time.sleep(float(self.start_retry_delay_seconds))
        return None, notes

    def _extract_recording_datetime(self, row: Dict[str, Any]) -> Optional[datetime]:
        for key in ("end_time", "recorded_at", "start_time"):
            dt = _parse_datetime(row.get(key))
            if dt is not None:
                return _to_naive_utc(dt)
        return None

    def _normalize_metadata_row(self, row: Dict) -> Dict:
        normalized = dict(row)
        recording_id = str(normalized.get("recording_id") or "").strip()
        local_path = self._resolve_local_path(normalized)
        normalized["filepath"] = str(local_path).replace("\\", "/")
        existing_file_path = str(normalized.get("file_path") or "").strip().replace("\\", "/")
        if existing_file_path.lower().startswith("/data/recordings/"):
            normalized["file_path"] = f"/media/recordings/{Path(existing_file_path).name}"
        elif recording_id and not existing_file_path:
            normalized["file_path"] = self._build_web_file_path(recording_id)
        elif existing_file_path:
            normalized["file_path"] = existing_file_path
        if "file_size_mb" not in normalized:
            normalized["file_size_mb"] = 0
        if "frames_written" not in normalized:
            normalized["frames_written"] = 0
        return normalized

    @staticmethod
    def _build_web_file_path(recording_id: str) -> str:
        return f"/media/recordings/{recording_id}.mp4"

    @staticmethod
    def _coerce_even_size(width: int, height: int) -> Tuple[int, int]:
        w = max(2, int(width))
        h = max(2, int(height))
        if w % 2 == 1:
            w -= 1
        if h % 2 == 1:
            h -= 1
        return max(2, w), max(2, h)

    @staticmethod
    def _safe_release_writer(writer: Optional[object]) -> None:
        try:
            if writer is not None:
                writer.release()
        except Exception:
            pass

    def _set_camera_recording_flag(self, camera_id: int, is_recording: bool) -> None:
        self._update_camera_state(camera_id=int(camera_id), is_recording=bool(is_recording))

    def _resolve_camera_source(self, camera_id: int) -> Optional[str]:
        db = SessionLocal()
        try:
            row = db.query(Camera).filter(Camera.id == int(camera_id)).first()
            if row is None:
                return None

            rtsp = str(getattr(row, "rtsp_url", "") or "").strip()
            if rtsp:
                injected = CameraService._inject_rtsp_auth(rtsp, row.username, row.password)
                return injected or rtsp

            ip = str(getattr(row, "ip_address", "") or "").strip()
            if not ip:
                return None

            port = int(getattr(row, "port", 554) or 554)
            username = str(getattr(row, "username", "") or "").strip()
            password = str(getattr(row, "password", "") or "").strip()
            if username and password:
                return f"rtsp://{username}:{password}@{ip}:{port}/stream"
            if username:
                return f"rtsp://{username}@{ip}:{port}/stream"
            return f"rtsp://{ip}:{port}/stream"
        except Exception:
            return None
        finally:
            db.close()

    def _resize_for_quality(self, frame, quality: str):
        if not _HAS_CV2:
            return frame
        try:
            frame_h, frame_w = int(frame.shape[0]), int(frame.shape[1])
        except Exception:
            return frame

        max_resolution = self.QUALITY_MAX_RESOLUTION.get(str(quality or "").lower())
        if not max_resolution:
            return frame

        max_w, max_h = max_resolution
        scale = min(float(max_w) / float(frame_w), float(max_h) / float(frame_h), 1.0)
        if scale >= 0.999:
            return frame

        target_w, target_h = self._coerce_even_size(int(frame_w * scale), int(frame_h * scale))
        try:
            return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        except Exception:
            return frame

    def _build_video_writer(self, local_path: Path, fps: float, width: int, height: int):
        codecs = []
        candidate = str(self.default_fourcc or "").strip()
        if len(candidate) == 4:
            codecs.append(candidate)
        codecs.extend(["mp4v", "avc1", "H264"])

        seen = set()
        for codec in codecs:
            if codec in seen or len(codec) != 4:
                continue
            seen.add(codec)
            try:
                fourcc = cv2.VideoWriter_fourcc(*codec)
                writer = cv2.VideoWriter(str(local_path), fourcc, float(fps), (int(width), int(height)))
                if writer is not None and writer.isOpened():
                    logger.info("Recording codec selected for %s: %s", local_path.name, codec)
                    return writer
                self._safe_release_writer(writer)
            except Exception:
                continue
        return None

    def _ensure_writer(self, worker: _RecordingWorker, frame_width: int, frame_height: int):
        if worker.writer is not None:
            return worker.writer

        width, height = self._coerce_even_size(frame_width, frame_height)
        writer = self._build_video_writer(worker.local_path, worker.fps, width, height)
        if writer is None:
            worker.last_error = "video_writer_init_failed"
            return None

        worker.writer = writer
        worker.frame_size = (width, height)
        return writer

    def _record_loop(self, worker: _RecordingWorker, seed_frame) -> None:
        if not _HAS_CV2:
            worker.last_error = "opencv_unavailable"
            return

        frame_interval = 1.0 / max(worker.fps, 1.0)
        next_tick = time.perf_counter()
        pending_frame = seed_frame

        try:
            while not worker.stop_event.is_set():
                if worker.pause_event.is_set():
                    next_tick = time.perf_counter() + frame_interval
                    worker.stop_event.wait(0.1)
                    continue

                now = time.perf_counter()
                if now < next_tick:
                    worker.stop_event.wait(next_tick - now)
                    continue
                next_tick = max(next_tick + frame_interval, now)

                frame = pending_frame
                pending_frame = None
                if frame is None:
                    frame = StreamService.get_camera_frame(camera_id=worker.camera_id, rtsp_url=worker.source)
                if frame is None:
                    worker.last_error = "no_frame_from_stream"
                    worker.read_failures += 1
                    if worker.read_failures in {10, 30, 60}:
                        logger.warning(
                            "Recording stream degraded camera=%s recording_id=%s read_failures=%s source=%s",
                            worker.camera_id,
                            worker.recording_id,
                            worker.read_failures,
                            self._sanitize_source(worker.source),
                        )
                    continue
                worker.read_failures = 0

                frame = self._resize_for_quality(frame, worker.quality)
                try:
                    frame_h, frame_w = int(frame.shape[0]), int(frame.shape[1])
                except Exception:
                    worker.last_error = "invalid_frame_shape"
                    continue

                writer = self._ensure_writer(worker, frame_w, frame_h)
                if writer is None:
                    worker.stop_event.wait(0.2)
                    continue

                if worker.frame_size is not None and (frame_w, frame_h) != worker.frame_size:
                    try:
                        frame = cv2.resize(frame, worker.frame_size, interpolation=cv2.INTER_LINEAR)
                    except Exception:
                        worker.last_error = "frame_resize_failed"
                        continue

                try:
                    writer.write(frame)
                    worker.frames_written += 1
                except Exception as exc:
                    worker.last_error = f"frame_write_failed: {exc}"
                    continue

                with self.recording_lock:
                    active = self.active_recordings.get(worker.camera_id)
                    if active is None:
                        continue
                    active["frames_written"] = int(worker.frames_written)
                    active["read_failures"] = int(worker.read_failures)
                    start_time_raw = str(active.get("start_time") or "")
                    if start_time_raw:
                        started = _parse_datetime(start_time_raw)
                        if started is not None:
                            active["duration_seconds"] = max(
                                0.0, (datetime.now() - started).total_seconds()
                            )
                            elapsed = max(0.001, float(active["duration_seconds"]))
                            active["fps_avg"] = round(float(worker.frames_written) / elapsed, 3)
                    if worker.local_path.exists():
                        active["file_size_mb"] = round(
                            worker.local_path.stat().st_size / (1024 * 1024), 4
                        )
        finally:
            self._safe_release_writer(worker.writer)
            worker.writer = None

    def start_recording(
        self,
        camera_id: int,
        camera_name: str,
        zone_id: Optional[int] = None,
        quality: str = "1080p",
    ) -> Dict:
        operation_started = time.perf_counter()
        with self.recording_lock:
            if camera_id in self.active_recordings:
                return {"status": "error", "message": "Already recording"}

        if not _HAS_CV2:
            latency_ms = (time.perf_counter() - operation_started) * 1000.0
            self._record_start_metric(
                camera_id,
                success=False,
                latency_ms=latency_ms,
                error="opencv_unavailable",
            )
            return {
                "status": "error",
                "message": "OpenCV is required for MP4 recording but is not available",
            }

        source = self._resolve_camera_source(camera_id)
        if not source:
            latency_ms = (time.perf_counter() - operation_started) * 1000.0
            self._record_start_metric(
                camera_id,
                success=False,
                latency_ms=latency_ms,
                error="camera_source_missing",
            )
            self._update_camera_state(
                int(camera_id),
                is_recording=False,
                connection_status="error",
                connection_error="camera_source_missing",
                update_connection_error=True,
            )
            return {
                "status": "error",
                "message": "No camera stream source configured (rtsp_url/ip missing)",
            }

        first_frame, retry_notes = self._read_first_frame_with_retry(camera_id=int(camera_id), source=source)
        if first_frame is None:
            latency_ms = (time.perf_counter() - operation_started) * 1000.0
            reason = self._classify_stream_failure(source)
            message = (
                f"Unable to read frames from camera stream after {self.start_max_retries} attempts "
                f"(reason: {reason})"
            )
            self._record_start_metric(
                camera_id,
                success=False,
                latency_ms=latency_ms,
                error=reason,
            )
            self._update_camera_state(
                int(camera_id),
                is_recording=False,
                connection_status="disconnected",
                connection_error=message,
                update_connection_error=True,
            )
            logger.warning(
                "Recording start failed camera=%s source=%s retries=%s details=%s",
                camera_id,
                self._sanitize_source(source),
                self.start_max_retries,
                "; ".join(retry_notes),
            )
            return {
                "status": "error",
                "message": message,
                "error_type": reason,
                "attempts": int(self.start_max_retries),
            }

        timestamp = datetime.now()
        recording_id = f"cam_{camera_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
        filepath = self.storage_dir / f"{recording_id}.mp4"
        web_file_path = self._build_web_file_path(recording_id)

        recording_info = {
            "recording_id": recording_id,
            "camera_id": int(camera_id),
            "camera_name": str(camera_name),
            "zone_id": zone_id,
            "quality": str(quality or "1080p"),
            "status": RecordingStatus.RECORDING.value,
            "start_time": timestamp.isoformat(),
            "end_time": None,
            "duration_seconds": 0.0,
            "filepath": str(filepath).replace("\\", "/"),
            "file_path": web_file_path,
            "file_size_mb": 0.0,
            "frames_written": 0,
            "read_failures": 0,
            "fps_avg": 0.0,
        }

        worker = _RecordingWorker(
            camera_id=int(camera_id),
            recording_id=recording_id,
            source=source,
            local_path=filepath,
            fps=self.recording_fps,
            quality=str(quality or "1080p"),
        )
        worker.thread = Thread(
            target=self._record_loop,
            args=(worker, first_frame),
            name=f"video-recorder-cam-{camera_id}",
            daemon=True,
        )

        with self.recording_lock:
            self.active_recordings[int(camera_id)] = recording_info
            self._workers[int(camera_id)] = worker
            worker.thread.start()

        latency_ms = (time.perf_counter() - operation_started) * 1000.0
        self._record_start_metric(camera_id, success=True, latency_ms=latency_ms)
        self._update_camera_state(
            int(camera_id),
            is_recording=True,
            connection_status="connected",
            connection_error=None,
            update_connection_error=True,
        )
        logger.info(
            "Recording started: %s (camera %s source=%s latency_ms=%.2f)",
            recording_id,
            camera_id,
            self._sanitize_source(source),
            latency_ms,
        )

        return {
            "status": "success",
            "recording_id": recording_id,
            "camera_id": int(camera_id),
            "start_time": timestamp.isoformat(),
            "file_path": web_file_path,
            "start_latency_ms": round(latency_ms, 2),
        }

    def stop_recording(self, camera_id: int) -> Dict:
        operation_started = time.perf_counter()
        with self.recording_lock:
            recording = self.active_recordings.get(int(camera_id))
            worker = self._workers.get(int(camera_id))
            if recording is None:
                latency_ms = (time.perf_counter() - operation_started) * 1000.0
                self._record_stop_metric(
                    camera_id,
                    success=False,
                    latency_ms=latency_ms,
                    error="no_active_recording",
                )
                return {"status": "error", "message": "No active recording"}
            recording["end_time"] = datetime.now().isoformat()
            if worker is not None:
                worker.stop_event.set()

        if worker is not None and worker.thread is not None:
            worker.thread.join(timeout=8.0)

        with self.recording_lock:
            recording = self.active_recordings.pop(int(camera_id), recording)
            self._workers.pop(int(camera_id), None)

            start_raw = str(recording.get("start_time") or "")
            end_raw = str(recording.get("end_time") or datetime.now().isoformat())
            duration_seconds = 0.0
            started_at = _parse_datetime(start_raw)
            ended_at = _parse_datetime(end_raw)
            if started_at is not None and ended_at is not None:
                duration_seconds = max(0.0, (ended_at - started_at).total_seconds())

            recording["duration_seconds"] = duration_seconds
            recording["status"] = RecordingStatus.STOPPED.value

            local_path = self._resolve_local_path(recording)
            file_size_bytes = 0
            if local_path.exists():
                try:
                    file_size_bytes = int(local_path.stat().st_size)
                except Exception:
                    file_size_bytes = 0
            recording["file_size_mb"] = round(file_size_bytes / (1024 * 1024), 4)
            recording["file_size_bytes"] = file_size_bytes
            if worker is not None:
                recording["frames_written"] = int(worker.frames_written)
                recording["read_failures"] = int(worker.read_failures)
                recording["fps_avg"] = round(
                    float(worker.frames_written) / max(0.001, float(duration_seconds)),
                    3,
                )
                if worker.last_error:
                    recording["last_error"] = worker.last_error

            if file_size_bytes <= 0 or int(recording.get("frames_written") or 0) <= 0:
                recording["status"] = "failed"
                if not recording.get("last_error"):
                    recording["last_error"] = "no_frames_written"

            existing_file_path = str(recording.get("file_path") or "").strip().replace("\\", "/")
            if existing_file_path.lower().startswith("/data/recordings/"):
                recording["file_path"] = f"/media/recordings/{Path(existing_file_path).name}"
            else:
                recording["file_path"] = str(
                    existing_file_path
                    or self._build_web_file_path(str(recording.get("recording_id") or ""))
                )
            recording["filepath"] = str(local_path).replace("\\", "/")

            self.metadata.append(recording)
            self._save_metadata()

        latency_ms = (time.perf_counter() - operation_started) * 1000.0
        frames_written = int(recording.get("frames_written") or 0)
        self._record_stop_metric(
            camera_id,
            success=True,
            latency_ms=latency_ms,
            frames_written=frames_written,
        )
        if str(recording.get("status")) == "failed":
            self._update_camera_state(
                int(camera_id),
                is_recording=False,
                connection_status="error",
                connection_error=str(recording.get("last_error") or "recording_failed"),
                update_connection_error=True,
            )
        else:
            self._update_camera_state(
                int(camera_id),
                is_recording=False,
                connection_status="connected",
                connection_error=None,
                update_connection_error=True,
            )
        logger.info(
            "Recording stopped: %s camera=%s duration=%.2fs frames=%s file_size_mb=%.3f stop_ms=%.2f",
            recording.get("recording_id"),
            camera_id,
            float(recording.get("duration_seconds") or 0.0),
            frames_written,
            float(recording.get("file_size_mb") or 0.0),
            latency_ms,
        )
        return {
            "status": "success",
            "recording_id": recording.get("recording_id"),
            "duration_seconds": recording.get("duration_seconds", 0.0),
            "file_path": recording.get("file_path"),
            "recording_status": recording.get("status"),
            "stop_latency_ms": round(latency_ms, 2),
        }

    def pause_recording(self, camera_id: int) -> Dict:
        with self.recording_lock:
            worker = self._workers.get(int(camera_id))
            recording = self.active_recordings.get(int(camera_id))
            if worker is None or recording is None:
                return {"status": "error", "message": "No active recording"}
            worker.pause_event.set()
            recording["status"] = RecordingStatus.PAUSED.value
        logger.info("Recording paused for camera %s", camera_id)
        return {"status": "success", "message": "Recording paused"}

    def resume_recording(self, camera_id: int) -> Dict:
        with self.recording_lock:
            worker = self._workers.get(int(camera_id))
            recording = self.active_recordings.get(int(camera_id))
            if worker is None or recording is None:
                return {"status": "error", "message": "No active recording"}
            worker.pause_event.clear()
            recording["status"] = RecordingStatus.RECORDING.value
        logger.info("Recording resumed for camera %s", camera_id)
        return {"status": "success", "message": "Recording resumed"}

    def get_active_recordings(self) -> List[Dict]:
        with self.recording_lock:
            now = datetime.now()
            rows: List[Dict] = []
            for camera_id, row in self.active_recordings.items():
                item = dict(row)
                start_raw = str(item.get("start_time") or "")
                started = _parse_datetime(start_raw)
                if started is not None:
                    elapsed = max(0.001, (now - started).total_seconds())
                    item["duration_seconds"] = float(elapsed)
                else:
                    elapsed = 0.001
                worker = self._workers.get(camera_id)
                frames = int(item.get("frames_written") or 0)
                if worker is not None:
                    frames = int(worker.frames_written)
                    item["frames_written"] = frames
                    item["read_failures"] = int(worker.read_failures)
                    if worker.last_error:
                        item["last_error"] = worker.last_error
                item["fps_avg"] = round(float(frames) / max(0.001, elapsed), 3)
                local_path = self._resolve_local_path(item)
                if local_path.exists():
                    item["file_size_mb"] = round(local_path.stat().st_size / (1024 * 1024), 4)
                rows.append(item)
            return rows

    def get_recording_history(self, camera_id: Optional[int] = None, limit: int = 100) -> List[Dict]:
        with self.recording_lock:
            history = [
                self._normalize_metadata_row(dict(row))
                for row in self.metadata
                if isinstance(row, dict)
            ]
        if camera_id is not None and int(camera_id) > 0:
            history = [row for row in history if int(row.get("camera_id") or 0) == int(camera_id)]
        safe_limit = max(1, int(limit))
        return history[-safe_limit:]

    def get_recording_by_id(self, recording_id: str) -> Optional[Dict]:
        with self.recording_lock:
            for row in self.active_recordings.values():
                if str(row.get("recording_id")) == str(recording_id):
                    return dict(row)
            for row in self.metadata:
                if not isinstance(row, dict):
                    continue
                if str(row.get("recording_id")) == str(recording_id):
                    return self._normalize_metadata_row(dict(row))
        return None

    def run_maintenance_cycle(self, trigger: str = "manual") -> Dict[str, Any]:
        now = datetime.utcnow()
        retention_cutoff: Optional[datetime] = None
        if int(self.retention_days) > 0:
            retention_cutoff = now - timedelta(days=int(self.retention_days))

        deleted_old_files = 0
        deleted_orphan_files = 0
        removed_old_metadata = 0
        removed_orphan_metadata = 0
        orphan_file_candidates = 0
        errors: List[str] = []
        metadata_changed = False

        with self.recording_lock:
            active_recording_ids = {
                str(row.get("recording_id"))
                for row in self.active_recordings.values()
                if str(row.get("recording_id") or "").strip()
            }
            active_file_keys = {
                _path_key(worker.local_path)
                for worker in self._workers.values()
                if worker is not None
            }
            kept_metadata: List[Dict[str, Any]] = []
            metadata_file_keys: set[str] = set()

            for row in self.metadata:
                if not isinstance(row, dict):
                    metadata_changed = True
                    removed_orphan_metadata += 1
                    continue
                item = self._normalize_metadata_row(dict(row))
                recording_id = str(item.get("recording_id") or "").strip()
                local_path = self._resolve_local_path(item)
                local_key = _path_key(local_path)
                file_exists = local_path.exists()
                row_time = self._extract_recording_datetime(item)
                is_active_recording = recording_id in active_recording_ids
                is_old = (
                    retention_cutoff is not None
                    and row_time is not None
                    and row_time < retention_cutoff
                )

                if is_old and not is_active_recording:
                    if file_exists and local_key not in active_file_keys:
                        try:
                            local_path.unlink()
                            deleted_old_files += 1
                            file_exists = False
                        except Exception as exc:
                            errors.append(
                                f"failed_to_delete_old_file:{local_path.name}:{str(exc)}"
                            )
                    if not file_exists:
                        removed_old_metadata += 1
                        metadata_changed = True
                        continue

                if not file_exists and not is_active_recording:
                    removed_orphan_metadata += 1
                    metadata_changed = True
                    continue

                kept_metadata.append(item)
                if file_exists:
                    metadata_file_keys.add(local_key)

            grace_seconds = max(0, int(self.orphan_file_grace_seconds))
            for file_path in self.storage_dir.glob("*.mp4"):
                key = _path_key(file_path)
                if key in metadata_file_keys or key in active_file_keys:
                    continue
                orphan_file_candidates += 1
                if grace_seconds > 0:
                    try:
                        age_seconds = (now - datetime.utcfromtimestamp(file_path.stat().st_mtime)).total_seconds()
                    except Exception:
                        age_seconds = float(grace_seconds) + 1.0
                    if age_seconds < grace_seconds:
                        continue
                try:
                    file_path.unlink()
                    deleted_orphan_files += 1
                except Exception as exc:
                    errors.append(f"failed_to_delete_orphan_file:{file_path.name}:{str(exc)}")

            if metadata_changed:
                self.metadata = kept_metadata
                self._save_metadata()

        report: Dict[str, Any] = {
            "trigger": str(trigger),
            "retention_days": int(self.retention_days),
            "deleted_old_files": int(deleted_old_files),
            "deleted_orphan_files": int(deleted_orphan_files),
            "removed_old_metadata": int(removed_old_metadata),
            "removed_orphan_metadata": int(removed_orphan_metadata),
            "orphan_file_candidates": int(orphan_file_candidates),
            "errors": errors[:50],
            "errors_count": len(errors),
            "timestamp": now.isoformat(),
        }
        self._last_maintenance_at = report["timestamp"]
        self._last_maintenance_report = dict(report)
        logger.info(
            "Video maintenance finished trigger=%s old_files=%s orphan_files=%s removed_old_metadata=%s removed_orphan_metadata=%s errors=%s",
            trigger,
            deleted_old_files,
            deleted_orphan_files,
            removed_old_metadata,
            removed_orphan_metadata,
            len(errors),
        )
        return report

    def delete_recording(self, recording_id: str) -> Dict:
        with self.recording_lock:
            active_camera_id = None
            for cam_id, row in self.active_recordings.items():
                if str(row.get("recording_id")) == str(recording_id):
                    active_camera_id = int(cam_id)
                    break
        if active_camera_id is not None:
            self.stop_recording(active_camera_id)

        recording = self.get_recording_by_id(recording_id)
        if not recording:
            return {"status": "error", "message": "Recording not found"}

        file_deleted = False
        try:
            local_path = self._resolve_local_path(recording)
            if not local_path.exists():
                local_path = self.storage_dir / f"{recording_id}.mp4"
            if local_path.exists():
                local_path.unlink()
                file_deleted = True
        except Exception as exc:
            logger.warning("Could not delete recording file %s: %s", recording_id, exc)

        with self.recording_lock:
            self.metadata = [
                row
                for row in self.metadata
                if isinstance(row, dict) and str(row.get("recording_id")) != str(recording_id)
            ]
            self._save_metadata()

        logger.info("Recording deleted: %s", recording_id)
        return {
            "status": "success",
            "message": "Recording deleted",
            "file_deleted": file_deleted,
        }

    def get_storage_stats(self) -> Dict:
        with self.recording_lock:
            metadata_snapshot = [
                self._normalize_metadata_row(dict(row))
                for row in self.metadata
                if isinstance(row, dict)
            ]
            active_count = len(self.active_recordings)
            active_file_keys = {
                _path_key(worker.local_path)
                for worker in self._workers.values()
                if worker is not None
            }

        metadata_file_keys: set[str] = set()
        orphan_metadata = 0
        completed_recordings = 0
        failed_recordings = 0
        for row in metadata_snapshot:
            local_path = self._resolve_local_path(row)
            if local_path.exists():
                metadata_file_keys.add(_path_key(local_path))
            else:
                orphan_metadata += 1
            status = str(row.get("status") or "").strip().lower()
            if status in {"stopped", "completed"}:
                completed_recordings += 1
            elif status == "failed":
                failed_recordings += 1

        total_size_bytes = 0
        file_count = 0
        orphan_files = 0
        orphan_files_size_bytes = 0
        for file_path in self.storage_dir.glob("*.mp4"):
            try:
                size = int(file_path.stat().st_size)
            except Exception:
                continue
            file_count += 1
            total_size_bytes += size
            key = _path_key(file_path)
            if key not in metadata_file_keys and key not in active_file_keys:
                orphan_files += 1
                orphan_files_size_bytes += size

        return {
            "total_files": int(file_count),
            "total_size_bytes": int(total_size_bytes),
            "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
            "active_recordings": int(active_count),
            "metadata_entries": int(len(metadata_snapshot)),
            "completed_recordings": int(completed_recordings),
            "failed_recordings": int(failed_recordings),
            "orphan_metadata_entries": int(orphan_metadata),
            "orphan_files": int(orphan_files),
            "orphan_files_size_mb": round(orphan_files_size_bytes / (1024 * 1024), 3),
            "retention_days": int(self.retention_days),
            "auto_purge_enabled": bool(self.auto_purge_enabled),
            "purge_interval_seconds": int(self.purge_interval_seconds),
            "last_maintenance_at": self._last_maintenance_at,
            "last_maintenance_report": self._last_maintenance_report,
            "storage_path": str(self.storage_dir).replace("\\", "/"),
        }

    def get_recording_metrics(self) -> Dict[str, Any]:
        with self.recording_lock:
            active_snapshot: List[Dict[str, Any]] = []
            for camera_id, row in self.active_recordings.items():
                item = dict(row)
                worker = self._workers.get(camera_id)
                if worker is not None:
                    item["frames_written"] = int(worker.frames_written)
                    item["read_failures"] = int(worker.read_failures)
                active_snapshot.append(item)
            history_snapshot = [
                self._normalize_metadata_row(dict(row))
                for row in self.metadata
                if isinstance(row, dict)
            ]
            camera_metrics_snapshot = {
                int(camera_id): dict(values)
                for camera_id, values in self._camera_operation_metrics.items()
            }

        active_frames_total = 0
        active_fps_values: List[float] = []
        for row in active_snapshot:
            frames = int(row.get("frames_written") or 0)
            active_frames_total += max(0, frames)
            fps_avg = _to_float(row.get("fps_avg"), default=0.0, minimum=0.0)
            if fps_avg > 0:
                active_fps_values.append(fps_avg)

        history_frames_total = sum(max(0, int(row.get("frames_written") or 0)) for row in history_snapshot)
        history_duration_total = sum(
            max(0.0, float(row.get("duration_seconds") or 0.0)) for row in history_snapshot
        )

        start_attempts_total = 0
        start_failures_total = 0
        stop_attempts_total = 0
        camera_metrics: List[Dict[str, Any]] = []
        active_by_camera = {
            int(row.get("camera_id") or 0): row for row in active_snapshot if int(row.get("camera_id") or 0) > 0
        }
        for camera_id in sorted(camera_metrics_snapshot.keys()):
            metric = dict(camera_metrics_snapshot[camera_id])
            starts_ok = int(metric.get("starts_ok") or 0)
            starts_failed = int(metric.get("starts_failed") or 0)
            stops_ok = int(metric.get("stops_ok") or 0)
            stops_failed = int(metric.get("stops_failed") or 0)
            start_attempts = starts_ok + starts_failed
            stop_attempts = stops_ok + stops_failed
            start_attempts_total += start_attempts
            start_failures_total += starts_failed
            stop_attempts_total += stop_attempts
            start_total_ms = _to_float(metric.get("start_total_ms"), default=0.0, minimum=0.0)
            stop_total_ms = _to_float(metric.get("stop_total_ms"), default=0.0, minimum=0.0)

            active_row = active_by_camera.get(camera_id)
            metric["start_attempts"] = start_attempts
            metric["stop_attempts"] = stop_attempts
            metric["start_avg_ms"] = round(start_total_ms / max(1, start_attempts), 2) if start_attempts > 0 else 0.0
            metric["stop_avg_ms"] = round(stop_total_ms / max(1, stop_attempts), 2) if stop_attempts > 0 else 0.0
            metric["start_failure_rate"] = round(starts_failed / max(1, start_attempts), 4) if start_attempts > 0 else 0.0
            metric["is_recording"] = active_row is not None
            metric["active_fps_avg"] = (
                _to_float(active_row.get("fps_avg"), default=0.0, minimum=0.0) if active_row else 0.0
            )
            metric["active_read_failures"] = int(active_row.get("read_failures") or 0) if active_row else 0
            camera_metrics.append(metric)

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "active_recordings": len(active_snapshot),
            "history_recordings": len(history_snapshot),
            "cameras_tracked": len(camera_metrics),
            "frames_written_total": int(history_frames_total + active_frames_total),
            "frames_written_history_total": int(history_frames_total),
            "frames_written_active_total": int(active_frames_total),
            "history_duration_seconds": round(history_duration_total, 3),
            "active_fps_avg": round(sum(active_fps_values) / len(active_fps_values), 3) if active_fps_values else 0.0,
            "start_attempts_total": int(start_attempts_total),
            "start_failures_total": int(start_failures_total),
            "start_failure_rate": round(start_failures_total / max(1, start_attempts_total), 4)
            if start_attempts_total > 0
            else 0.0,
            "stop_attempts_total": int(stop_attempts_total),
            "camera_metrics": camera_metrics,
            "last_maintenance_at": self._last_maintenance_at,
        }


_recorder: Optional[VideoRecorder] = None


def get_video_recorder() -> VideoRecorder:
    global _recorder
    if _recorder is None:
        _recorder = VideoRecorder()
    return _recorder
