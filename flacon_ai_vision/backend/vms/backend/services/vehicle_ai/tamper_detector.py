from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    cv2 = None
    _HAS_CV2 = False

logger = logging.getLogger(__name__)


@dataclass
class TamperDetectionResult:
    tamper_detected: bool
    tamper_type: Optional[str]
    severity: str
    confidence: float
    metrics: Dict[str, Any]
    reason: str


class CameraTamperDetector:
    """Simple tamper checks for black/covered/no-signal conditions."""

    def __init__(self):
        self.enabled = self._read_bool("VEHICLE_TAMPER_ENABLE", True)
        self.black_brightness_max = self._read_float("VEHICLE_TAMPER_BLACK_BRIGHTNESS_MAX", 20.0)
        self.black_ratio_min = self._read_float("VEHICLE_TAMPER_BLACK_RATIO_MIN", 0.92)
        self.covered_std_max = self._read_float("VEHICLE_TAMPER_COVERED_STD_MAX", 10.0)
        self.edge_density_min = self._read_float("VEHICLE_TAMPER_EDGE_DENSITY_MIN", 0.005)

    def detect(self, frame_bgr: Optional[np.ndarray]) -> TamperDetectionResult:
        if not self.enabled:
            logger.debug("Camera tamper detector disabled by configuration")
            return TamperDetectionResult(
                tamper_detected=False,
                tamper_type=None,
                severity="low",
                confidence=0.0,
                metrics={"enabled": False},
                reason="disabled",
            )

        if frame_bgr is None or frame_bgr.size == 0:
            logger.warning("Camera tamper detector received an empty frame")
            return TamperDetectionResult(
                tamper_detected=True,
                tamper_type="signal_loss",
                severity="critical",
                confidence=1.0,
                metrics={},
                reason="empty_frame",
            )

        gray = self._to_gray(frame_bgr)
        brightness = float(np.mean(gray))
        black_ratio = float(np.mean(gray <= self.black_brightness_max))
        std_dev = float(np.std(gray))
        edge_density = float(self._edge_density(gray))

        metrics: Dict[str, Any] = {
            "brightness": round(brightness, 4),
            "black_ratio": round(black_ratio, 4),
            "std_dev": round(std_dev, 4),
            "edge_density": round(edge_density, 6),
        }

        if black_ratio >= self.black_ratio_min and brightness <= (self.black_brightness_max + 8):
            confidence = float(max(0.75, min(1.0, black_ratio)))
            logger.info(
                "Camera tamper detected: black_frame brightness=%.2f black_ratio=%.4f",
                brightness,
                black_ratio,
            )
            return TamperDetectionResult(
                tamper_detected=True,
                tamper_type="black_frame",
                severity="critical",
                confidence=confidence,
                metrics=metrics,
                reason="dominant_black_pixels",
            )

        if std_dev <= self.covered_std_max and edge_density <= self.edge_density_min:
            confidence = float(max(0.65, min(0.98, (self.covered_std_max - std_dev + 1.0) / (self.covered_std_max + 1.0))))
            logger.info(
                "Camera tamper detected: camera_covered std_dev=%.4f edge_density=%.6f",
                std_dev,
                edge_density,
            )
            return TamperDetectionResult(
                tamper_detected=True,
                tamper_type="camera_covered",
                severity="critical",
                confidence=confidence,
                metrics=metrics,
                reason="low_texture_low_edges",
            )

        return TamperDetectionResult(
            tamper_detected=False,
            tamper_type=None,
            severity="low",
            confidence=0.0,
            metrics=metrics,
            reason="normal_frame",
        )

    def _to_gray(self, frame_bgr: np.ndarray) -> np.ndarray:
        if _HAS_CV2:
            try:
                return cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            except Exception as exc:
                logger.debug("Tamper detector cv2 grayscale conversion failed, using NumPy fallback: %s", exc)
        if frame_bgr.ndim == 2:
            return frame_bgr.astype(np.uint8)
        return np.mean(frame_bgr, axis=2).astype(np.uint8)

    def _edge_density(self, gray: np.ndarray) -> float:
        if gray.size == 0:
            return 0.0
        if _HAS_CV2:
            try:
                edges = cv2.Canny(gray, 60, 130)
                return float(np.mean(edges > 0))
            except Exception as exc:
                logger.debug("Tamper detector cv2 edge density failed, using NumPy fallback: %s", exc)
        gy, gx = np.gradient(gray.astype(np.float32))
        mag = np.sqrt(gx * gx + gy * gy)
        return float(np.mean(mag > 18.0))

    def _read_bool(self, env_name: str, default: bool) -> bool:
        raw = str(os.getenv(env_name, str(default)) or "").strip().lower()
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        logger.warning("Invalid boolean value for %s=%r, using default=%s", env_name, raw, default)
        return bool(default)

    def _read_float(self, env_name: str, default: float) -> float:
        raw = str(os.getenv(env_name, str(default)) or "").strip()
        try:
            return float(raw)
        except Exception:
            logger.warning("Invalid float value for %s=%r, using default=%s", env_name, raw, default)
            return float(default)
