from __future__ import annotations

import logging

import numpy as np

from vms.backend.services.face_ai.face_detector import FaceDetector
from vms.backend.services.vehicle_ai.lprnet_adapter import LPRNetAdapter, LPRNetDecodeResult
from vms.backend.services.vehicle_ai.plate_reader import PlateReader


def test_face_detector_logs_insightface_failure(caplog) -> None:
    detector = FaceDetector.__new__(FaceDetector)
    detector.min_face_size = 40

    class _BrokenApp:
        def get(self, _image, max_num=0):
            raise RuntimeError(f"insightface unavailable for max_num={max_num}")

    detector.app = _BrokenApp()

    with caplog.at_level(logging.DEBUG):
        detections = detector._detect_with_insightface(
            np.zeros((32, 32, 3), dtype=np.uint8),
            max_faces=2,
        )

    assert detections == []
    assert "InsightFace detection failed" in caplog.text


def test_plate_reader_logs_lprnet_variant_failure_and_keeps_candidate(caplog) -> None:
    reader = PlateReader.__new__(PlateReader)
    reader.lprnet_max_variants = 3
    reader.ocr_conf_threshold = 0.15
    reader.min_plate_chars = 4
    reader.min_plate_digits = 2

    class _FlakyLprnetReader:
        def __init__(self):
            self.calls = 0

        def decode(self, _img):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("bad preprocessing variant")
            return LPRNetDecodeResult(text="123 TN 4567", confidence=0.91)

    reader.lprnet_reader = _FlakyLprnetReader()

    variants = [
        np.zeros((8, 16, 3), dtype=np.uint8),
        np.ones((8, 16, 3), dtype=np.uint8),
    ]

    with caplog.at_level(logging.DEBUG):
        candidates = reader._read_with_lprnet(variants)

    assert len(candidates) == 1
    assert candidates[0]["source"] == "lprnet"
    assert candidates[0]["text"] == "123 TN 4567"
    assert "LPRNet decode failed on a preprocessing variant" in caplog.text


def test_lprnet_adapter_logs_import_failure(caplog) -> None:
    adapter = LPRNetAdapter.__new__(LPRNetAdapter)

    with caplog.at_level(logging.DEBUG):
        module = adapter._safe_import("definitely_missing_lprnet_module_for_test")

    assert module is None
    assert "Unable to import LPRNet module" in caplog.text


def test_plate_reader_easyocr_fallback_languages_avoid_duplicate_retry() -> None:
    reader = PlateReader.__new__(PlateReader)

    assert reader._resolve_easyocr_fallback_languages(["ar", "en"]) == ["en"]
    assert reader._resolve_easyocr_fallback_languages(["en"]) is None
    assert reader._resolve_easyocr_fallback_languages(["fr"]) == ["en"]
