from __future__ import annotations

import pytest
from fastapi import HTTPException

from vms.backend.routers import runtime_guard


class _DummyManager:
    def __init__(self, *, mode: str, running: bool) -> None:
        self._mode = str(mode)
        self._running = bool(running)

    def status(self):
        return {
            "mode": self._mode,
            "production_runtime": {
                "running": self._running,
            },
        }


def test_manual_inference_guard_allows_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime_guard,
        "get_operation_mode_manager",
        lambda: _DummyManager(mode="development", running=False),
    )

    payload = runtime_guard.get_manual_inference_guard_status()
    assert payload["allowed"] is True
    assert payload["mode"] == "development"


def test_manual_inference_guard_blocks_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runtime_guard,
        "get_operation_mode_manager",
        lambda: _DummyManager(mode="production", running=True),
    )

    payload = runtime_guard.get_manual_inference_guard_status()
    assert payload["allowed"] is False
    assert payload["production_runtime_running"] is True

    with pytest.raises(HTTPException) as exc:
        runtime_guard.ensure_manual_inference_allowed("unit_test")

    assert exc.value.status_code == 409
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail.get("code") == "MANUAL_INFERENCE_BLOCKED"

