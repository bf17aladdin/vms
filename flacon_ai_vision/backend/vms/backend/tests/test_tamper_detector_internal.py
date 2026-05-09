from __future__ import annotations

import logging

import numpy as np

from vms.backend.services.vehicle_ai.tamper_detector import CameraTamperDetector


def test_tamper_detector_invalid_env_values_fall_back_to_defaults(monkeypatch, caplog) -> None:
    monkeypatch.setenv("VEHICLE_TAMPER_ENABLE", "maybe")
    monkeypatch.setenv("VEHICLE_TAMPER_BLACK_BRIGHTNESS_MAX", "abc")
    monkeypatch.setenv("VEHICLE_TAMPER_BLACK_RATIO_MIN", "xyz")

    with caplog.at_level(logging.WARNING):
        detector = CameraTamperDetector()

    assert detector.enabled is True
    assert detector.black_brightness_max == 20.0
    assert detector.black_ratio_min == 0.92
    assert "Invalid boolean value for VEHICLE_TAMPER_ENABLE" in caplog.text
    assert "Invalid float value for VEHICLE_TAMPER_BLACK_BRIGHTNESS_MAX" in caplog.text


def test_tamper_detector_flags_black_frame() -> None:
    detector = CameraTamperDetector()
    frame = np.zeros((32, 32, 3), dtype=np.uint8)

    result = detector.detect(frame)

    assert result.tamper_detected is True
    assert result.tamper_type == "black_frame"
    assert result.reason == "dominant_black_pixels"
    assert result.confidence >= 0.75


def test_tamper_detector_flags_camera_covered() -> None:
    detector = CameraTamperDetector()
    frame = np.full((48, 48, 3), 180, dtype=np.uint8)

    result = detector.detect(frame)

    assert result.tamper_detected is True
    assert result.tamper_type == "camera_covered"
    assert result.reason == "low_texture_low_edges"


def test_tamper_detector_allows_textured_normal_frame() -> None:
    detector = CameraTamperDetector()
    frame = np.indices((48, 48)).sum(axis=0) % 2
    frame = (frame * 255).astype(np.uint8)
    frame = np.stack([frame, frame, frame], axis=2)

    result = detector.detect(frame)

    assert result.tamper_detected is False
    assert result.tamper_type is None
    assert result.reason == "normal_frame"
