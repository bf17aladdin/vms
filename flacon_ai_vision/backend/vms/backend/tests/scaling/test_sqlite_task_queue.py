from __future__ import annotations

from vms.backend.services.scaling.sqlite_task_queue import SqliteTaskQueue


def test_sqlite_task_queue_dedupe_keeps_latest_item(tmp_path) -> None:
    db_path = tmp_path / "scaling_queue.db"
    queue = SqliteTaskQueue[dict](
        db_path=str(db_path),
        topic="frames",
        maxsize=16,
        purge_on_start=True,
    )

    assert queue.put({"seq": 1}, dedupe_key="camera:1") is True
    assert queue.put({"seq": 2}, dedupe_key="camera:1") is True

    snap = queue.snapshot()
    assert snap["size"] == 1
    assert snap["dropped_replaced"] >= 1
    item = queue.get(timeout=0.2)
    assert item is not None
    assert item["seq"] == 2


def test_sqlite_task_queue_overflow_drops_oldest(tmp_path) -> None:
    db_path = tmp_path / "scaling_queue.db"
    queue = SqliteTaskQueue[dict](
        db_path=str(db_path),
        topic="frames",
        maxsize=2,
        purge_on_start=True,
    )

    queue.put({"seq": 1})
    queue.put({"seq": 2})
    queue.put({"seq": 3})

    snap = queue.snapshot()
    assert snap["size"] == 2
    assert snap["dropped_overflow"] >= 1

    first = queue.get(timeout=0.2)
    second = queue.get(timeout=0.2)
    assert first is not None and second is not None
    assert first["seq"] == 2
    assert second["seq"] == 3


def test_sqlite_task_queue_allows_cross_instance_exchange(tmp_path) -> None:
    db_path = tmp_path / "scaling_queue.db"
    producer = SqliteTaskQueue[dict](
        db_path=str(db_path),
        topic="results",
        maxsize=8,
        purge_on_start=True,
    )
    consumer = SqliteTaskQueue[dict](
        db_path=str(db_path),
        topic="results",
        maxsize=8,
        purge_on_start=False,
    )

    assert producer.put({"camera_id": 5, "ok": True}) is True
    payload = consumer.get(timeout=0.5)
    assert payload is not None
    assert payload["camera_id"] == 5
    assert payload["ok"] is True
