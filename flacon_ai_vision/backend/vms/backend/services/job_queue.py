from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import threading
import traceback
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


@dataclass
class JobState:
    job_id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class LocalJobQueue:
    """Simple async queue using thread pool (default backend)."""

    def __init__(self, workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="jobq")
        self._jobs: Dict[str, JobState] = {}
        self._lock = threading.Lock()

    def enqueue(self, name: str, func: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> str:
        job_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._jobs[job_id] = JobState(
                job_id=job_id,
                name=name,
                status="queued",
                created_at=now,
                updated_at=now,
            )

        def runner() -> None:
            self._set_status(job_id, "running")
            try:
                payload = func(*args, **kwargs)
                self._set_result(job_id, payload)
            except Exception:
                self._set_error(job_id, traceback.format_exc()[-1200:])

        self._executor.submit(runner)
        return job_id

    def get(self, job_id: str) -> Optional[JobState]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 100, status: Optional[str] = None) -> list[JobState]:
        with self._lock:
            rows = list(self._jobs.values())
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        if status:
            rows = [row for row in rows if row.status == status]
        return rows[: max(1, limit)]

    def _set_status(self, job_id: str, status: str) -> None:
        with self._lock:
            row = self._jobs.get(job_id)
            if row is None:
                return
            row.status = status
            row.updated_at = datetime.now(timezone.utc).isoformat()

    def _set_result(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            row = self._jobs.get(job_id)
            if row is None:
                return
            row.status = "completed"
            row.result = result
            row.updated_at = datetime.now(timezone.utc).isoformat()

    def _set_error(self, job_id: str, error: str) -> None:
        with self._lock:
            row = self._jobs.get(job_id)
            if row is None:
                return
            row.status = "failed"
            row.error = error
            row.updated_at = datetime.now(timezone.utc).isoformat()


class RQJobQueue:
    """Redis-backed queue using rq (optional runtime backend)."""

    def __init__(self, redis_url: str):
        from redis import Redis
        from rq import Queue

        self._queue = Queue(name=os.getenv("ASYNC_QUEUE_NAME", "vehicle-recognition"), connection=Redis.from_url(redis_url))

    def enqueue(self, name: str, func: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> str:
        job = self._queue.enqueue(func, *args, **kwargs, job_timeout=int(os.getenv("ASYNC_QUEUE_JOB_TIMEOUT", "60")))
        return str(job.id)

    def get(self, job_id: str) -> Optional[JobState]:
        from rq.job import Job

        try:
            job = Job.fetch(job_id, connection=self._queue.connection)
        except Exception:
            return None

        status = job.get_status(refresh=True)
        mapped_status = {
            "queued": "queued",
            "started": "running",
            "deferred": "queued",
            "finished": "completed",
            "failed": "failed",
            "stopped": "failed",
            "canceled": "failed",
        }.get(status, status)
        result = job.result if mapped_status == "completed" else None
        error = str(job.exc_info)[-1200:] if mapped_status == "failed" and job.exc_info else None
        created = job.created_at.isoformat() if job.created_at else datetime.now(timezone.utc).isoformat()
        ended = job.ended_at.isoformat() if job.ended_at else datetime.now(timezone.utc).isoformat()
        return JobState(
            job_id=str(job.id),
            name=str(job.func_name or "job"),
            status=mapped_status,
            created_at=created,
            updated_at=ended,
            result=result if isinstance(result, dict) else None,
            error=error,
        )

    def list(self, limit: int = 100, status: Optional[str] = None) -> list[JobState]:
        # Optional backend: provide best-effort listing from the queue.
        from rq.registry import FinishedJobRegistry, StartedJobRegistry, FailedJobRegistry

        rows: list[JobState] = []
        ids: list[str] = []
        ids.extend(self._queue.job_ids[: max(1, limit)])
        ids.extend(StartedJobRegistry(self._queue.name, connection=self._queue.connection).get_job_ids()[: max(1, limit)])
        ids.extend(FinishedJobRegistry(self._queue.name, connection=self._queue.connection).get_job_ids()[: max(1, limit)])
        ids.extend(FailedJobRegistry(self._queue.name, connection=self._queue.connection).get_job_ids()[: max(1, limit)])

        seen = set()
        for job_id in ids:
            if job_id in seen:
                continue
            seen.add(job_id)
            row = self.get(job_id)
            if row is None:
                continue
            if status and row.status != status:
                continue
            rows.append(row)
            if len(rows) >= max(1, limit):
                break
        return rows


_queue_instance: Optional[Any] = None
_queue_lock = threading.Lock()


def get_job_queue():
    global _queue_instance
    if _queue_instance is None:
        with _queue_lock:
            if _queue_instance is None:
                backend = (os.getenv("ASYNC_QUEUE_BACKEND", "local") or "local").strip().lower()
                if backend in {"rq", "redis"}:
                    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
                    try:
                        _queue_instance = RQJobQueue(redis_url=redis_url)
                    except Exception:
                        workers = int(os.getenv("ASYNC_QUEUE_WORKERS", "3"))
                        _queue_instance = LocalJobQueue(workers=workers)
                else:
                    workers = int(os.getenv("ASYNC_QUEUE_WORKERS", "3"))
                    _queue_instance = LocalJobQueue(workers=workers)
    return _queue_instance
