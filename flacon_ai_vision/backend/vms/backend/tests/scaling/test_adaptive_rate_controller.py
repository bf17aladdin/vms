from __future__ import annotations

from vms.backend.services.scaling.adaptive_rate_controller import (
    AdaptiveRateController,
    AdaptiveRateControllerConfig,
)
from vms.backend.services.scaling.frame_task_queue import (
    BoundedTaskQueue,
    FrameTask,
    utc_now_iso,
)
from vms.backend.services.scaling.multi_camera_ingestion_service import (
    CameraIngestionConfig,
    MultiCameraIngestionService,
)


def _build_ingestion_with_camera(
    *,
    sample_interval_ms: int,
    queue_maxsize: int = 10,
) -> tuple[MultiCameraIngestionService, BoundedTaskQueue[FrameTask]]:
    frame_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=queue_maxsize)
    ingestion = MultiCameraIngestionService(
        frame_queue=frame_queue,
        frame_reader=lambda _camera_id, _source: None,
        idle_sleep_sec=0.005,
    )
    ingestion.register_camera(
        CameraIngestionConfig(
            camera_id=1,
            source="sim://camera/1",
            enabled=True,
            sample_interval_ms=int(sample_interval_ms),
        )
    )
    return ingestion, frame_queue


def _enqueue_tasks(frame_queue: BoundedTaskQueue[FrameTask], *, count: int) -> None:
    for idx in range(max(0, int(count))):
        frame_queue.put(
            FrameTask(
                camera_id=1,
                source="sim://camera/1",
                frame={"n": idx},
                captured_at=utc_now_iso(),
                sequence=idx + 1,
            )
        )


def test_adaptive_rate_increases_on_high_queue_pressure() -> None:
    ingestion, frame_queue = _build_ingestion_with_camera(sample_interval_ms=120, queue_maxsize=10)
    _enqueue_tasks(frame_queue, count=6)  # queue ratio = 0.6

    controller = AdaptiveRateController(
        ingestion_service=ingestion,
        frame_queue=frame_queue,
        config=AdaptiveRateControllerConfig(
            enabled=True,
            min_sample_interval_ms=120,
            max_sample_interval_ms=500,
            adjust_step_ms=40,
            queue_high_ratio=0.35,
            queue_low_ratio=0.05,
            cpu_high_pct=85.0,
            cpu_low_pct=55.0,
        ),
        cpu_provider=lambda: 20.0,
    )

    controller.tick_once()

    current = ingestion.list_cameras()[0]
    snapshot = controller.snapshot()
    assert current.sample_interval_ms == 160
    assert snapshot["adjustments_up"] == 1
    assert snapshot["last_reason"] == "queue_high"


def test_adaptive_rate_decreases_on_low_queue_and_cpu() -> None:
    ingestion, frame_queue = _build_ingestion_with_camera(sample_interval_ms=220, queue_maxsize=10)

    controller = AdaptiveRateController(
        ingestion_service=ingestion,
        frame_queue=frame_queue,
        config=AdaptiveRateControllerConfig(
            enabled=True,
            min_sample_interval_ms=120,
            max_sample_interval_ms=500,
            adjust_step_ms=40,
            queue_high_ratio=0.35,
            queue_low_ratio=0.05,
            cpu_high_pct=85.0,
            cpu_low_pct=55.0,
        ),
        cpu_provider=lambda: 30.0,
    )

    controller.tick_once()

    current = ingestion.list_cameras()[0]
    snapshot = controller.snapshot()
    assert current.sample_interval_ms == 180
    assert snapshot["adjustments_down"] == 1
    assert snapshot["last_reason"] == "queue_low_and_cpu_ok"


def test_adaptive_rate_respects_min_max_bounds() -> None:
    ingestion_up, frame_queue_up = _build_ingestion_with_camera(sample_interval_ms=490, queue_maxsize=10)
    _enqueue_tasks(frame_queue_up, count=7)  # queue ratio = 0.7
    up_controller = AdaptiveRateController(
        ingestion_service=ingestion_up,
        frame_queue=frame_queue_up,
        config=AdaptiveRateControllerConfig(
            enabled=True,
            min_sample_interval_ms=120,
            max_sample_interval_ms=500,
            adjust_step_ms=40,
        ),
        cpu_provider=lambda: 10.0,
    )

    up_controller.tick_once()
    assert ingestion_up.list_cameras()[0].sample_interval_ms == 500

    ingestion_down, frame_queue_down = _build_ingestion_with_camera(sample_interval_ms=130, queue_maxsize=10)
    down_controller = AdaptiveRateController(
        ingestion_service=ingestion_down,
        frame_queue=frame_queue_down,
        config=AdaptiveRateControllerConfig(
            enabled=True,
            min_sample_interval_ms=120,
            max_sample_interval_ms=500,
            adjust_step_ms=40,
        ),
        cpu_provider=lambda: 10.0,
    )

    down_controller.tick_once()
    assert ingestion_down.list_cameras()[0].sample_interval_ms == 120
