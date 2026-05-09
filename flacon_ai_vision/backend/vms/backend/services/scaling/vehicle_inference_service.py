from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from vms.backend.core.database import SessionLocal
from vms.backend.services.vehicle_ai.vehicle_pipeline import VehicleRecognitionPipeline

from .frame_task_queue import FrameTask


class VehicleInferenceService:
    """
    Isolated inference service.

    The service can run with persist=False to decouple heavy recognition
    from synchronous DB writes. Event persistence can then be delegated to
    a separate async writer worker.
    """

    def __init__(
        self,
        *,
        session_factory: Optional[Callable[[], Session]] = None,
        persist: bool = False,
        save_snapshot: bool = False,
        reuse_thread_local_pipeline: bool = True,
        rebind_db_per_call: bool = False,
    ):
        self.session_factory = session_factory or SessionLocal
        self.persist = bool(persist)
        self.save_snapshot = bool(save_snapshot)
        self.reuse_thread_local_pipeline = bool(reuse_thread_local_pipeline)
        self.rebind_db_per_call = bool(rebind_db_per_call)
        self._lock = threading.RLock()
        self._thread_sessions: dict[int, Session] = {}
        self._thread_pipelines: dict[int, VehicleRecognitionPipeline] = {}

    def infer(self, task: FrameTask) -> dict[str, Any]:
        if self.reuse_thread_local_pipeline:
            if self.rebind_db_per_call:
                db = self.session_factory()
                try:
                    pipeline = self._get_or_create_thread_pipeline(db)
                    return self._infer_with_pipeline(pipeline, task)
                finally:
                    db.close()
            _db, pipeline = self._get_or_create_thread_context()
            return self._infer_with_pipeline(pipeline, task)

        db = self.session_factory()
        try:
            pipeline = VehicleRecognitionPipeline(db)
            return self._infer_with_pipeline(pipeline, task)
        finally:
            db.close()

    def infer_batch(self, tasks: list[FrameTask]) -> list[dict[str, Any]]:
        if not tasks:
            return []

        if self.reuse_thread_local_pipeline:
            if self.rebind_db_per_call:
                db = self.session_factory()
                try:
                    pipeline = self._get_or_create_thread_pipeline(db)
                    return self._infer_batch_with_pipeline(pipeline, tasks)
                finally:
                    db.close()
            _db, pipeline = self._get_or_create_thread_context()
            return self._infer_batch_with_pipeline(pipeline, tasks)

        db = self.session_factory()
        try:
            pipeline = VehicleRecognitionPipeline(db)
            return self._infer_batch_with_pipeline(pipeline, tasks)
        finally:
            db.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._thread_sessions.values())
            self._thread_sessions.clear()
            self._thread_pipelines.clear()
        for db in sessions:
            try:
                db.close()
            except Exception:
                pass

    def _get_or_create_thread_pipeline(self, db: Session) -> VehicleRecognitionPipeline:
        thread_id = int(threading.get_ident())
        with self._lock:
            pipeline = self._thread_pipelines.get(thread_id)
            if pipeline is None:
                pipeline = VehicleRecognitionPipeline(db)
                self._thread_pipelines[thread_id] = pipeline
                return pipeline

            if hasattr(pipeline, "bind_db"):
                pipeline.bind_db(db)
            return pipeline

    def _get_or_create_thread_context(self) -> tuple[Session, VehicleRecognitionPipeline]:
        thread_id = int(threading.get_ident())
        with self._lock:
            db = self._thread_sessions.get(thread_id)
            pipeline = self._thread_pipelines.get(thread_id)
            if db is None or pipeline is None:
                db = self.session_factory()
                pipeline = VehicleRecognitionPipeline(db)
                self._thread_sessions[thread_id] = db
                self._thread_pipelines[thread_id] = pipeline
            return db, pipeline

    def _infer_with_pipeline(
        self,
        pipeline: VehicleRecognitionPipeline,
        task: FrameTask,
    ) -> dict[str, Any]:
        direction = str(task.metadata.get("direction", "IN")).upper()
        gate_id = task.metadata.get("gate_id")
        zone_id = task.metadata.get("zone_id")
        return pipeline.recognize_from_frame(
            frame_bgr=task.frame,
            camera_id=task.camera_id,
            zone_id=zone_id,
            gate_id=gate_id,
            direction=direction,
            persist=self.persist,
            save_snapshot=self.save_snapshot,
            image_bytes=None,
        )

    def _infer_batch_with_pipeline(
        self,
        pipeline: VehicleRecognitionPipeline,
        tasks: list[FrameTask],
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        for task in tasks:
            try:
                outputs.append(self._infer_with_pipeline(pipeline, task))
            except Exception as exc:
                outputs.append(
                    {
                        "success": False,
                        "camera_id": int(task.camera_id),
                        "message": str(exc),
                    }
                )
        return outputs
