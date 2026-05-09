from __future__ import annotations

import threading
import time

from vms.backend.services.scaling.camera_lease_store import SqliteCameraLeaseStore
from vms.backend.services.scaling.frame_task_queue import BoundedTaskQueue, FrameTask
from vms.backend.services.scaling.multi_camera_ingestion_service import (
    CameraIngestionConfig,
    MultiCameraIngestionService,
)


class _FakeFrameReader:
    def __init__(self) -> None:
        self._counts: dict[int, int] = {}

    def __call__(self, camera_id: int, source: str):
        current = self._counts.get(camera_id, 0) + 1
        self._counts[camera_id] = current
        return {"camera_id": camera_id, "source": source, "frame_no": current}


class _FlakyFrameReader:
    def __init__(self, fail_count: int) -> None:
        self.fail_count = max(0, int(fail_count))
        self._calls: dict[int, int] = {}

    def __call__(self, camera_id: int, source: str):
        current = self._calls.get(camera_id, 0) + 1
        self._calls[camera_id] = current
        if current <= self.fail_count:
            return None
        return {"camera_id": camera_id, "source": source, "frame_no": current}


class _AlwaysNoneReader:
    def __call__(self, camera_id: int, source: str):
        return None


def test_ingestion_service_enqueues_frames_per_camera() -> None:
    frame_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=64)
    reader = _FakeFrameReader()
    service = MultiCameraIngestionService(
        frame_queue=frame_queue,
        frame_reader=reader,
        idle_sleep_sec=0.005,
    )
    service.register_camera(
        CameraIngestionConfig(camera_id=10, source="0", sample_interval_ms=20, enabled=True)
    )
    service.register_camera(
        CameraIngestionConfig(camera_id=11, source="1", sample_interval_ms=20, enabled=True)
    )

    service.start()
    time.sleep(0.20)
    service.stop()

    metrics = service.snapshot_metrics()
    cam10 = metrics["per_camera"][10]
    cam11 = metrics["per_camera"][11]
    assert cam10["frames_enqueued"] > 0
    assert cam11["frames_enqueued"] > 0
    assert metrics["service"]["running"] is False

    # Queue keeps latest per camera, so size stays bounded and non-zero after short run.
    assert metrics["queue"]["size"] >= 1


def test_ingestion_service_tracks_reconnect_and_health_recovery() -> None:
    frame_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=64)
    reader = _FlakyFrameReader(fail_count=4)
    service = MultiCameraIngestionService(
        frame_queue=frame_queue,
        frame_reader=reader,
        idle_sleep_sec=0.002,
    )
    service.register_camera(
        CameraIngestionConfig(
            camera_id=21,
            source="0",
            sample_interval_ms=20,
            retry_backoff_ms=10,
            retry_backoff_max_ms=80,
            retry_backoff_factor=2.0,
            degraded_error_threshold=2,
            down_error_threshold=6,
            enabled=True,
        )
    )

    service.start()
    time.sleep(0.35)
    service.stop()

    metrics = service.snapshot_metrics()["per_camera"][21]
    assert metrics["read_errors"] >= 4
    assert metrics["reconnect_attempts"] >= 4
    assert metrics["reconnect_recoveries"] >= 1
    assert metrics["frames_enqueued"] > 0
    assert metrics["health_status"] == "up"
    assert metrics["read_fps_30s"] >= 0.0


def test_ingestion_service_marks_down_when_errors_persist() -> None:
    frame_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=16)
    reader = _AlwaysNoneReader()
    service = MultiCameraIngestionService(
        frame_queue=frame_queue,
        frame_reader=reader,
        idle_sleep_sec=0.002,
    )
    service.register_camera(
        CameraIngestionConfig(
            camera_id=31,
            source="0",
            sample_interval_ms=20,
            retry_backoff_ms=10,
            retry_backoff_max_ms=40,
            retry_backoff_factor=2.0,
            degraded_error_threshold=1,
            down_error_threshold=2,
            enabled=True,
        )
    )

    service.start()
    time.sleep(0.18)
    service.stop()

    metrics = service.snapshot_metrics()["per_camera"][31]
    assert metrics["read_errors"] >= 2
    assert metrics["health_status"] == "down"
    assert metrics["reconnect_attempts"] >= 2


def test_ingestion_service_self_heals_missing_camera_threads() -> None:
    frame_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=16)
    reader = _FakeFrameReader()
    service = MultiCameraIngestionService(
        frame_queue=frame_queue,
        frame_reader=reader,
        idle_sleep_sec=0.002,
    )
    service.register_camera(
        CameraIngestionConfig(
            camera_id=41,
            source="0",
            sample_interval_ms=20,
            enabled=True,
        )
    )

    service.start()
    time.sleep(0.08)
    with service._lock:
        service._threads[41] = threading.Thread(target=lambda: None, daemon=True)

    healed = service.ensure_camera_threads()
    service.stop()

    snap = service.snapshot_metrics()["service"]
    assert healed["restarted"] >= 1
    assert 41 in healed["restarted_cameras"]
    assert snap["thread_restarts_total"] >= 1


def test_ingestion_service_claims_expired_camera_lease(tmp_path) -> None:
    lease_db = tmp_path / "camera_lease_failover.db"
    namespace = "ingestion_failover"

    stale_owner = SqliteCameraLeaseStore(
        db_path=str(lease_db),
        namespace=namespace,
        owner_id="stale-owner",
        owner_role="ingestion",
        lease_ttl_sec=0.15,
    )
    standby_owner = SqliteCameraLeaseStore(
        db_path=str(lease_db),
        namespace=namespace,
        owner_id="standby-owner",
        owner_role="ingestion",
        lease_ttl_sec=0.15,
    )
    stale_owner.claim_or_renew(51, owner_metadata={"camera": 51})

    frame_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=16)
    reader = _FakeFrameReader()
    service = MultiCameraIngestionService(
        frame_queue=frame_queue,
        frame_reader=reader,
        idle_sleep_sec=0.002,
        camera_lease_store=standby_owner,
        ownership_heartbeat_interval_sec=0.03,
    )
    service.register_camera(
        CameraIngestionConfig(
            camera_id=51,
            source="0",
            sample_interval_ms=20,
            enabled=True,
        )
    )

    service.start()
    time.sleep(0.05)
    first_snapshot = service.snapshot_metrics()
    assert first_snapshot["service"]["active_threads"] == 0
    assert first_snapshot["per_camera"][51]["ownership"]["status"] == "standby"

    time.sleep(0.18)
    healed = service.ensure_camera_threads()
    time.sleep(0.10)
    service.stop()

    final_snapshot = service.snapshot_metrics()
    assert healed["restarted"] >= 1
    assert final_snapshot["per_camera"][51]["frames_enqueued"] > 0
    assert final_snapshot["per_camera"][51]["ownership"]["acquired_total"] >= 1
