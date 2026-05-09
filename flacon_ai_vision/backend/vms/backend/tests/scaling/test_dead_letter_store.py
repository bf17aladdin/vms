from __future__ import annotations

from vms.backend.services.scaling.dead_letter_store import (
    DeadLetterRecord,
    InMemoryDeadLetterStore,
    SqliteDeadLetterStore,
)


def test_in_memory_dead_letter_store_tracks_totals_and_categories() -> None:
    store = InMemoryDeadLetterStore()
    store.write(
        DeadLetterRecord(
            category="inference_failed",
            reason="forced_failure",
            payload={"ok": False},
            camera_id=1,
            sequence=10,
            source="sim://cam1",
        )
    )
    store.write(
        DeadLetterRecord(
            category="writer_persist_failed",
            reason="db_down",
            payload={"ok": False},
            camera_id=1,
            sequence=10,
            source="sim://cam1",
        )
    )

    snapshot = store.snapshot(limit=10)
    assert snapshot["backend"] == "memory"
    assert snapshot["total"] == 2
    assert snapshot["by_category"]["inference_failed"] == 1
    assert snapshot["by_category"]["writer_persist_failed"] == 1
    assert len(snapshot["recent"]) == 2


def test_sqlite_dead_letter_store_isolated_by_namespace(tmp_path) -> None:
    db_path = tmp_path / "dead_letters.db"
    store_a = SqliteDeadLetterStore(db_path=str(db_path), namespace="ns_a")
    store_b = SqliteDeadLetterStore(db_path=str(db_path), namespace="ns_b")

    store_a.write(
        DeadLetterRecord(
            category="inference_failed",
            reason="cam_disconnected",
            payload={"camera": 1},
            camera_id=1,
            sequence=11,
            source="sim://cam1",
        )
    )
    store_b.write(
        DeadLetterRecord(
            category="writer_skipped_inference_failure",
            reason="inference_failed",
            payload={"camera": 2},
            camera_id=2,
            sequence=22,
            source="sim://cam2",
        )
    )

    snap_a = store_a.snapshot(limit=10)
    snap_b = store_b.snapshot(limit=10)
    assert snap_a["backend"] == "sqlite"
    assert snap_a["namespace"] == "ns_a"
    assert snap_a["total"] == 1
    assert snap_a["by_category"]["inference_failed"] == 1
    assert snap_b["namespace"] == "ns_b"
    assert snap_b["total"] == 1
    assert snap_b["by_category"]["writer_skipped_inference_failure"] == 1
