from __future__ import annotations

import time

from vms.backend.services.scaling.camera_lease_store import SqliteCameraLeaseStore


def test_sqlite_camera_lease_store_supports_failover_after_expiry(tmp_path) -> None:
    lease_db = tmp_path / "camera_leases.db"
    store_a = SqliteCameraLeaseStore(
        db_path=str(lease_db),
        namespace="lease_failover",
        owner_id="owner-a",
        owner_role="ingestion",
        lease_ttl_sec=0.15,
    )
    store_b = SqliteCameraLeaseStore(
        db_path=str(lease_db),
        namespace="lease_failover",
        owner_id="owner-b",
        owner_role="ingestion",
        lease_ttl_sec=0.15,
    )

    first = store_a.claim_or_renew(101, owner_metadata={"camera": 101})
    blocked = store_b.claim_or_renew(101, owner_metadata={"camera": 101})
    time.sleep(0.20)
    takeover = store_b.claim_or_renew(101, owner_metadata={"camera": 101})

    assert first.claimed is True
    assert first.owner_id == "owner-a"
    assert blocked.claimed is False
    assert blocked.owner_id == "owner-a"
    assert takeover.claimed is True
    assert takeover.owner_id == "owner-b"

    snapshot = store_b.snapshot()
    assert snapshot["active_leases_count"] == 1
    assert snapshot["active_leases"][0]["owner_id"] == "owner-b"
