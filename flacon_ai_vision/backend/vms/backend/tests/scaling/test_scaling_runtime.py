from __future__ import annotations

import time

from vms.backend.services.scaling.scaling_runtime import (
    RuntimeThresholds,
    ScalingRuntime,
    SimulationProfile,
)


def test_scaling_runtime_simulated_pipeline_runs_and_reports_go() -> None:
    runtime = ScalingRuntime.build_simulated(
        camera_count=6,
        sample_interval_ms=60,
        frame_queue_maxsize=256,
        result_queue_maxsize=256,
        inference_workers=2,
        writer_workers=1,
        profile=SimulationProfile(
            frame_reader_latency_ms_min=1.0,
            frame_reader_latency_ms_max=3.0,
            inference_latency_ms_min=5.0,
            inference_latency_ms_max=15.0,
            persistence_latency_ms_min=1.0,
            persistence_latency_ms_max=5.0,
            inference_success_ratio=1.0,
            persistence_success_ratio=1.0,
        ),
    )
    thresholds = RuntimeThresholds(
        p95_end_to_end_ms_max=3000.0,
        queue_depth_max=200,
        event_persist_success_min_pct=0.0,
    )

    runtime.start()
    time.sleep(1.2)
    runtime.stop()

    snapshot = runtime.snapshot()
    evaluation = runtime.evaluate(thresholds)

    assert snapshot["inference_worker"]["processed"] > 0
    assert snapshot["event_writer_worker"]["processed"] > 0
    assert snapshot["measured_persistence"]["persisted"] > 0
    assert evaluation["verdict"] == "GO"


def test_scaling_runtime_can_use_custom_persistence_service() -> None:
    class _Persistence:
        def __init__(self) -> None:
            self.calls = 0

        def persist(self, result):
            self.calls += 1
            return self.calls

    custom = _Persistence()
    runtime = ScalingRuntime.build_simulated(
        camera_count=3,
        sample_interval_ms=80,
        frame_queue_maxsize=128,
        result_queue_maxsize=128,
        inference_workers=1,
        writer_workers=1,
        profile=SimulationProfile(
            frame_reader_latency_ms_min=1.0,
            frame_reader_latency_ms_max=2.0,
            inference_latency_ms_min=2.0,
            inference_latency_ms_max=6.0,
            persistence_latency_ms_min=1.0,
            persistence_latency_ms_max=2.0,
            inference_success_ratio=1.0,
            persistence_success_ratio=1.0,
        ),
        persistence_service=custom,
    )
    runtime.start()
    time.sleep(0.8)
    runtime.stop()

    snapshot = runtime.snapshot()
    assert custom.calls > 0
    assert snapshot["measured_persistence"]["persisted"] > 0


def test_scaling_runtime_blocks_go_when_preflight_ratio_is_low() -> None:
    runtime = ScalingRuntime.build_simulated(
        camera_count=4,
        sample_interval_ms=60,
        frame_queue_maxsize=128,
        result_queue_maxsize=128,
        inference_workers=2,
        writer_workers=1,
        profile=SimulationProfile(
            frame_reader_latency_ms_min=1.0,
            frame_reader_latency_ms_max=2.0,
            inference_latency_ms_min=4.0,
            inference_latency_ms_max=10.0,
            persistence_latency_ms_min=1.0,
            persistence_latency_ms_max=3.0,
            inference_success_ratio=1.0,
            persistence_success_ratio=1.0,
        ),
    )
    thresholds = RuntimeThresholds(
        p95_end_to_end_ms_max=3000.0,
        queue_depth_max=200,
        event_persist_success_min_pct=99.0,
        preflight_ok_ratio_min=0.9,
    )

    runtime.start()
    time.sleep(0.8)
    runtime.stop()

    evaluation = runtime.evaluate(thresholds, preflight_ok_ratio=0.45)
    assert evaluation["verdict"] == "NO-GO_SOURCE_UNSTABLE"
    assert evaluation["criteria"]["preflight_ok_ratio_gte_threshold"] is False


def test_scaling_runtime_simulated_supports_batch_inference_mode() -> None:
    runtime = ScalingRuntime.build_simulated(
        camera_count=5,
        sample_interval_ms=50,
        frame_queue_maxsize=128,
        result_queue_maxsize=128,
        inference_workers=1,
        inference_batch_size=4,
        inference_batch_max_wait_ms=20.0,
        writer_workers=1,
        profile=SimulationProfile(
            frame_reader_latency_ms_min=1.0,
            frame_reader_latency_ms_max=2.0,
            inference_latency_ms_min=4.0,
            inference_latency_ms_max=8.0,
            persistence_latency_ms_min=1.0,
            persistence_latency_ms_max=2.0,
            inference_success_ratio=1.0,
            persistence_success_ratio=1.0,
        ),
    )

    runtime.start()
    time.sleep(0.9)
    runtime.stop()

    snapshot = runtime.snapshot()
    infer_metrics = snapshot["inference_worker"]
    assert infer_metrics["processed"] > 0
    assert infer_metrics["batch_calls"] > 0
    assert infer_metrics["batch_size"] == 4


def test_scaling_runtime_exposes_runtime_health_panel(monkeypatch) -> None:
    monkeypatch.setattr(ScalingRuntime, "_safe_cpu_percent", staticmethod(lambda: 96.0))
    monkeypatch.setattr(ScalingRuntime, "_safe_memory_percent", staticmethod(lambda: 66.0))

    runtime = ScalingRuntime.build_simulated(
        camera_count=3,
        sample_interval_ms=60,
        frame_queue_maxsize=128,
        result_queue_maxsize=128,
        inference_workers=1,
        inference_batch_size=2,
        inference_batch_max_wait_ms=10.0,
        writer_workers=1,
        profile=SimulationProfile(
            frame_reader_latency_ms_min=1.0,
            frame_reader_latency_ms_max=2.0,
            inference_latency_ms_min=3.0,
            inference_latency_ms_max=7.0,
            persistence_latency_ms_min=1.0,
            persistence_latency_ms_max=2.0,
            inference_success_ratio=1.0,
            persistence_success_ratio=1.0,
        ),
    )

    runtime.start()
    time.sleep(0.7)
    runtime.stop()

    panel = runtime.snapshot()["runtime_health_panel"]
    summary = panel["summary"]
    assert panel["status"] == "down"
    assert summary["camera_total"] == 3
    assert summary["cpu_percent"] == 96.0
    assert "frame_queue_util_pct" in summary
    assert "inference_avg_latency_ms" in summary
    assert "persist_success_pct" in summary
    assert len(panel["per_camera"]) == 3


def test_scaling_runtime_simulated_supports_sqlite_queue_backend(tmp_path) -> None:
    queue_db = tmp_path / "scaling_runtime_queue.db"
    runtime = ScalingRuntime.build_simulated(
        camera_count=4,
        sample_interval_ms=70,
        frame_queue_maxsize=128,
        result_queue_maxsize=128,
        queue_backend="sqlite",
        queue_sqlite_path=str(queue_db),
        queue_namespace="pytest_sqlite",
        inference_workers=2,
        writer_workers=1,
        profile=SimulationProfile(
            frame_reader_latency_ms_min=1.0,
            frame_reader_latency_ms_max=2.0,
            inference_latency_ms_min=3.0,
            inference_latency_ms_max=8.0,
            persistence_latency_ms_min=1.0,
            persistence_latency_ms_max=2.0,
            inference_success_ratio=1.0,
            persistence_success_ratio=1.0,
        ),
    )
    thresholds = RuntimeThresholds(
        p95_end_to_end_ms_max=3000.0,
        queue_depth_max=200,
        event_persist_success_min_pct=99.0,
    )

    runtime.start()
    time.sleep(0.9)
    runtime.stop()

    snapshot = runtime.snapshot()
    evaluation = runtime.evaluate(thresholds)
    transport = snapshot["queue_transport"]

    assert snapshot["inference_worker"]["processed"] > 0
    assert snapshot["event_writer_worker"]["processed"] > 0
    assert evaluation["verdict"] == "GO"
    assert transport["backend"] == "sqlite"
    assert transport["sqlite_path"].endswith("scaling_runtime_queue.db")


def test_scaling_runtime_evaluate_fails_when_result_queue_overflows() -> None:
    runtime = ScalingRuntime.build_simulated(
        camera_count=6,
        sample_interval_ms=20,
        frame_queue_maxsize=64,
        result_queue_maxsize=8,
        inference_workers=2,
        writer_workers=1,
        profile=SimulationProfile(
            frame_reader_latency_ms_min=1.0,
            frame_reader_latency_ms_max=2.0,
            inference_latency_ms_min=2.0,
            inference_latency_ms_max=4.0,
            persistence_latency_ms_min=120.0,
            persistence_latency_ms_max=180.0,
            inference_success_ratio=1.0,
            persistence_success_ratio=1.0,
        ),
    )
    thresholds = RuntimeThresholds(
        p95_end_to_end_ms_max=999999.0,
        queue_depth_max=999999,
        queue_overflow_max=0,
        event_persist_success_min_pct=0.0,
    )

    runtime.start()
    time.sleep(1.2)
    runtime.stop()

    evaluation = runtime.evaluate(thresholds)
    assert evaluation["verdict"] == "NO-GO"
    assert evaluation["criteria"]["queue_overflow_lte_threshold"] is False
    assert evaluation["values"]["queue_overflow_total"] > 0
