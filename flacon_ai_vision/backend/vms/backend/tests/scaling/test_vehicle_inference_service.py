from __future__ import annotations

from vms.backend.services.scaling.frame_task_queue import FrameTask
from vms.backend.services.scaling.vehicle_inference_service import VehicleInferenceService
import vms.backend.services.scaling.vehicle_inference_service as inference_module


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0

    def close(self) -> None:
        self.closed = True
        self.close_calls += 1


class _FakePipeline:
    def __init__(self, db) -> None:
        self.db = db
        self.bound_dbs = [db]

    def bind_db(self, db) -> None:
        self.db = db
        self.bound_dbs.append(db)

    def recognize_from_frame(self, **kwargs):
        return {
            "success": True,
            "camera_id": kwargs.get("camera_id"),
            "persist": kwargs.get("persist"),
            "save_snapshot": kwargs.get("save_snapshot"),
        }


def test_inference_service_delegates_to_pipeline(monkeypatch) -> None:
    fake_session = _FakeSession()
    monkeypatch.setattr(inference_module, "VehicleRecognitionPipeline", _FakePipeline)

    service = VehicleInferenceService(
        session_factory=lambda: fake_session,
        persist=False,
        save_snapshot=False,
        reuse_thread_local_pipeline=False,
    )
    task = FrameTask(
        camera_id=99,
        source="0",
        frame={"dummy": True},
        captured_at="2026-02-24T00:00:00+00:00",
        sequence=1,
        metadata={"direction": "IN"},
    )

    payload = service.infer(task)
    assert payload["success"] is True
    assert payload["camera_id"] == 99
    assert payload["persist"] is False
    assert fake_session.closed is True


def test_inference_service_reuses_thread_local_pipeline_until_close_all(monkeypatch) -> None:
    sessions: list[_FakeSession] = []
    monkeypatch.setattr(inference_module, "VehicleRecognitionPipeline", _FakePipeline)

    def _factory() -> _FakeSession:
        session = _FakeSession()
        sessions.append(session)
        return session

    service = VehicleInferenceService(
        session_factory=_factory,
        persist=False,
        save_snapshot=False,
        reuse_thread_local_pipeline=True,
    )
    task = FrameTask(
        camera_id=42,
        source="0",
        frame={"dummy": True},
        captured_at="2026-02-24T00:00:00+00:00",
        sequence=1,
        metadata={"direction": "IN"},
    )

    payload1 = service.infer(task)
    payload2 = service.infer(task)
    assert payload1["success"] is True
    assert payload2["success"] is True
    assert len(sessions) == 1
    assert sessions[0].closed is False

    service.close_all()
    assert sessions[0].closed is True
    assert sessions[0].close_calls == 1


def test_inference_service_reuses_pipeline_state_with_short_lived_sessions(monkeypatch) -> None:
    sessions: list[_FakeSession] = []
    pipelines: list[_FakePipeline] = []

    class _BindingPipeline(_FakePipeline):
        def __init__(self, db) -> None:
            super().__init__(db)
            pipelines.append(self)

    monkeypatch.setattr(inference_module, "VehicleRecognitionPipeline", _BindingPipeline)

    def _factory() -> _FakeSession:
        session = _FakeSession()
        sessions.append(session)
        return session

    service = VehicleInferenceService(
        session_factory=_factory,
        persist=False,
        save_snapshot=False,
        reuse_thread_local_pipeline=True,
        rebind_db_per_call=True,
    )
    task = FrameTask(
        camera_id=7,
        source="0",
        frame={"dummy": True},
        captured_at="2026-02-24T00:00:00+00:00",
        sequence=1,
        metadata={"direction": "IN"},
    )

    payload1 = service.infer(task)
    payload2 = service.infer(task)

    assert payload1["success"] is True
    assert payload2["success"] is True
    assert len(sessions) == 2
    assert all(session.closed for session in sessions)
    assert len(pipelines) == 1
    assert len(pipelines[0].bound_dbs) >= 2


def test_inference_service_infer_batch_reuses_single_session(monkeypatch) -> None:
    sessions: list[_FakeSession] = []
    monkeypatch.setattr(inference_module, "VehicleRecognitionPipeline", _FakePipeline)

    def _factory() -> _FakeSession:
        session = _FakeSession()
        sessions.append(session)
        return session

    service = VehicleInferenceService(
        session_factory=_factory,
        persist=False,
        save_snapshot=False,
        reuse_thread_local_pipeline=True,
    )
    tasks = [
        FrameTask(
            camera_id=50 + i,
            source="0",
            frame={"dummy": True},
            captured_at="2026-02-24T00:00:00+00:00",
            sequence=i + 1,
            metadata={"direction": "IN"},
        )
        for i in range(3)
    ]

    outputs = service.infer_batch(tasks)
    assert len(outputs) == 3
    assert all(bool(item.get("success")) for item in outputs)
    assert len(sessions) == 1
    assert sessions[0].closed is False

    service.close_all()
    assert sessions[0].closed is True
