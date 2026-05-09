from __future__ import annotations

import colorsys
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np


@dataclass
class VehicleProfilePrediction:
    vehicle_type: str
    body_style: str
    model_hint: str
    make_hint: str
    dominant_color: str
    confidence: float
    aspect_ratio: Optional[float]
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vehicle_type": self.vehicle_type,
            "body_style": self.body_style,
            "model_hint": self.model_hint,
            "make_hint": self.make_hint,
            "dominant_color": self.dominant_color,
            "confidence": round(float(max(0.0, min(1.0, self.confidence))), 3),
            "aspect_ratio": round(float(self.aspect_ratio), 3) if self.aspect_ratio is not None else None,
            "source": self.source,
        }


class LightVehicleProfileClassifier:
    """
    Lightweight vehicle profile classifier.
    - type/body/model hint from detector class + box geometry
    - dominant color from ROI statistics (no heavy dependency)
    """

    def predict(
        self,
        *,
        class_name: Optional[str],
        bbox: Optional[Tuple[int, int, int, int]],
        frame_bgr: Optional[np.ndarray] = None,
    ) -> VehicleProfilePrediction:
        ratio = None
        if bbox is not None:
            _x, _y, w, h = bbox
            ratio = float(w) / max(1.0, float(h))

        vehicle_type, body_style, model_hint, make_hint, base_conf = self._shape_profile(
            class_name=class_name,
            aspect_ratio=ratio,
        )
        dominant_color, color_conf = self._estimate_dominant_color(
            frame_bgr=frame_bgr,
            bbox=bbox,
        )
        confidence = min(0.95, (0.82 * base_conf) + (0.18 * color_conf))

        return VehicleProfilePrediction(
            vehicle_type=vehicle_type,
            body_style=body_style,
            model_hint=model_hint,
            make_hint=make_hint,
            dominant_color=dominant_color,
            confidence=confidence,
            aspect_ratio=ratio,
            source="light_profile_classifier_v1",
        )

    def _shape_profile(
        self,
        *,
        class_name: Optional[str],
        aspect_ratio: Optional[float],
    ) -> tuple[str, str, str, str, float]:
        normalized_class = str(class_name or "unknown").strip().lower() or "unknown"
        if normalized_class == "car":
            if aspect_ratio is not None and aspect_ratio >= 2.25:
                return ("passenger", "sedan_coupe", "sedan_like", "sedan_family", 0.66)
            if aspect_ratio is not None and aspect_ratio >= 1.65:
                return ("passenger", "suv_crossover", "crossover_like", "suv_family", 0.63)
            return ("passenger", "compact_hatch", "compact_like", "compact_family", 0.58)
        if normalized_class == "truck":
            return ("utility", "truck", "pickup_or_truck", "utility_fleet", 0.72)
        if normalized_class == "bus":
            return ("transport", "bus", "bus_like", "transport_fleet", 0.74)
        if normalized_class == "motorcycle":
            return ("two_wheeler", "motorcycle", "motorcycle_like", "two_wheeler_fleet", 0.76)
        return ("unknown", "unknown", "unknown", "unknown", 0.35)

    def _estimate_dominant_color(
        self,
        *,
        frame_bgr: Optional[np.ndarray],
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> tuple[str, float]:
        if frame_bgr is None or frame_bgr.size == 0:
            return ("unknown", 0.0)

        roi = self._extract_focus_roi(frame_bgr=frame_bgr, bbox=bbox)
        if roi is None or roi.size == 0:
            return ("unknown", 0.0)

        sample = roi.reshape(-1, 3).astype(np.float32)
        if sample.shape[0] > 12_000:
            stride = max(1, int(sample.shape[0] / 12_000))
            sample = sample[::stride]

        rgb = sample[:, ::-1]
        luminance = rgb.mean(axis=1)
        valid = rgb[(luminance > 20.0) & (luminance < 245.0)]
        if valid.shape[0] >= 80:
            rgb = valid

        r, g, b = np.percentile(rgb, 55, axis=0).tolist()
        color = self._map_rgb_to_color_name(r=float(r), g=float(g), b=float(b))

        spread = float(max(r, g, b) - min(r, g, b))
        if color in {"black", "white", "gray", "silver"}:
            confidence = 0.62 if spread < 36 else 0.55
        elif color == "unknown":
            confidence = 0.0
        else:
            confidence = min(0.9, 0.48 + (spread / 190.0))
        return (color, float(max(0.0, min(1.0, confidence))))

    def _extract_focus_roi(
        self,
        *,
        frame_bgr: np.ndarray,
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> Optional[np.ndarray]:
        h, w = frame_bgr.shape[:2]
        if bbox is None:
            x1, y1, x2, y2 = 0, 0, w, h
        else:
            x, y, bw, bh = bbox
            x1 = max(0, int(x))
            y1 = max(0, int(y))
            x2 = min(w, int(x + bw))
            y2 = min(h, int(y + bh))
        roi = frame_bgr[y1:y2, x1:x2]
        if roi is None or roi.size == 0:
            return None

        rh, rw = roi.shape[:2]
        if rh < 8 or rw < 8:
            return roi

        # Remove upper reflections and lower shadows/plate region.
        top = int(rh * 0.16)
        bottom = int(rh * 0.84)
        left = int(rw * 0.07)
        right = int(rw * 0.93)
        focus = roi[top:bottom, left:right]
        return focus if focus.size > 0 else roi

    def _map_rgb_to_color_name(self, *, r: float, g: float, b: float) -> str:
        rf = max(0.0, min(1.0, r / 255.0))
        gf = max(0.0, min(1.0, g / 255.0))
        bf = max(0.0, min(1.0, b / 255.0))
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)

        if v < 0.18:
            return "black"
        if s < 0.10:
            if v > 0.85:
                return "white"
            if v > 0.62:
                return "silver"
            return "gray"
        if h < 0.04 or h >= 0.96:
            return "red"
        if h < 0.09:
            return "orange"
        if h < 0.18:
            return "yellow"
        if h < 0.42:
            return "green"
        if h < 0.58:
            return "cyan"
        if h < 0.76:
            return "blue"
        if h < 0.92:
            return "purple"
        return "unknown"

