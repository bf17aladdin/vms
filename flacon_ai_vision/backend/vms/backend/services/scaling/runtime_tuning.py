from __future__ import annotations

from hashlib import blake2b
from math import ceil


DEFAULT_INFERENCE_HEARTBEAT_SEC = 2.0
DEFAULT_INFERENCE_LEASE_TTL_SEC = 8.0


def stable_bucket_for_camera(camera_id: int, bucket_count: int, *, salt: str = "") -> int:
    buckets = max(1, int(bucket_count))
    if buckets <= 1:
        return 0

    key = _stable_hash_u64(f"{salt}:{int(camera_id)}")
    return _jump_consistent_hash(key, buckets)


def estimate_cameras_per_inference_worker(
    *,
    camera_count: int,
    inference_partition_count: int,
    inference_workers: int,
) -> int:
    partitions = max(1, int(inference_partition_count))
    workers = max(1, int(inference_workers))
    cameras = max(1, int(camera_count))
    per_partition = max(1, int(ceil(cameras / partitions)))
    return max(1, int(ceil(per_partition / workers)))


def resolve_effective_inference_batch_size(
    *,
    configured_batch_size: int,
    camera_count: int,
    inference_partition_count: int,
    inference_workers: int,
    sticky_by_camera: bool,
) -> int:
    configured = max(1, int(configured_batch_size))
    if not sticky_by_camera:
        return configured

    cameras_per_worker = estimate_cameras_per_inference_worker(
        camera_count=camera_count,
        inference_partition_count=inference_partition_count,
        inference_workers=inference_workers,
    )
    return max(1, min(configured, cameras_per_worker))


def resolve_inference_local_queue_maxsize(
    *,
    configured_local_queue_maxsize: int,
    frame_queue_maxsize: int,
    camera_count: int,
    inference_partition_count: int,
    inference_workers: int,
    effective_batch_size: int,
) -> int:
    override = int(configured_local_queue_maxsize or 0)
    if override > 0:
        return max(16, override)

    cameras_per_worker = estimate_cameras_per_inference_worker(
        camera_count=camera_count,
        inference_partition_count=inference_partition_count,
        inference_workers=inference_workers,
    )
    recommended = max(
        16,
        int(cameras_per_worker * max(2, int(effective_batch_size))),
        int(max(1, int(effective_batch_size)) * 2),
    )
    return min(max(16, int(frame_queue_maxsize)), recommended)


def resolve_effective_inference_heartbeat_interval_sec(
    *,
    configured_heartbeat_interval_sec: float,
    sample_interval_ms: int,
    camera_count: int,
    inference_partition_count: int,
    inference_workers: int,
) -> float:
    configured = float(configured_heartbeat_interval_sec)
    if abs(configured - DEFAULT_INFERENCE_HEARTBEAT_SEC) > 1e-9:
        return max(0.1, configured)

    sample_interval_sec = max(0.05, float(sample_interval_ms) / 1000.0)
    cameras_per_worker = estimate_cameras_per_inference_worker(
        camera_count=camera_count,
        inference_partition_count=inference_partition_count,
        inference_workers=inference_workers,
    )
    load_scale = 1.0 + min(2.0, max(0.0, float(cameras_per_worker - 1)) * 0.10)
    recommended = max(0.5, min(1.5, sample_interval_sec * 2.5 * load_scale))
    return round(recommended, 3)


def resolve_effective_inference_lease_ttl_sec(
    *,
    configured_lease_ttl_sec: float,
    effective_heartbeat_interval_sec: float,
    camera_count: int,
    inference_partition_count: int,
    inference_workers: int,
    effective_batch_size: int,
) -> float:
    configured = float(configured_lease_ttl_sec)
    if abs(configured - DEFAULT_INFERENCE_LEASE_TTL_SEC) > 1e-9:
        return max(0.2, configured)

    cameras_per_worker = estimate_cameras_per_inference_worker(
        camera_count=camera_count,
        inference_partition_count=inference_partition_count,
        inference_workers=inference_workers,
    )
    load_margin = min(2.0, max(0.0, float(cameras_per_worker - 1)) * 0.25)
    batch_margin = min(1.0, max(0.0, float(max(1, int(effective_batch_size)) - 1)) * 0.15)
    recommended = max(2.0, float(effective_heartbeat_interval_sec) * 3.0 + load_margin + batch_margin)
    return round(recommended, 3)


def _stable_hash_u64(value: str) -> int:
    digest = blake2b(str(value).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def _jump_consistent_hash(key: int, buckets: int) -> int:
    b = -1
    j = 0
    while j < buckets:
        b = j
        key = ((key * 2862933555777941757) + 1) & 0xFFFFFFFFFFFFFFFF
        j = int((b + 1) * (1 << 31) / ((key >> 33) + 1))
    return int(b)
