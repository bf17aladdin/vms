from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np
from PIL import Image


@dataclass
class TinyOnnxBrandPrediction:
    brand: str
    confidence: float
    class_index: int
    source: str


class TinyOnnxBrandClassifier:
    """Tiny ONNX vehicle brand classifier with graceful fallback when unavailable."""

    def __init__(
        self,
        *,
        enabled: bool,
        model_path: Optional[str],
        labels_path: Optional[str],
        input_size: int = 112,
    ):
        self.enabled = bool(enabled)
        self.input_size = max(32, int(input_size))
        self.model_path = str(model_path or "").strip()
        self.labels_path = str(labels_path or "").strip()
        self.backend = "disabled"

        self._session = None
        self._input_name: Optional[str] = None
        self._input_shape: Optional[Tuple[int, ...]] = None
        self._expects_nchw = True
        self._labels: Sequence[str] = ()

        if not self.enabled:
            return
        if not self.model_path or not Path(self.model_path).exists():
            self.enabled = False
            self.backend = "missing_model"
            return

        self._labels = self._load_labels(self.labels_path)

        try:
            import onnxruntime as ort  # type: ignore
        except Exception:
            self.enabled = False
            self.backend = "onnxruntime_unavailable"
            return

        try:
            self._session = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
            inputs = self._session.get_inputs()
            if not inputs:
                self.enabled = False
                self.backend = "invalid_model_inputs"
                self._session = None
                return
            inp = inputs[0]
            self._input_name = str(inp.name)
            shape = tuple(int(v) if isinstance(v, int) else -1 for v in (inp.shape or []))
            self._input_shape = shape if len(shape) == 4 else None
            if self._input_shape is not None and self._input_shape[3] in {1, 3}:
                self._expects_nchw = False
            self.backend = "onnxruntime"
        except Exception:
            self.enabled = False
            self.backend = "onnx_init_failed"
            self._session = None

    @property
    def available(self) -> bool:
        return bool(self.enabled and self._session is not None and self._input_name)

    def predict(
        self,
        *,
        frame_bgr: Optional[np.ndarray],
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> Optional[TinyOnnxBrandPrediction]:
        if not self.available:
            return None
        if frame_bgr is None or frame_bgr.size == 0:
            return None
        if self._session is None or self._input_name is None:
            return None

        roi = self._extract_roi(frame_bgr=frame_bgr, bbox=bbox)
        if roi is None or roi.size == 0:
            return None

        try:
            tensor = self._preprocess(roi)
            outputs = self._session.run(None, {self._input_name: tensor})
            if not outputs:
                return None
            logits = np.asarray(outputs[0])
            if logits.ndim == 2:
                logits = logits[0]
            logits = logits.astype(np.float32).reshape(-1)
            if logits.size == 0:
                return None
            probs = self._softmax(logits)
            class_index = int(np.argmax(probs))
            confidence = float(probs[class_index])
            brand = self._resolve_label(class_index)
            if not brand:
                return None
            return TinyOnnxBrandPrediction(
                brand=brand,
                confidence=float(max(0.0, min(1.0, confidence))),
                class_index=class_index,
                source=self.backend,
            )
        except Exception:
            return None

    def _extract_roi(
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
        top = int(rh * 0.10)
        bottom = int(rh * 0.92)
        left = int(rw * 0.08)
        right = int(rw * 0.92)
        focus = roi[top:bottom, left:right]
        return focus if focus.size > 0 else roi

    def _preprocess(self, roi_bgr: np.ndarray) -> np.ndarray:
        target_h = self.input_size
        target_w = self.input_size
        if self._input_shape is not None:
            if self._expects_nchw:
                if self._input_shape[2] > 0:
                    target_h = int(self._input_shape[2])
                if self._input_shape[3] > 0:
                    target_w = int(self._input_shape[3])
            else:
                if self._input_shape[1] > 0:
                    target_h = int(self._input_shape[1])
                if self._input_shape[2] > 0:
                    target_w = int(self._input_shape[2])

        rgb = roi_bgr[:, :, ::-1]
        resized = Image.fromarray(rgb).resize((target_w, target_h), Image.BILINEAR)
        arr = np.asarray(resized).astype(np.float32) / 255.0
        # ImageNet-style normalization.
        arr = (arr - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array(
            [0.229, 0.224, 0.225], dtype=np.float32
        )

        if self._expects_nchw:
            arr = np.transpose(arr, (2, 0, 1))
            arr = arr[np.newaxis, :, :, :]
        else:
            arr = arr[np.newaxis, :, :, :]
        return arr.astype(np.float32)

    def _resolve_label(self, idx: int) -> str:
        if 0 <= int(idx) < len(self._labels):
            return str(self._labels[int(idx)]).strip()
        return f"class_{int(idx)}"

    def _load_labels(self, labels_path: str) -> Sequence[str]:
        if labels_path:
            p = Path(labels_path)
            if p.exists():
                try:
                    text = p.read_text(encoding="utf-8").strip()
                    if text.startswith("[") or text.startswith("{"):
                        payload = json.loads(text)
                        if isinstance(payload, list):
                            return [str(item).strip() for item in payload if str(item).strip()]
                        if isinstance(payload, dict):
                            out = []
                            for _, value in sorted(payload.items(), key=lambda row: int(row[0])):
                                label = str(value).strip()
                                if label:
                                    out.append(label)
                            return out
                    labels = [line.strip() for line in text.splitlines() if line.strip()]
                    if labels:
                        return labels
                except Exception:
                    pass

        csv_labels = str(os.getenv("VEHICLE_TINY_BRAND_ONNX_LABELS", "") or "").strip()
        if csv_labels:
            return [chunk.strip() for chunk in csv_labels.split(",") if chunk.strip()]
        return ()

    def _softmax(self, logits: np.ndarray) -> np.ndarray:
        z = logits - np.max(logits)
        exp = np.exp(z)
        denom = np.sum(exp)
        if denom <= 0:
            return np.zeros_like(logits, dtype=np.float32)
        return exp / denom

