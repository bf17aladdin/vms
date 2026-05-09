from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .tiny_onnx_brand_classifier import TinyOnnxBrandClassifier


@dataclass
class TinyOnnxTerrainPrediction:
    brand: Optional[str]
    brand_confidence: float
    color: Optional[str]
    color_confidence: float
    model: Optional[str]
    model_confidence: float
    source: str


class TinyOnnxTerrainClassifier:
    """
    Optional terrain ONNX ensemble:
    - brand head
    - color head
    - model head
    Gracefully degrades when one or more heads are missing.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        brand_model_path: Optional[str],
        brand_labels_path: Optional[str],
        color_model_path: Optional[str],
        color_labels_path: Optional[str],
        model_model_path: Optional[str],
        model_labels_path: Optional[str],
        input_size: int = 112,
    ):
        self.enabled = bool(enabled)
        self.brand_head = TinyOnnxBrandClassifier(
            enabled=self.enabled,
            model_path=brand_model_path,
            labels_path=brand_labels_path,
            input_size=input_size,
        )
        self.color_head = TinyOnnxBrandClassifier(
            enabled=self.enabled,
            model_path=color_model_path,
            labels_path=color_labels_path,
            input_size=input_size,
        )
        self.model_head = TinyOnnxBrandClassifier(
            enabled=self.enabled,
            model_path=model_model_path,
            labels_path=model_labels_path,
            input_size=input_size,
        )

    @property
    def available(self) -> bool:
        return bool(
            (self.brand_head is not None and self.brand_head.available)
            or (self.color_head is not None and self.color_head.available)
            or (self.model_head is not None and self.model_head.available)
        )

    def predict(
        self,
        *,
        frame_bgr: Optional[np.ndarray],
        bbox: Optional[tuple[int, int, int, int]],
    ) -> Optional[TinyOnnxTerrainPrediction]:
        if not self.available:
            return None

        brand_pred = self.brand_head.predict(frame_bgr=frame_bgr, bbox=bbox) if self.brand_head.available else None
        color_pred = self.color_head.predict(frame_bgr=frame_bgr, bbox=bbox) if self.color_head.available else None
        model_pred = self.model_head.predict(frame_bgr=frame_bgr, bbox=bbox) if self.model_head.available else None

        if brand_pred is None and color_pred is None and model_pred is None:
            return None

        sources = []
        if brand_pred is not None:
            sources.append(f"brand:{brand_pred.source}")
        if color_pred is not None:
            sources.append(f"color:{color_pred.source}")
        if model_pred is not None:
            sources.append(f"model:{model_pred.source}")

        return TinyOnnxTerrainPrediction(
            brand=(brand_pred.brand if brand_pred is not None else None),
            brand_confidence=float(brand_pred.confidence if brand_pred is not None else 0.0),
            color=(color_pred.brand if color_pred is not None else None),
            color_confidence=float(color_pred.confidence if color_pred is not None else 0.0),
            model=(model_pred.brand if model_pred is not None else None),
            model_confidence=float(model_pred.confidence if model_pred is not None else 0.0),
            source="+".join(sources) if sources else "onnxruntime",
        )
