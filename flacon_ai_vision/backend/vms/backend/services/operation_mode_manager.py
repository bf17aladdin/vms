from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from sqlalchemy.orm import Session

from vms.backend.core.database import SessionLocal
from vms.backend.models import Camera
from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline
from vms.backend.services.stream_service import StreamService
from vms.backend.services.camera_service import CameraService
from vms.backend.services.vehicle_ai.vehicle_pipeline import VehicleRecognitionPipeline


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


ALLOWED_CAMERA_PROFILES = ("fixed_medium", "fixed_high", "ptz", "panoramic")
DEFAULT_CAMERA_PROFILE = "fixed_medium"


@dataclass(frozen=True, slots=True)
class CameraProfilePolicy:
    name: str
    min_sample_interval_ms: int
    max_sample_interval_ms: int
    default_sample_interval_ms: int
    min_face_max_faces: int
    max_face_max_faces: int
    default_face_max_faces: int


CAMERA_PROFILE_POLICIES: dict[str, CameraProfilePolicy] = {
    "fixed_medium": CameraProfilePolicy(
        name="fixed_medium",
        min_sample_interval_ms=180,
        max_sample_interval_ms=1200,
        default_sample_interval_ms=220,
        min_face_max_faces=4,
        max_face_max_faces=16,
        default_face_max_faces=10,
    ),
    "fixed_high": CameraProfilePolicy(
        name="fixed_high",
        min_sample_interval_ms=220,
        max_sample_interval_ms=1500,
        default_sample_interval_ms=300,
        min_face_max_faces=4,
        max_face_max_faces=12,
        default_face_max_faces=8,
    ),
    "ptz": CameraProfilePolicy(
        name="ptz",
        min_sample_interval_ms=260,
        max_sample_interval_ms=1800,
        default_sample_interval_ms=350,
        min_face_max_faces=2,
        max_face_max_faces=10,
        default_face_max_faces=6,
    ),
    "panoramic": CameraProfilePolicy(
        name="panoramic",
        min_sample_interval_ms=320,
        max_sample_interval_ms=2200,
        default_sample_interval_ms=420,
        min_face_max_faces=2,
        max_face_max_faces=8,
        default_face_max_faces=4,
    ),
}


def _normalize_profile_name(raw: Any, fallback: str = DEFAULT_CAMERA_PROFILE) -> str:
    candidate = str(raw or "").strip().lower()
    if candidate in CAMERA_PROFILE_POLICIES:
        return candidate
    return str(fallback)


def _normalize_profile_overrides(raw: Optional[Mapping[Any, Any]]) -> dict[int, str]:
    if not raw:
        return {}
    normalized: dict[int, str] = {}
    for key, value in raw.items():
        camera_id = _safe_int(key, 0)
        if camera_id <= 0:
            raise ValueError(f"Invalid camera profile override key '{key}' (must be a positive camera id)")
        profile = str(value or "").strip().lower()
        if profile not in CAMERA_PROFILE_POLICIES:
            allowed = ", ".join(ALLOWED_CAMERA_PROFILES)
            raise ValueError(
                f"Invalid camera profile '{value}' for camera #{camera_id}. Allowed profiles: {allowed}"
            )
        normalized[camera_id] = profile
    return normalized


def _infer_camera_profile(
    camera: Camera,
    *,
    default_profile: str,
    overrides: Mapping[int, str],
) -> str:
    camera_id = _safe_int(getattr(camera, "id", 0), 0)
    if camera_id in overrides:
        return overrides[camera_id]

    camera_type = str(getattr(camera, "camera_type", "") or "").strip().lower()
    text_bag = " ".join(
        [
            camera_type,
            str(getattr(camera, "name", "") or ""),
            str(getattr(camera, "description", "") or ""),
            str(getattr(camera, "location", "") or ""),
            str(getattr(camera, "zone_name", "") or ""),
        ]
    ).lower()

    if bool(getattr(camera, "pan_tilt_zoom_capable", False)) or "ptz" in camera_type:
        return "ptz"

    if any(token in text_bag for token in ("panoramic", "panorama", "fisheye", "360")):
        return "panoramic"

    if any(token in text_bag for token in ("4k", "2160", "1440", "1080", "fullhd", "high")):
        return "fixed_high"

    return _normalize_profile_name(default_profile)


@dataclass(slots=True)
class ProductionRuntimeConfig:
    camera_ids: Optional[list[int]] = None
    sample_interval_ms: int = 1000
    face_enabled: bool = True
    vehicle_enabled: bool = True
    persist_face: bool = True
    persist_vehicle: bool = True
    face_top_k: int = 5
    face_max_faces: int = 10
    vehicle_direction: str = "IN"
    vehicle_gate_id: Optional[str] = None
    zone_id: Optional[int] = None
    enforce_camera_profiles: bool = True
    strict_policy_validation: bool = True
    default_camera_profile: str = DEFAULT_CAMERA_PROFILE
    camera_profile_overrides: Optional[dict[int, str]] = None


@dataclass(slots=True)
class _CameraRuntimeState:
    camera_id: int
    camera_name: str
    source: str
    profile: str = DEFAULT_CAMERA_PROFILE
    sample_interval_ms: int = 1000
    face_max_faces: int = 10
    status: str = "starting"
    frames_processed: int = 0
    last_frame_at: Optional[str] = None
    last_error: Optional[str] = None
    read_errors: int = 0
    frame_width: int = 0
    frame_height: int = 0
    face_frames: int = 0
    face_latency_ms_total: float = 0.0
    face_latency_ms_max: float = 0.0
    vehicle_frames: int = 0
    vehicle_latency_ms_total: float = 0.0
    vehicle_latency_ms_max: float = 0.0
    face_last: Optional[dict[str, Any]] = None
    vehicle_last: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        face_avg = self.face_latency_ms_total / self.face_frames if self.face_frames > 0 else 0.0
        veh_avg = self.vehicle_latency_ms_total / self.vehicle_frames if self.vehicle_frames > 0 else 0.0
        policy = CAMERA_PROFILE_POLICIES.get(str(self.profile), CAMERA_PROFILE_POLICIES[DEFAULT_CAMERA_PROFILE])
        return {
            "camera_id": int(self.camera_id),
            "camera_name": str(self.camera_name),
            "profile": str(self.profile),
            "sample_interval_ms": int(self.sample_interval_ms),
            "face_max_faces": int(self.face_max_faces),
            "profile_policy": {
                "name": policy.name,
                "sample_interval_ms_min": int(policy.min_sample_interval_ms),
                "sample_interval_ms_max": int(policy.max_sample_interval_ms),
                "sample_interval_ms_default": int(policy.default_sample_interval_ms),
                "face_max_faces_min": int(policy.min_face_max_faces),
                "face_max_faces_max": int(policy.max_face_max_faces),
                "face_max_faces_default": int(policy.default_face_max_faces),
            },
            "status": str(self.status),
            "frames_processed": int(self.frames_processed),
            "last_frame_at": self.last_frame_at,
            "last_error": self.last_error,
            "read_errors": int(self.read_errors),
            "frame_width": int(self.frame_width),
            "frame_height": int(self.frame_height),
            "face": {
                "enabled": self.face_last is not None or self.face_frames > 0,
                "frames": int(self.face_frames),
                "latency_avg_ms": round(float(face_avg), 3),
                "latency_max_ms": round(float(self.face_latency_ms_max), 3),
                "last": self.face_last,
            },
            "vehicle": {
                "enabled": self.vehicle_last is not None or self.vehicle_frames > 0,
                "frames": int(self.vehicle_frames),
                "latency_avg_ms": round(float(veh_avg), 3),
                "latency_max_ms": round(float(self.vehicle_latency_ms_max), 3),
                "last": self.vehicle_last,
            },
        }


class ProductionLiveRuntime:
    """
    Runtime for real monitoring mode.

    It continuously pulls frames from configured cameras and runs:
    - multi-face recognition (FaceRecognitionPipeline)
    - vehicle recognition + plate type classification (VehicleRecognitionPipeline)
    """

    def __init__(self, *, session_factory: Callable[[], Session] = SessionLocal):
        self.session_factory = session_factory
        self._lock = threading.RLock()
        self._running = False
        self._started_at: Optional[str] = None
        self._stopped_at: Optional[str] = None
        self._config: Optional[ProductionRuntimeConfig] = None
        self._threads: dict[int, threading.Thread] = {}
        self._stop_events: dict[int, threading.Event] = {}
        self._states: dict[int, _CameraRuntimeState] = {}

    def start(self, config: ProductionRuntimeConfig) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return self.snapshot()

            normalized_camera_ids = self._normalize_camera_ids(config.camera_ids)
            normalized_default_profile = _normalize_profile_name(config.default_camera_profile, DEFAULT_CAMERA_PROFILE)
            normalized_overrides = _normalize_profile_overrides(config.camera_profile_overrides)

            if not bool(config.face_enabled) and not bool(config.vehicle_enabled):
                raise ValueError("At least one AI module must be enabled (face_enabled or vehicle_enabled)")

            cameras = self._load_cameras(normalized_camera_ids or None)
            if not cameras:
                raise ValueError("No active cameras found for production mode")
            self._validate_requested_camera_ids(normalized_camera_ids, cameras)
            self._validate_profile_overrides(
                overrides=normalized_overrides,
                cameras=cameras,
                strict=bool(config.strict_policy_validation),
            )

            self._config = ProductionRuntimeConfig(
                camera_ids=normalized_camera_ids or None,
                sample_interval_ms=max(100, int(config.sample_interval_ms)),
                face_enabled=bool(config.face_enabled),
                vehicle_enabled=bool(config.vehicle_enabled),
                persist_face=bool(config.persist_face),
                persist_vehicle=bool(config.persist_vehicle),
                face_top_k=max(1, min(20, int(config.face_top_k))),
                face_max_faces=max(1, min(64, int(config.face_max_faces))),
                vehicle_direction=str(config.vehicle_direction or "IN").upper(),
                vehicle_gate_id=str(config.vehicle_gate_id) if config.vehicle_gate_id else None,
                zone_id=int(config.zone_id) if config.zone_id is not None else None,
                enforce_camera_profiles=bool(config.enforce_camera_profiles),
                strict_policy_validation=bool(config.strict_policy_validation),
                default_camera_profile=normalized_default_profile,
                camera_profile_overrides=normalized_overrides,
            )
            self._states = {}
            self._threads = {}
            self._stop_events = {}

            for row in cameras:
                source = self._build_camera_source(row)
                if not source:
                    continue
                camera_id = int(row.id)
                profile_name = _infer_camera_profile(
                    row,
                    default_profile=self._config.default_camera_profile,
                    overrides=self._config.camera_profile_overrides or {},
                )
                profile_policy = CAMERA_PROFILE_POLICIES.get(profile_name, CAMERA_PROFILE_POLICIES[DEFAULT_CAMERA_PROFILE])
                sample_interval_ms = self._resolve_sample_interval_ms(
                    requested_ms=self._config.sample_interval_ms,
                    policy=profile_policy,
                    enforce_profiles=bool(self._config.enforce_camera_profiles),
                    strict=bool(self._config.strict_policy_validation),
                )
                face_max_faces = self._resolve_face_max_faces(
                    requested_max_faces=self._config.face_max_faces,
                    policy=profile_policy,
                    enforce_profiles=bool(self._config.enforce_camera_profiles),
                    strict=bool(self._config.strict_policy_validation),
                )
                state = _CameraRuntimeState(
                    camera_id=camera_id,
                    camera_name=str(row.name or f"Camera {camera_id}"),
                    source=str(source),
                    profile=profile_policy.name,
                    sample_interval_ms=int(sample_interval_ms),
                    face_max_faces=int(face_max_faces),
                    status="starting",
                )
                stop_event = threading.Event()
                thread = threading.Thread(
                    target=self._camera_loop,
                    args=(camera_id, stop_event),
                    name=f"production-live-cam-{camera_id}",
                    daemon=True,
                )
                self._states[camera_id] = state
                self._stop_events[camera_id] = stop_event
                self._threads[camera_id] = thread

            if not self._threads:
                raise ValueError("No camera stream source configured (rtsp_url/ip missing)")

            self._running = True
            self._started_at = _utcnow_iso()
            self._stopped_at = None
            for thread in self._threads.values():
                thread.start()

            return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._running:
                return self.snapshot()
            self._running = False
            stop_events = list(self._stop_events.values())
            threads = list(self._threads.values())
            sources = [str(state.source or "").strip() for state in self._states.values() if str(state.source or "").strip()]

        for stop_event in stop_events:
            stop_event.set()
        for thread in threads:
            thread.join(timeout=2.0)
        for source in sources:
            try:
                StreamService.release_camera_stream(rtsp_url=source)
            except Exception:
                pass

        with self._lock:
            for state in self._states.values():
                if state.status not in {"down", "degraded"}:
                    state.status = "stopped"
            self._threads = {}
            self._stop_events = {}
            self._stopped_at = _utcnow_iso()
            return self.snapshot()

    def stop_camera(self, camera_id: int) -> dict[str, Any]:
        target_id = int(camera_id)
        with self._lock:
            stop_event = self._stop_events.pop(target_id, None)
            thread = self._threads.pop(target_id, None)
            state = self._states.get(target_id)
            cfg = self._config

        if state is None:
            raise ValueError(f"Camera {target_id} is not part of active production runtime")
        source = str(state.source or "").strip()

        if stop_event is not None:
            stop_event.set()
        if thread is not None:
            thread.join(timeout=2.0)
        if source:
            try:
                StreamService.release_camera_stream(rtsp_url=source)
            except Exception:
                pass

        with self._lock:
            if state.status not in {"down", "degraded"}:
                state.status = "stopped"

            if cfg and cfg.camera_ids:
                cfg.camera_ids = [int(x) for x in cfg.camera_ids if int(x) != target_id]

            if len(self._threads) == 0:
                self._running = False
                self._stopped_at = _utcnow_iso()

            snapshot = self.snapshot()
        return snapshot

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._running)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            states = [state.to_dict() for state in sorted(self._states.values(), key=lambda s: s.camera_id)]
            cfg = self._config
            running = bool(self._running)
            started_at = self._started_at
            stopped_at = self._stopped_at

        total_frames = sum(_safe_int(item.get("frames_processed")) for item in states)
        up = sum(1 for item in states if str(item.get("status")) == "up")
        degraded = sum(1 for item in states if str(item.get("status")) == "degraded")
        down = sum(1 for item in states if str(item.get("status")) == "down")
        stopped = sum(1 for item in states if str(item.get("status")) == "stopped")

        return {
            "running": running,
            "started_at": started_at,
            "stopped_at": stopped_at,
            "config": {
                "camera_ids": list(cfg.camera_ids) if cfg and cfg.camera_ids else None,
                "sample_interval_ms": int(cfg.sample_interval_ms) if cfg else None,
                "face_enabled": bool(cfg.face_enabled) if cfg else None,
                "vehicle_enabled": bool(cfg.vehicle_enabled) if cfg else None,
                "persist_face": bool(cfg.persist_face) if cfg else None,
                "persist_vehicle": bool(cfg.persist_vehicle) if cfg else None,
                "face_top_k": int(cfg.face_top_k) if cfg else None,
                "face_max_faces": int(cfg.face_max_faces) if cfg else None,
                "vehicle_direction": str(cfg.vehicle_direction) if cfg else None,
                "vehicle_gate_id": str(cfg.vehicle_gate_id) if cfg and cfg.vehicle_gate_id else None,
                "zone_id": int(cfg.zone_id) if cfg and cfg.zone_id is not None else None,
                "enforce_camera_profiles": bool(cfg.enforce_camera_profiles) if cfg else None,
                "strict_policy_validation": bool(cfg.strict_policy_validation) if cfg else None,
                "default_camera_profile": str(cfg.default_camera_profile) if cfg else None,
                "camera_profile_overrides": dict(cfg.camera_profile_overrides or {}) if cfg else None,
                "allowed_camera_profiles": list(ALLOWED_CAMERA_PROFILES),
            },
            "totals": {
                "camera_total": len(states),
                "camera_up": int(up),
                "camera_degraded": int(degraded),
                "camera_down": int(down),
                "camera_stopped": int(stopped),
                "frames_processed_total": int(total_frames),
            },
            "cameras": states,
        }

    def _camera_loop(self, camera_id: int, stop_event: threading.Event) -> None:
        face_pipeline: Optional[FaceRecognitionPipeline] = None
        vehicle_pipeline: Optional[VehicleRecognitionPipeline] = None
        face_bootstrap_db: Optional[Session] = None
        vehicle_bootstrap_db: Optional[Session] = None

        try:
            with self._lock:
                cfg = self._config
                state = self._states.get(int(camera_id))

            if cfg is None or state is None:
                return

            if cfg.face_enabled:
                face_bootstrap_db = self.session_factory()
                face_pipeline = FaceRecognitionPipeline(face_bootstrap_db)
            if cfg.vehicle_enabled:
                vehicle_bootstrap_db = self.session_factory()
                vehicle_pipeline = VehicleRecognitionPipeline(vehicle_bootstrap_db)

            while not stop_event.is_set():
                loop_started = time.perf_counter()
                frame = StreamService.get_camera_frame(camera_id=int(camera_id), rtsp_url=state.source)

                with self._lock:
                    if frame is None:
                        state.status = "down"
                        state.read_errors += 1
                        state.last_error = "no_frame_from_stream"
                    else:
                        state.status = "up"
                        state.frames_processed += 1
                        state.last_frame_at = _utcnow_iso()
                        state.last_error = None
                        if hasattr(frame, "shape") and len(frame.shape) >= 2:
                            state.frame_height = _safe_int(frame.shape[0], state.frame_height)
                            state.frame_width = _safe_int(frame.shape[1], state.frame_width)

                if frame is not None and face_pipeline is not None:
                    face_db: Optional[Session] = None
                    face_started = time.perf_counter()
                    try:
                        face_db = self.session_factory()
                        face_pipeline.bind_db(face_db)
                        face_payload = face_pipeline.recognize_many_from_frame(
                            frame_bgr=frame,
                            camera_id=int(camera_id),
                            zone_id=cfg.zone_id,
                            persist=bool(cfg.persist_face),
                            top_k=int(cfg.face_top_k),
                            max_faces=int(state.face_max_faces),
                            image_bytes=None,
                        )
                        face_latency = (time.perf_counter() - face_started) * 1000.0
                        with self._lock:
                            state.face_frames += 1
                            state.face_latency_ms_total += float(face_latency)
                            state.face_latency_ms_max = max(state.face_latency_ms_max, float(face_latency))
                            state.face_last = self._summarize_face_payload(face_payload, face_latency)
                    except Exception as exc:
                        with self._lock:
                            state.status = "degraded"
                            state.last_error = f"face_pipeline_error: {exc}"
                    finally:
                        if face_db is not None:
                            try:
                                face_db.close()
                            except Exception:
                                pass

                if frame is not None and vehicle_pipeline is not None:
                    vehicle_db: Optional[Session] = None
                    veh_started = time.perf_counter()
                    try:
                        vehicle_db = self.session_factory()
                        vehicle_pipeline.bind_db(vehicle_db)
                        veh_payload = vehicle_pipeline.recognize_from_frame(
                            frame_bgr=frame,
                            camera_id=int(camera_id),
                            zone_id=cfg.zone_id,
                            gate_id=cfg.vehicle_gate_id,
                            direction=cfg.vehicle_direction,
                            persist=bool(cfg.persist_vehicle),
                            save_snapshot=bool(cfg.persist_vehicle),
                            image_bytes=None,
                        )
                        veh_latency = (time.perf_counter() - veh_started) * 1000.0
                        with self._lock:
                            state.vehicle_frames += 1
                            state.vehicle_latency_ms_total += float(veh_latency)
                            state.vehicle_latency_ms_max = max(state.vehicle_latency_ms_max, float(veh_latency))
                            state.vehicle_last = self._summarize_vehicle_payload(veh_payload, veh_latency)
                    except Exception as exc:
                        with self._lock:
                            state.status = "degraded"
                            state.last_error = f"vehicle_pipeline_error: {exc}"
                    finally:
                        if vehicle_db is not None:
                            try:
                                vehicle_db.close()
                            except Exception:
                                pass

                elapsed_ms = (time.perf_counter() - loop_started) * 1000.0
                wait_ms = max(0, int(state.sample_interval_ms) - int(elapsed_ms))
                if wait_ms > 0:
                    stop_event.wait(wait_ms / 1000.0)
        finally:
            try:
                with self._lock:
                    st = self._states.get(int(camera_id))
                    if st is not None and st.status not in {"down", "degraded"}:
                        st.status = "stopped"
            except Exception:
                pass
            if face_bootstrap_db is not None:
                try:
                    face_bootstrap_db.close()
                except Exception:
                    pass
            if vehicle_bootstrap_db is not None:
                try:
                    vehicle_bootstrap_db.close()
                except Exception:
                    pass
            try:
                with self._lock:
                    source = self._states.get(int(camera_id)).source if int(camera_id) in self._states else None
                if source:
                    StreamService.release_camera_stream(rtsp_url=source)
            except Exception:
                pass

    def _load_cameras(self, camera_ids: Optional[list[int]]) -> list[Camera]:
        db = self.session_factory()
        try:
            query = db.query(Camera).filter(Camera.is_active.is_(True))
            if camera_ids:
                normalized_ids = [int(x) for x in camera_ids if int(x) > 0]
                if normalized_ids:
                    query = query.filter(Camera.id.in_(normalized_ids))
            return query.order_by(Camera.id.asc()).all()
        finally:
            db.close()

    @staticmethod
    def _normalize_camera_ids(camera_ids: Optional[list[int]]) -> list[int]:
        if not camera_ids:
            return []
        unique_ids: list[int] = []
        seen: set[int] = set()
        for raw in camera_ids:
            camera_id = _safe_int(raw, 0)
            if camera_id <= 0:
                continue
            if camera_id in seen:
                continue
            seen.add(camera_id)
            unique_ids.append(camera_id)
        return unique_ids

    @staticmethod
    def _validate_requested_camera_ids(requested_ids: list[int], cameras: list[Camera]) -> None:
        if not requested_ids:
            return
        found = {int(getattr(row, "id", 0) or 0) for row in cameras}
        missing = [camera_id for camera_id in requested_ids if camera_id not in found]
        if missing:
            missing_csv = ", ".join(str(x) for x in missing)
            raise ValueError(f"Requested cameras are not active or unavailable: {missing_csv}")

    @staticmethod
    def _validate_profile_overrides(
        *,
        overrides: Mapping[int, str],
        cameras: list[Camera],
        strict: bool,
    ) -> None:
        if not overrides:
            return
        available_ids = {int(getattr(row, "id", 0) or 0) for row in cameras}
        unknown_ids = sorted(camera_id for camera_id in overrides if camera_id not in available_ids)
        if unknown_ids and strict:
            unknown_csv = ", ".join(str(x) for x in unknown_ids)
            raise ValueError(
                f"Camera profile overrides reference cameras not selected/active: {unknown_csv}"
            )

    @staticmethod
    def _resolve_sample_interval_ms(
        *,
        requested_ms: int,
        policy: CameraProfilePolicy,
        enforce_profiles: bool,
        strict: bool,
    ) -> int:
        requested = max(100, int(requested_ms))
        if not enforce_profiles:
            return requested
        if policy.min_sample_interval_ms <= requested <= policy.max_sample_interval_ms:
            return requested
        if strict:
            raise ValueError(
                f"sample_interval_ms={requested} is out of profile range for '{policy.name}' "
                f"({policy.min_sample_interval_ms}-{policy.max_sample_interval_ms})"
            )
        return max(policy.min_sample_interval_ms, min(policy.max_sample_interval_ms, requested))

    @staticmethod
    def _resolve_face_max_faces(
        *,
        requested_max_faces: int,
        policy: CameraProfilePolicy,
        enforce_profiles: bool,
        strict: bool,
    ) -> int:
        requested = max(1, int(requested_max_faces))
        if not enforce_profiles:
            return requested
        if policy.min_face_max_faces <= requested <= policy.max_face_max_faces:
            return requested
        if strict:
            raise ValueError(
                f"face_max_faces={requested} is out of profile range for '{policy.name}' "
                f"({policy.min_face_max_faces}-{policy.max_face_max_faces})"
            )
        return max(policy.min_face_max_faces, min(policy.max_face_max_faces, requested))

    @staticmethod
    def _build_camera_source(camera: Camera) -> Optional[str]:
        rtsp = str(getattr(camera, "rtsp_url", "") or "").strip()
        if rtsp:
            injected = CameraService._inject_rtsp_auth(rtsp, getattr(camera, "username", None), getattr(camera, "password", None))
            return injected or rtsp

        ip = str(getattr(camera, "ip_address", "") or "").strip()
        if not ip:
            return None

        port = _safe_int(getattr(camera, "port", 554), 554)
        user = str(getattr(camera, "username", "") or "").strip()
        pwd = str(getattr(camera, "password", "") or "").strip()
        if user and pwd:
            return f"rtsp://{user}:{pwd}@{ip}:{port}/stream"
        if user:
            return f"rtsp://{user}@{ip}:{port}/stream"
        return f"rtsp://{ip}:{port}/stream"

    @staticmethod
    def _summarize_face_payload(payload: dict[str, Any], latency_ms: float) -> dict[str, Any]:
        faces_raw = payload.get("faces") if isinstance(payload, dict) else []
        faces_out: list[dict[str, Any]] = []
        if isinstance(faces_raw, list):
            for item in faces_raw[:8]:
                if not isinstance(item, dict):
                    continue
                bbox_raw = item.get("bbox")
                bbox = None
                if isinstance(bbox_raw, dict):
                    bbox = {
                        "x": _safe_int(bbox_raw.get("x"), 0),
                        "y": _safe_int(bbox_raw.get("y"), 0),
                        "w": _safe_int(bbox_raw.get("w"), 0),
                        "h": _safe_int(bbox_raw.get("h"), 0),
                    }
                faces_out.append(
                    {
                        "status": str(item.get("status") or ""),
                        "label": str(item.get("label") or item.get("personnel_name") or "UNKNOWN"),
                        "personnel_id": _safe_int(item.get("personnel_id"), 0) or None,
                        "track_id": _safe_int(item.get("track_id"), 0) or None,
                        "confidence": round(_safe_float(item.get("confidence")), 4),
                        "match_quality": str(item.get("match_quality") or ""),
                        "bbox": bbox,
                    }
                )
        return {
            "status": str(payload.get("status", "unknown")),
            "faces_count": _safe_int(payload.get("faces_count"), len(faces_out)),
            "matched_count": _safe_int(payload.get("matched_count"), 0),
            "unknown_count": _safe_int(payload.get("unknown_count"), 0),
            "latency_ms": round(float(latency_ms), 3),
            "timestamp": _utcnow_iso(),
            "faces": faces_out,
        }

    @staticmethod
    def _summarize_vehicle_payload(payload: dict[str, Any], latency_ms: float) -> dict[str, Any]:
        vehicle_bbox_raw = payload.get("vehicle_bbox")
        vehicle_bbox = None
        if isinstance(vehicle_bbox_raw, dict):
            vehicle_bbox = {
                "x": _safe_int(vehicle_bbox_raw.get("x"), 0),
                "y": _safe_int(vehicle_bbox_raw.get("y"), 0),
                "w": _safe_int(vehicle_bbox_raw.get("w"), 0),
                "h": _safe_int(vehicle_bbox_raw.get("h"), 0),
            }

        plate_bbox_raw = payload.get("plate_bbox")
        plate_bbox = None
        if isinstance(plate_bbox_raw, dict):
            plate_bbox = {
                "x": _safe_int(plate_bbox_raw.get("x"), 0),
                "y": _safe_int(plate_bbox_raw.get("y"), 0),
                "w": _safe_int(plate_bbox_raw.get("w"), 0),
                "h": _safe_int(plate_bbox_raw.get("h"), 0),
            }

        return {
            "status": str(payload.get("status", "unknown")),
            "vehicle_detected": bool(payload.get("vehicle_detected", False)),
            "plate_number": payload.get("plate_display") or payload.get("plate_number"),
            "plate_type": str(payload.get("plate_type", "unknown")),
            "confidence": round(_safe_float(payload.get("confidence")), 4),
            "vehicle_class": payload.get("vehicle_class"),
            "vehicle_confidence": round(_safe_float(payload.get("vehicle_confidence")), 4),
            "vehicle_bbox": vehicle_bbox,
            "plate_bbox": plate_bbox,
            "event_id": _safe_int(payload.get("event_id"), 0) or None,
            "security_tag": payload.get("security_tag"),
            "decision": payload.get("decision"),
            "decision_reason": payload.get("decision_reason"),
            "requires_manual_review": bool(payload.get("requires_manual_review", False)),
            "latency_ms": round(float(latency_ms), 3),
            "timestamp": _utcnow_iso(),
        }


class OperationModeManager:
    """
    System operation mode coordinator.

    - development: enrollment/training flow (existing modules unchanged)
    - production: live multi-camera AI runtime
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._mode: str = "development"
        self._last_transition_at: str = _utcnow_iso()
        self._runtime = ProductionLiveRuntime()

    def set_development_mode(self) -> dict[str, Any]:
        with self._lock:
            self._runtime.stop()
            self._mode = "development"
            self._last_transition_at = _utcnow_iso()
            return self.status()

    def start_production_mode(self, config: ProductionRuntimeConfig) -> dict[str, Any]:
        with self._lock:
            self._runtime.start(config)
            self._mode = "production"
            self._last_transition_at = _utcnow_iso()
            return self.status()

    def stop_production_mode(self) -> dict[str, Any]:
        with self._lock:
            self._runtime.stop()
            self._mode = "development"
            self._last_transition_at = _utcnow_iso()
            return self.status()

    def stop_production_camera(self, camera_id: int) -> dict[str, Any]:
        with self._lock:
            if self._mode != "production":
                raise ValueError("Production mode is not active")
            self._runtime.stop_camera(int(camera_id))
            if not self._runtime.is_running():
                self._mode = "development"
            self._last_transition_at = _utcnow_iso()
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": str(self._mode),
                "last_transition_at": self._last_transition_at,
                "development": {
                    "enrollment_pipeline": "active",
                    "note": "Face enrollment/training module remains unchanged.",
                },
                "production_runtime": self._runtime.snapshot(),
            }


_operation_mode_manager = OperationModeManager()


def get_operation_mode_manager() -> OperationModeManager:
    return _operation_mode_manager
