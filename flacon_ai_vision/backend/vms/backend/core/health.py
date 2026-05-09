from __future__ import annotations

from datetime import datetime, timezone
import os
import time
from typing import Any

from sqlalchemy import text

from vms.backend.core.database import SessionLocal


def live_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "falcon-ai-vision-backend",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _db_check(timeout_ms: int = 1200) -> dict[str, Any]:
    started = time.perf_counter()
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        latency_ms = (time.perf_counter() - started) * 1000.0
        return {
            "ok": latency_ms <= timeout_ms,
            "latency_ms": round(latency_ms, 2),
            "timeout_ms": timeout_ms,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:240], "timeout_ms": timeout_ms}
    finally:
        db.close()


def _ai_backends() -> dict[str, Any]:
    detector_backend = "unknown"
    ocr_backend = "unknown"
    try:
        from vms.backend.services.vehicle_ai.vehicle_pipeline import VehicleRecognitionPipeline

        probe = VehicleRecognitionPipeline.__new__(VehicleRecognitionPipeline)
        detector, plate_reader, _normalizer = VehicleRecognitionPipeline._get_shared_components()  # type: ignore[attr-defined]
        detector_backend = getattr(detector, "backend", "unknown")
        ocr_backend = getattr(plate_reader, "backend", "unknown")
    except Exception:
        pass
    return {
        "vehicle_detector_backend": detector_backend,
        "plate_ocr_backend": ocr_backend,
        "face_pgvector_enabled": os.getenv("FACE_PGVECTOR_ENABLED", "true").lower() == "true",
    }


def ready_health(timeout_ms: int = 1200) -> dict[str, Any]:
    db_state = _db_check(timeout_ms=timeout_ms)
    ai_state = _ai_backends()
    overall_ok = bool(db_state.get("ok"))
    return {
        "status": "ready" if overall_ok else "degraded",
        "ready": overall_ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "database": db_state,
            "ai": ai_state,
        },
    }
