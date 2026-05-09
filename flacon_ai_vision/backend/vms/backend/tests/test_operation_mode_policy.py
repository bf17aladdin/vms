from __future__ import annotations

from types import SimpleNamespace

import pytest

from vms.backend.services.operation_mode_manager import (
    CAMERA_PROFILE_POLICIES,
    ProductionLiveRuntime,
    _infer_camera_profile,
    _normalize_profile_overrides,
)


def test_profile_override_normalization_rejects_invalid_profile() -> None:
    with pytest.raises(ValueError):
        _normalize_profile_overrides({1: "invalid_profile"})


def test_infer_camera_profile_prefers_override() -> None:
    camera = SimpleNamespace(
        id=5,
        camera_type="mix",
        name="Front Gate",
        description=None,
        location=None,
        zone_name=None,
        pan_tilt_zoom_capable=False,
    )
    profile = _infer_camera_profile(camera, default_profile="fixed_medium", overrides={5: "panoramic"})
    assert profile == "panoramic"


def test_infer_camera_profile_detects_ptz_flag() -> None:
    camera = SimpleNamespace(
        id=9,
        camera_type="mix",
        name="PTZ Tower",
        description=None,
        location=None,
        zone_name=None,
        pan_tilt_zoom_capable=True,
    )
    profile = _infer_camera_profile(camera, default_profile="fixed_medium", overrides={})
    assert profile == "ptz"


def test_resolve_sample_interval_strict_validation_raises() -> None:
    policy = CAMERA_PROFILE_POLICIES["fixed_medium"]
    with pytest.raises(ValueError):
        ProductionLiveRuntime._resolve_sample_interval_ms(
            requested_ms=5000,
            policy=policy,
            enforce_profiles=True,
            strict=True,
        )


def test_resolve_sample_interval_non_strict_clamps() -> None:
    policy = CAMERA_PROFILE_POLICIES["fixed_high"]
    resolved = ProductionLiveRuntime._resolve_sample_interval_ms(
        requested_ms=120,
        policy=policy,
        enforce_profiles=True,
        strict=False,
    )
    assert resolved == policy.min_sample_interval_ms

