from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from fastapi import WebSocket
from sqlalchemy.orm import Session

from vms.backend.core.database import SessionLocal
from vms.backend.services.multi_cam_monitor import MultiCamMonitorService

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _coerce_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _coerce_float(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


@dataclass(frozen=True)
class MultiCamStreamParams:
    minutes: int = 30
    person_limit: int = 20
    vehicle_limit: int = 20
    similarity_threshold: float = 0.88

    @classmethod
    def from_values(
        cls,
        *,
        minutes: Any = 30,
        person_limit: Any = 20,
        vehicle_limit: Any = 20,
        similarity_threshold: Any = 0.88,
    ) -> "MultiCamStreamParams":
        return cls(
            minutes=_coerce_int(minutes, default=30, minimum=5, maximum=240),
            person_limit=_coerce_int(person_limit, default=20, minimum=1, maximum=100),
            vehicle_limit=_coerce_int(vehicle_limit, default=20, minimum=1, maximum=100),
            similarity_threshold=round(
                _coerce_float(
                    similarity_threshold,
                    default=0.88,
                    minimum=0.5,
                    maximum=1.0,
                ),
                4,
            ),
        )

    def channel_key(self) -> str:
        return (
            f"minutes={self.minutes}|person_limit={self.person_limit}|"
            f"vehicle_limit={self.vehicle_limit}|similarity={self.similarity_threshold:.4f}"
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "minutes": int(self.minutes),
            "person_limit": int(self.person_limit),
            "vehicle_limit": int(self.vehicle_limit),
            "similarity_threshold": float(self.similarity_threshold),
        }


def _snapshot_core(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": copy.deepcopy(snapshot.get("summary") or {}),
        "persons": copy.deepcopy(snapshot.get("persons") or []),
        "vehicles": copy.deepcopy(snapshot.get("vehicles") or []),
        "timeline": copy.deepcopy(snapshot.get("timeline") or []),
    }


def _sort_persons(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            float(row.get("track_confidence") or 0.0),
            str(row.get("last_seen") or ""),
        ),
        reverse=True,
    )


def _sort_vehicles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: str(row.get("detected_at") or ""),
        reverse=True,
    )


def _person_identity(track: dict[str, Any]) -> str:
    return str(track.get("track_id") or "")


def _vehicle_identity(track: dict[str, Any]) -> str:
    return str(track.get("detection_id") or "")


def _timeline_changed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    return list(previous.get("timeline") or []) != list(current.get("timeline") or [])


def _build_change_events(
    *,
    person_upsert: list[dict[str, Any]],
    vehicle_upsert: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    for track in _sort_persons(person_upsert)[:4]:
        events.append(
            {
                "type": "person_track_upsert",
                "timestamp": str(track.get("last_seen") or ""),
                "payload": {
                    "track_id": track.get("track_id"),
                    "label": track.get("label"),
                    "camera_id": track.get("last_camera_id"),
                    "camera_ids": track.get("camera_ids") or [],
                    "confidence": track.get("track_confidence"),
                    "detections_count": track.get("detections_count"),
                },
            }
        )

    for vehicle in _sort_vehicles(vehicle_upsert)[:4]:
        events.append(
            {
                "type": "vehicle_track_upsert",
                "timestamp": str(vehicle.get("detected_at") or ""),
                "payload": {
                    "detection_id": vehicle.get("detection_id"),
                    "license_plate": vehicle.get("license_plate"),
                    "camera_id": vehicle.get("camera_id"),
                    "vehicle_type": vehicle.get("vehicle_type"),
                    "confidence": vehicle.get("confidence"),
                    "color": vehicle.get("color"),
                },
            }
        )

    events.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
    return events[:6]


def build_multi_cam_snapshot_diff(
    previous_snapshot: dict[str, Any],
    current_snapshot: dict[str, Any],
) -> Optional[dict[str, Any]]:
    previous = _snapshot_core(previous_snapshot)
    current = _snapshot_core(current_snapshot)

    previous_persons = {
        _person_identity(track): track
        for track in previous.get("persons") or []
        if _person_identity(track)
    }
    current_persons = {
        _person_identity(track): track
        for track in current.get("persons") or []
        if _person_identity(track)
    }
    person_upsert = [
        copy.deepcopy(track)
        for track_id, track in current_persons.items()
        if previous_persons.get(track_id) != track
    ]
    person_remove = [
        track_id for track_id in previous_persons.keys() if track_id not in current_persons
    ]

    previous_vehicles = {
        _vehicle_identity(track): track
        for track in previous.get("vehicles") or []
        if _vehicle_identity(track)
    }
    current_vehicles = {
        _vehicle_identity(track): track
        for track in current.get("vehicles") or []
        if _vehicle_identity(track)
    }
    vehicle_upsert = [
        copy.deepcopy(track)
        for track_id, track in current_vehicles.items()
        if previous_vehicles.get(track_id) != track
    ]
    vehicle_remove = [
        track_id for track_id in previous_vehicles.keys() if track_id not in current_vehicles
    ]

    summary_changed = previous.get("summary") != current.get("summary")
    timeline_replace = (
        copy.deepcopy(current.get("timeline") or [])
        if _timeline_changed(previous, current)
        else None
    )

    if (
        not summary_changed
        and not person_upsert
        and not person_remove
        and not vehicle_upsert
        and not vehicle_remove
        and timeline_replace is None
    ):
        return None

    return {
        "generated_at": current_snapshot.get("generated_at"),
        "summary": copy.deepcopy(current.get("summary") or {}),
        "persons": {
            "upsert": _sort_persons(person_upsert),
            "remove": person_remove,
        },
        "vehicles": {
            "upsert": _sort_vehicles(vehicle_upsert),
            "remove": vehicle_remove,
        },
        "timeline": {
            "replace": timeline_replace,
        },
        "events": _build_change_events(
            person_upsert=person_upsert,
            vehicle_upsert=vehicle_upsert,
        ),
    }


@dataclass
class _ChannelState:
    params: MultiCamStreamParams
    snapshot: Optional[dict[str, Any]] = None
    version: int = 0
    subscribers: set[WebSocket] = field(default_factory=set)
    task: Optional[asyncio.Task[None]] = None
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    fps_counter: int = 0
    fps_start_time: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    current_fps: float = 0.0


class MultiCamMonitorStreamHub:
    def __init__(
        self,
        *,
        session_factory: Optional[SessionFactory] = None,
        poll_interval_sec: float = 2.0,
    ):
        self._session_factory = session_factory or SessionLocal
        self._poll_interval_sec = max(0.05, float(poll_interval_sec))
        self._channels: dict[str, _ChannelState] = {}
        self._channels_lock = asyncio.Lock()

    async def get_snapshot(
        self,
        *,
        params: MultiCamStreamParams,
        db: Optional[Session] = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        channel = await self._get_or_create_channel(params)
        if force_refresh or channel.snapshot is None:
            await self._refresh_channel(channel, db=db)
        return copy.deepcopy(channel.snapshot or self._empty_snapshot(params=params))

    async def connect(self, websocket: WebSocket, *, params: MultiCamStreamParams) -> None:
        await websocket.accept()
        channel = await self._get_or_create_channel(params)
        async with self._channels_lock:
            channel.subscribers.add(websocket)
            if channel.task is None or channel.task.done():
                channel.task = asyncio.create_task(
                    self._run_channel(channel_key=params.channel_key()),
                    name=f"multi-cam-stream:{params.channel_key()}",
                )

        snapshot = await self.get_snapshot(params=params, force_refresh=True)
        await websocket.send_json({"type": "multi_cam_snapshot", "data": snapshot})

    async def disconnect(self, websocket: WebSocket, *, params: MultiCamStreamParams) -> None:
        channel_key = params.channel_key()
        async with self._channels_lock:
            channel = self._channels.get(channel_key)
            if channel is None:
                return
            channel.subscribers.discard(websocket)

    async def _get_or_create_channel(self, params: MultiCamStreamParams) -> _ChannelState:
        channel_key = params.channel_key()
        async with self._channels_lock:
            existing = self._channels.get(channel_key)
            if existing is not None:
                return existing
            channel = _ChannelState(params=params)
            self._channels[channel_key] = channel
            return channel

    def _build_snapshot_payload(
        self,
        *,
        db: Session,
        params: MultiCamStreamParams,
        version: int,
    ) -> dict[str, Any]:
        service = MultiCamMonitorService(db)
        payload = service.get_snapshot(
            minutes=params.minutes,
            person_limit=params.person_limit,
            vehicle_limit=params.vehicle_limit,
            similarity_threshold=params.similarity_threshold,
        )
        return {
            "success": True,
            "version": int(version),
            "stream_key": params.channel_key(),
            "stream_params": params.to_payload(),
            **payload,
        }

    def _empty_snapshot(self, *, params: MultiCamStreamParams) -> dict[str, Any]:
        return {
            "success": True,
            "version": 0,
            "stream_key": params.channel_key(),
            "stream_params": params.to_payload(),
            "generated_at": None,
            "summary": {
                "active_person_tracks": 0,
                "cross_camera_tracks": 0,
                "recent_vehicle_tracks": 0,
            },
            "persons": [],
            "vehicles": [],
            "timeline": [],
        }

    async def _refresh_channel(
        self,
        channel: _ChannelState,
        *,
        db: Optional[Session] = None,
    ) -> Optional[dict[str, Any]]:
        async with channel.refresh_lock:
            previous = copy.deepcopy(channel.snapshot) if channel.snapshot is not None else None

            try:
                if db is not None:
                    next_snapshot = self._build_snapshot_payload(
                        db=db,
                        params=channel.params,
                        version=max(1, channel.version or 1),
                    )
                else:
                    session = self._session_factory()
                    try:
                        next_snapshot = self._build_snapshot_payload(
                            db=session,
                            params=channel.params,
                            version=max(1, channel.version or 1),
                        )
                    finally:
                        session.close()
            except Exception:
                logger.exception(
                    "Failed to refresh multi-cam channel %s",
                    channel.params.channel_key(),
                )
                return None

            if previous is None:
                channel.version = 1
                next_snapshot["version"] = channel.version
                channel.snapshot = next_snapshot
                return None

            diff = build_multi_cam_snapshot_diff(previous, next_snapshot)
            if diff is None:
                next_snapshot["version"] = max(1, channel.version)
                channel.snapshot = next_snapshot
                return None

            channel.version += 1
            next_snapshot["version"] = channel.version
            channel.snapshot = next_snapshot
            diff["version"] = channel.version
            diff["stream_key"] = channel.params.channel_key()
            diff["stream_params"] = channel.params.to_payload()
            
            # Update FPS counter
            channel.fps_counter += 1
            current_time = asyncio.get_event_loop().time()
            elapsed = current_time - channel.fps_start_time
            if elapsed >= 1.0:  # Update FPS every second
                channel.current_fps = channel.fps_counter / elapsed
                channel.fps_counter = 0
                channel.fps_start_time = current_time
            
            diff["performance"] = {
                "current_fps": round(channel.current_fps, 2),
                "poll_interval_sec": self._poll_interval_sec
            }
            
            return diff

    async def _run_channel(self, *, channel_key: str) -> None:
        try:
            while True:
                async with self._channels_lock:
                    channel = self._channels.get(channel_key)
                    if channel is None:
                        return
                    subscribers = tuple(channel.subscribers)

                if not subscribers:
                    return

                diff = await self._refresh_channel(channel)
                if diff is not None:
                    await self._broadcast(subscribers=subscribers, channel=channel, message={"type": "multi_cam_diff", "data": diff})

                await asyncio.sleep(self._poll_interval_sec)
        finally:
            async with self._channels_lock:
                channel = self._channels.get(channel_key)
                if channel is not None:
                    channel.task = None

    async def _broadcast(
        self,
        *,
        subscribers: tuple[WebSocket, ...],
        channel: _ChannelState,
        message: dict[str, Any],
    ) -> None:
        disconnected: list[WebSocket] = []
        for websocket in subscribers:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(websocket)

        if disconnected:
            async with self._channels_lock:
                for websocket in disconnected:
                    channel.subscribers.discard(websocket)


_multi_cam_stream_hub: Optional[MultiCamMonitorStreamHub] = None


def get_multi_cam_monitor_stream_hub() -> MultiCamMonitorStreamHub:
    global _multi_cam_stream_hub
    if _multi_cam_stream_hub is None:
        _multi_cam_stream_hub = MultiCamMonitorStreamHub()
    return _multi_cam_stream_hub


def reset_multi_cam_monitor_stream_hub() -> None:
    global _multi_cam_stream_hub
    _multi_cam_stream_hub = None
