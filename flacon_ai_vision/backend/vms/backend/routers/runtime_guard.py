from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from vms.backend.services.operation_mode_manager import get_operation_mode_manager


def get_manual_inference_guard_status() -> Dict[str, Any]:
    manager = get_operation_mode_manager()
    status = manager.status()
    mode = str(status.get("mode") or "development").lower()
    runtime = status.get("production_runtime") or {}
    running = bool(runtime.get("running", False))
    allowed = mode != "production"
    message = (
        "Manual inference blocked: production runtime is active. "
        "Use Live Stream global runtime and consume persisted events."
        if not allowed
        else "Manual inference allowed."
    )
    return {
        "allowed": bool(allowed),
        "mode": mode,
        "production_runtime_running": running,
        "message": message,
    }


def ensure_manual_inference_allowed(operation: str) -> None:
    guard = get_manual_inference_guard_status()
    if bool(guard.get("allowed", True)):
        return
    detail = {
        "code": "MANUAL_INFERENCE_BLOCKED",
        "operation": str(operation),
        **guard,
    }
    raise HTTPException(status_code=409, detail=detail)

