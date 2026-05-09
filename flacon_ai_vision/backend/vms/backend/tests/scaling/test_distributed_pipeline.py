from __future__ import annotations

import threading
import time

from vms.backend.services.scaling.camera_lease_store import SqliteCameraLeaseStore
from vms.backend.services.scaling.distributed_pipeline import (
    DistributedPipelineConfig,
    DistributedPipelineNode,
)
from vms.backend.services.scaling.frame_task_queue import (
    BoundedTaskQueue,
    FrameTask,
    InferenceResultTask,
)
from vms.backend.services.scaling.scaling_runtime import RuntimeThresholds
from vms.backend.services.scaling.sqlite_task_queue import SqliteTaskQueue


def test_distributed_pipeline_full_role_with_sqlite_backend(tmp_path) -> None:
    queue_db = tmp_path / "distributed_scaling.db"
    node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="full",
            queue_backend="sqlite",
            queue_sqlite_path=str(queue_db),
            queue_namespace="full_node",
            queue_purge_on_start=True,
            camera_count=4,
            sample_interval_ms=60,
            inference_workers=2,
            writer_workers=1,
            persist_target="memory",
        )
    )

    node.start()
    time.sleep(1.0)
    node.stop()

    snapshot = node.snapshot()
    evaluation = node.evaluate(
        RuntimeThresholds(
            p95_end_to_end_ms_max=3000.0,
            queue_depth_max=200,
            event_persist_success_min_pct=0.0,
        )
    )
    assert snapshot["queue_transport"]["backend"] == "sqlite"
    assert snapshot["inference_worker"]["processed"] > 0
    assert snapshot["event_writer_worker"]["processed"] > 0
    assert evaluation["verdict"] in {"GO", "NO-GO"}


def test_distributed_pipeline_split_roles_exchange_via_sqlite(tmp_path) -> None:
    queue_db = tmp_path / "distributed_scaling.db"
    namespace = "split_roles"

    ingestion_node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="ingestion",
            queue_backend="sqlite",
            queue_sqlite_path=str(queue_db),
            queue_namespace=namespace,
            queue_purge_on_start=False,
            camera_count=3,
            sample_interval_ms=50,
        )
    )
    inference_node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="inference",
            queue_backend="sqlite",
            queue_sqlite_path=str(queue_db),
            queue_namespace=namespace,
            queue_purge_on_start=False,
            inference_workers=2,
            inference_batch_size=2,
            inference_batch_max_wait_ms=10.0,
        )
    )
    writer_node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="writer",
            queue_backend="sqlite",
            queue_sqlite_path=str(queue_db),
            queue_namespace=namespace,
            queue_purge_on_start=False,
            writer_workers=1,
            persist_target="memory",
        )
    )

    inference_node.start()
    writer_node.start()
    ingestion_node.start()
    time.sleep(1.5)
    ingestion_node.stop()
    inference_node.stop()
    writer_node.stop()

    ingestion_snapshot = ingestion_node.snapshot()
    inference_snapshot = inference_node.snapshot()
    writer_snapshot = writer_node.snapshot()

    assert ingestion_snapshot["ingestion"]["service"]["registered_cameras"] == 3
    assert ingestion_snapshot["ingestion"]["per_camera"][1]["frames_enqueued"] > 0
    assert inference_snapshot["inference_worker"]["processed"] > 0
    assert writer_snapshot["event_writer_worker"]["processed"] > 0
    assert writer_snapshot["measured_persistence"]["persisted"] > 0
    assert writer_snapshot["queue_transport"]["backend"] == "sqlite"


def test_distributed_pipeline_exposes_dead_letter_snapshot_when_enabled() -> None:
    node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="full",
            queue_backend="memory",
            camera_count=3,
            sample_interval_ms=40,
            inference_workers=1,
            writer_workers=1,
            persist_target="memory",
            inference_success_ratio=0.0,
            dead_letter_backend="memory",
        )
    )

    node.start()
    time.sleep(0.9)
    node.stop()

    snapshot = node.snapshot()
    assert "dead_letters" in snapshot
    assert snapshot["dead_letters"]["backend"] == "memory"
    assert snapshot["dead_letters"]["total"] > 0
    assert snapshot["inference_worker"]["dead_lettered"] > 0
    assert snapshot["event_writer_worker"]["dead_lettered"] > 0


def test_distributed_pipeline_evaluate_uses_result_queue_depth_for_backpressure() -> None:
    frame_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=256)
    result_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=256)
    for seq in range(1, 65):
        result_queue.put(
            InferenceResultTask(
                camera_id=1,
                source="sim://camera/1",
                captured_at="2026-02-24T00:00:00+00:00",
                produced_at="2026-02-24T00:00:00+00:00",
                sequence=seq,
                success=True,
                payload={"camera_id": 1},
            )
        )

    node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="writer",
            queue_backend="memory",
            writer_workers=1,
            persist_target="memory",
        ),
        frame_queue=frame_queue,
        result_queue=result_queue,
    )

    evaluation = node.evaluate(
        RuntimeThresholds(
            p95_end_to_end_ms_max=3000.0,
            queue_depth_max=10,
            queue_overflow_max=999999,
            event_persist_success_min_pct=0.0,
        )
    )
    assert evaluation["verdict"] == "NO-GO"
    assert evaluation["criteria"]["queue_depth_lt_threshold"] is False
    assert evaluation["values"]["queue_depth_high_watermark"] >= 64


def test_distributed_pipeline_evaluate_fails_when_queue_overflow_detected() -> None:
    frame_queue: BoundedTaskQueue[FrameTask] = BoundedTaskQueue(maxsize=8)
    result_queue: BoundedTaskQueue[InferenceResultTask] = BoundedTaskQueue(maxsize=2)
    for seq in range(1, 7):
        result_queue.put(
            InferenceResultTask(
                camera_id=1,
                source="sim://camera/1",
                captured_at="2026-02-24T00:00:00+00:00",
                produced_at="2026-02-24T00:00:00+00:00",
                sequence=seq,
                success=True,
                payload={"camera_id": 1},
            )
        )

    node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="writer",
            queue_backend="memory",
            writer_workers=1,
            persist_target="memory",
        ),
        frame_queue=frame_queue,
        result_queue=result_queue,
    )

    evaluation = node.evaluate(
        RuntimeThresholds(
            p95_end_to_end_ms_max=3000.0,
            queue_depth_max=200,
            queue_overflow_max=0,
            event_persist_success_min_pct=0.0,
        )
    )
    assert evaluation["verdict"] == "NO-GO"
    assert evaluation["criteria"]["queue_overflow_lte_threshold"] is False
    assert evaluation["values"]["queue_overflow_total"] > 0


def test_distributed_pipeline_resilience_supervisor_self_heals_components() -> None:
    node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="full",
            queue_backend="memory",
            camera_count=2,
            sample_interval_ms=40,
            inference_workers=2,
            writer_workers=2,
            persist_target="memory",
            resilience_supervisor_enabled=True,
            resilience_supervisor_interval_sec=0.05,
            resilience_restart_cooldown_sec=0.01,
            resilience_max_restarts_per_component=20,
        )
    )

    node.start()
    time.sleep(0.15)

    assert node.ingestion_service is not None
    assert node.inference_worker is not None
    assert node.event_writer_worker is not None

    with node.ingestion_service._lock:
        cam_id = next(iter(node.ingestion_service._threads.keys()))
        node.ingestion_service._threads[cam_id] = threading.Thread(target=lambda: None, daemon=True)

    with node.inference_worker._lock:
        node.inference_worker._threads = [threading.Thread(target=lambda: None, daemon=True)]

    with node.event_writer_worker._lock:
        node.event_writer_worker._threads = [threading.Thread(target=lambda: None, daemon=True)]

    time.sleep(0.25)
    node.stop()

    snap = node.snapshot()
    resilience = snap["resilience"]
    assert resilience["enabled"] is True
    assert resilience["restarts_total"] >= 3
    assert resilience["restarts"]["ingestion"] >= 1
    assert resilience["restarts"]["inference"] >= 1
    assert resilience["restarts"]["writer"] >= 1


def test_distributed_pipeline_exposes_runtime_tuning_for_sticky_inference() -> None:
    node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="inference",
            queue_backend="memory",
            camera_count=3,
            inference_workers=4,
            inference_batch_size=4,
            frame_queue_maxsize=128,
            inference_sticky_by_camera=True,
        )
    )

    snapshot = node.snapshot()
    tuning = snapshot["runtime_tuning"]
    worker = snapshot["inference_worker"]

    assert tuning["effective_inference_batch_size"] == 1
    assert tuning["inference_local_queue_maxsize"] <= 128
    assert worker["batch_size"] == 1
    assert worker["sticky_by_camera"] is True


def test_distributed_pipeline_ingestion_failover_reclaims_expired_camera_leases(tmp_path) -> None:
    queue_db = tmp_path / "distributed_failover.db"
    lease_namespace = "failover_leases"
    stale_owner = SqliteCameraLeaseStore(
        db_path=str(queue_db),
        namespace=lease_namespace,
        owner_id="dead-worker",
        owner_role="ingestion",
        lease_ttl_sec=0.15,
    )
    stale_owner.claim_or_renew(1, owner_metadata={"camera": 1})

    node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="ingestion",
            queue_backend="sqlite",
            queue_sqlite_path=str(queue_db),
            queue_namespace="failover_queue",
            queue_purge_on_start=True,
            camera_count=1,
            sample_interval_ms=20,
            camera_ownership_backend="sqlite",
            camera_ownership_sqlite_path=str(queue_db),
            camera_ownership_namespace=lease_namespace,
            camera_ownership_lease_ttl_sec=0.15,
            camera_ownership_heartbeat_interval_sec=0.03,
            resilience_supervisor_enabled=True,
            resilience_supervisor_interval_sec=0.05,
            resilience_restart_cooldown_sec=0.01,
            resilience_max_restarts_per_component=20,
        )
    )

    node.start()
    try:
        time.sleep(0.05)
        first_snapshot = node.snapshot()
        assert first_snapshot["ingestion"]["service"]["active_threads"] == 0
        assert first_snapshot["ingestion"]["per_camera"][1]["ownership"]["status"] == "standby"

        deadline = time.time() + 1.0
        recovered_snapshot = first_snapshot
        while time.time() < deadline:
            recovered_snapshot = node.snapshot()
            if recovered_snapshot["ingestion"]["per_camera"][1]["frames_enqueued"] > 0:
                break
            time.sleep(0.05)
    finally:
        node.stop()

    assert recovered_snapshot["ingestion"]["service"]["active_threads"] >= 1
    assert recovered_snapshot["ingestion"]["per_camera"][1]["frames_enqueued"] > 0
    assert recovered_snapshot["ingestion"]["per_camera"][1]["ownership"]["status"] == "owned"
    assert recovered_snapshot["camera_ownership"]["active_leases_count"] == 1
    assert recovered_snapshot["camera_ownership"]["active_leases"][0]["owner_id"] == node.config.camera_ownership_owner_id


def test_distributed_pipeline_inference_failover_reclaims_expired_partition_lease(tmp_path) -> None:
    queue_db = tmp_path / "distributed_inference_failover.db"
    lease_namespace = "inference_partition_leases"

    stale_owner = SqliteCameraLeaseStore(
        db_path=str(queue_db),
        namespace=lease_namespace,
        owner_id="dead-inference-worker",
        owner_role="inference",
        lease_ttl_sec=0.15,
    )
    stale_owner.claim_or_renew(1, owner_metadata={"partition": 0})

    preload_queue = SqliteTaskQueue[FrameTask](
        db_path=str(queue_db),
        topic="inference_failover_frame",
        maxsize=16,
        purge_on_start=True,
    )
    preload_queue.put(
        FrameTask(
            camera_id=1,
            source="sim://camera/1",
            frame={"frame": 1},
            captured_at="2026-02-24T00:00:00+00:00",
            sequence=1,
            metadata={"direction": "IN"},
        ),
        dedupe_key="camera:1",
    )

    node = DistributedPipelineNode(
        config=DistributedPipelineConfig(
            role="inference",
            queue_backend="sqlite",
            queue_sqlite_path=str(queue_db),
            queue_namespace="inference_failover",
            queue_purge_on_start=False,
            inference_mode="simulated",
            inference_workers=2,
            inference_sticky_by_camera=True,
            inference_partition_count=1,
            inference_partition_index=0,
            inference_ownership_backend="sqlite",
            inference_ownership_sqlite_path=str(queue_db),
            inference_ownership_namespace=lease_namespace,
            inference_ownership_lease_ttl_sec=0.15,
            inference_ownership_heartbeat_interval_sec=0.03,
            resilience_supervisor_enabled=True,
            resilience_supervisor_interval_sec=0.05,
            resilience_restart_cooldown_sec=0.01,
            resilience_max_restarts_per_component=20,
        )
    )

    node.start()
    try:
        first_snapshot = node.snapshot()
        initial_deadline = time.time() + 0.30
        while time.time() < initial_deadline:
            first_snapshot = node.snapshot()
            if first_snapshot["inference_worker"]["ownership"]["status"] == "standby":
                break
            time.sleep(0.02)
        assert first_snapshot["inference_worker"]["processed"] == 0
        assert first_snapshot["inference_worker"]["ownership"]["status"] == "standby"

        deadline = time.time() + 1.5
        recovered_snapshot = first_snapshot
        while time.time() < deadline:
            recovered_snapshot = node.snapshot()
            if recovered_snapshot["inference_worker"]["processed"] > 0:
                break
            time.sleep(0.05)
    finally:
        node.stop()

    assert recovered_snapshot["inference_worker"]["processed"] > 0
    assert recovered_snapshot["inference_worker"]["ownership"]["status"] == "owned"
    assert recovered_snapshot["result_queue"]["size"] > 0
    assert recovered_snapshot["inference_ownership"]["active_leases_count"] == 1
    assert recovered_snapshot["inference_ownership"]["active_leases"][0]["owner_id"] == node.config.inference_ownership_owner_id
