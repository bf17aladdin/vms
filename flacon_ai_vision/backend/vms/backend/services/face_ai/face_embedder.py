from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    import face_recognition as _fr  # type: ignore

    _HAS_FACE_RECOGNITION = True
except Exception:
    _HAS_FACE_RECOGNITION = False

try:
    from insightface.model_zoo import get_model  # type: ignore

    _HAS_INSIGHTFACE_MODEL = True
except Exception:
    _HAS_INSIGHTFACE_MODEL = False

from .face_detector import FaceDetection, resolve_face_onnx_runtime

logger = logging.getLogger(__name__)


class FaceEmbedder:
    """Face embedding extractor with ArcFace-first strategy."""

    def __init__(self):
        self.prefer_detector_embedding = os.getenv("FACE_USE_DETECTOR_EMBEDDING", "true").lower() == "true"
        self.enable_fallback_embedding = os.getenv("FACE_ENABLE_FALLBACK_EMBEDDING", "false").lower() == "true"
        self.arcface_model = None
        self._init_arcface_model()
        default_fallback_dim = 512
        if self.arcface_model is None and _HAS_FACE_RECOGNITION:
            default_fallback_dim = 128
        self.fallback_dim = int(
            os.getenv("FACE_FALLBACK_EMBEDDING_DIM", str(default_fallback_dim))
        )

    @property
    def backend(self) -> str:
        if self.arcface_model is not None:
            return "arcface_onnx"
        if _HAS_FACE_RECOGNITION:
            return "face_recognition"
        return "fallback"

    def _candidate_arcface_paths(self) -> list[Path]:
        explicit = str(os.getenv("ARCFACE_MODEL_PATH", "") or "").strip()
        candidates: list[Path] = []
        if explicit:
            candidates.append(Path(explicit).expanduser())

        insightface_home = str(os.getenv("INSIGHTFACE_HOME", "") or "").strip()
        if insightface_home:
            candidates.append(
                Path(insightface_home).expanduser() / "models" / "buffalo_l" / "w600k_r50.onnx"
            )

        # Default InsightFace cache location used on local/dev workstations.
        candidates.append(Path.home() / ".insightface" / "models" / "buffalo_l" / "w600k_r50.onnx")

        deduped: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate.resolve()) if candidate.exists() else str(candidate)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _init_arcface_model(self) -> None:
        if not _HAS_INSIGHTFACE_MODEL:
            return

        try:
            providers, ctx_id, _available = resolve_face_onnx_runtime()
        except Exception as exc:
            logger.debug("Face embedder ONNX runtime resolution failed: %s", exc)
            return

        kwargs = {}
        if providers:
            kwargs["providers"] = providers

        for model_path in self._candidate_arcface_paths():
            if not model_path.exists():
                continue
            try:
                try:
                    self.arcface_model = get_model(str(model_path), **kwargs)
                except TypeError:
                    # Backward compatibility with insightface builds not accepting providers=...
                    self.arcface_model = get_model(str(model_path))
                self.arcface_model.prepare(ctx_id=ctx_id)
                return
            except Exception as exc:
                logger.debug("Unable to initialize ArcFace model from %s: %s", model_path, exc)
                self.arcface_model = None

    def embed(self, aligned_face_bgr: np.ndarray, detection: Optional[FaceDetection] = None) -> Tuple[Optional[np.ndarray], str]:
        if aligned_face_bgr is None or aligned_face_bgr.size == 0:
            return None, "empty"

        detector_vector = self._extract_detector_vector(detection)
        if detector_vector is not None:
            return detector_vector, "insightface_detector_embedding"

        if self.arcface_model is not None:
            try:
                vec = self.arcface_model.get_feat(aligned_face_bgr)
                vec = np.asarray(vec, dtype=np.float32).reshape(-1)
                if vec.size > 0:
                    return self._normalize(vec), "arcface_onnx"
            except Exception as exc:
                logger.debug("ArcFace embedding failed, falling back to alternate backends: %s", exc)

        if _HAS_FACE_RECOGNITION:
            try:
                if _HAS_CV2:
                    rgb = cv2.cvtColor(aligned_face_bgr, cv2.COLOR_BGR2RGB)
                else:
                    rgb = aligned_face_bgr[..., ::-1]
                locations = _fr.face_locations(rgb, model="hog")
                encodings = _fr.face_encodings(rgb, known_face_locations=locations[:1] if locations else None)
                if encodings:
                    return self._normalize(np.asarray(encodings[0], dtype=np.float32)), "face_recognition"
            except Exception as exc:
                logger.debug("face_recognition embedding fallback failed: %s", exc)

        if self.enable_fallback_embedding:
            return self._fallback_embedding(aligned_face_bgr), "fallback_hist"
        return None, "fallback_disabled"

    def _extract_detector_vector(self, detection: Optional[FaceDetection]) -> Optional[np.ndarray]:
        if not self.prefer_detector_embedding or detection is None or detection.raw is None:
            return None

        raw = detection.raw
        for attr in ("normed_embedding", "embedding"):
            value = getattr(raw, attr, None)
            if value is None:
                continue
            vec = np.asarray(value, dtype=np.float32).reshape(-1)
            if vec.size == 0:
                continue
            return self._normalize(vec)
        return None

    def _fallback_embedding(self, aligned_face_bgr: np.ndarray) -> np.ndarray:
        if _HAS_CV2:
            gray = cv2.cvtColor(aligned_face_bgr, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_LINEAR)
        else:
            gray = np.mean(aligned_face_bgr, axis=2)
            ys = np.linspace(0, gray.shape[0] - 1, 32).astype(int)
            xs = np.linspace(0, gray.shape[1] - 1, 32).astype(int)
            resized = gray[np.ix_(ys, xs)]

        vec = resized.astype(np.float32).reshape(-1)
        if vec.size < self.fallback_dim:
            pad = np.zeros(self.fallback_dim - vec.size, dtype=np.float32)
            vec = np.concatenate([vec, pad], axis=0)
        elif vec.size > self.fallback_dim:
            vec = vec[: self.fallback_dim]
        return self._normalize(vec)

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            return vector.astype(np.float32)
        return (vector / norm).astype(np.float32)
