from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

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
    from insightface.app import FaceAnalysis  # type: ignore

    _HAS_INSIGHTFACE = True
except Exception:
    _HAS_INSIGHTFACE = False

logger = logging.getLogger(__name__)


def _read_face_ctx_id(default_ctx_id: int) -> int:
    raw = os.getenv("FACE_CTX_ID", "").strip()
    if not raw:
        return int(default_ctx_id)
    try:
        return int(raw)
    except Exception:
        return int(default_ctx_id)


def resolve_face_onnx_runtime() -> Tuple[Optional[List[str]], int, List[str]]:
    """
    Resolve ONNX providers and ctx_id safely.
    - Prefers GPU providers when actually available.
    - Falls back to CPU provider without raising noisy runtime warnings.
    """
    providers_env = os.getenv("FACE_ONNX_PROVIDERS", "").strip()
    force_cpu = os.getenv("FACE_FORCE_CPU", "false").lower() == "true"

    available: List[str] = []
    try:
        import onnxruntime as ort  # type: ignore

        available = [str(p) for p in ort.get_available_providers()]
    except Exception:
        available = []

    requested: List[str] = []
    if providers_env:
        requested = [p.strip() for p in providers_env.split(",") if p.strip()]

    if force_cpu:
        selected = ["CPUExecutionProvider"] if not available or "CPUExecutionProvider" in available else []
        return (selected or None), _read_face_ctx_id(-1), available

    if requested:
        if available:
            selected = [p for p in requested if p in available]
            if not selected and "CPUExecutionProvider" in available:
                selected = ["CPUExecutionProvider"]
        else:
            # If availability cannot be queried, trust explicit configuration.
            selected = requested
    else:
        selected = []
        if available:
            preferred_order = [
                "CUDAExecutionProvider",
                "TensorrtExecutionProvider",
                "DmlExecutionProvider",
                "ROCMExecutionProvider",
                "CPUExecutionProvider",
            ]
            selected = [p for p in preferred_order if p in available]
            if not selected:
                selected = list(available)

    if selected:
        has_gpu_provider = any(p != "CPUExecutionProvider" for p in selected)
        default_ctx_id = 0 if has_gpu_provider else -1
    else:
        default_ctx_id = -1

    ctx_id = _read_face_ctx_id(default_ctx_id)
    return (selected or None), ctx_id, available


@dataclass
class FaceDetection:
    bbox: Tuple[int, int, int, int]
    score: float
    landmarks: Optional[np.ndarray]
    source: str
    raw: Any = None


class FaceDetector:
    """Face detector with InsightFace-first strategy and cv2 fallback."""

    def __init__(self, det_size: Tuple[int, int] = (640, 640)):
        self.det_size = det_size
        self.min_face_size = int(os.getenv("FACE_MIN_SIZE", "40"))
        self.use_fr_fallback = os.getenv("FACE_USE_FR_FALLBACK", "true").lower() == "true"
        self.fr_max_side = int(os.getenv("FACE_FR_MAX_SIDE", "480"))
        self.fr_upsample = int(os.getenv("FACE_FR_UPSAMPLE", "0"))
        self.app = None
        self._init_insightface()

    @property
    def backend(self) -> str:
        if self.app is not None:
            return "insightface"
        if _HAS_FACE_RECOGNITION:
            return "face_recognition_hog"
        if _HAS_CV2:
            return "cv2_haar_multi"
        return "none"

    def _init_insightface(self) -> None:
        if not _HAS_INSIGHTFACE:
            return

        model_pack = os.getenv("FACE_MODEL_PACK", "buffalo_l")
        providers, ctx_id, available = resolve_face_onnx_runtime()

        try:
            kwargs = {"name": model_pack}
            if providers:
                kwargs["providers"] = providers
            self.app = FaceAnalysis(**kwargs)
            self.app.prepare(ctx_id=ctx_id, det_size=self.det_size)
            if providers:
                logger.info(
                    "Face detector ONNX providers selected=%s available=%s ctx_id=%s",
                    providers,
                    available,
                    ctx_id,
                )
        except Exception as e:
            logger.warning("Face detector init failed: %s", e)
            self.app = None

    def detect(self, image_bgr: np.ndarray, max_faces: int = 0) -> List[FaceDetection]:
        if image_bgr is None or not hasattr(image_bgr, "shape"):
            logger.debug("Face detector received an invalid image payload")
            return []

        if self.app is not None:
            detections = self._detect_with_insightface(image_bgr, max_faces=max_faces)
            if detections:
                return detections

        if _HAS_CV2:
            detections = self._detect_with_haar(image_bgr)
            if detections:
                return detections
            eye_proxy = self._detect_with_eye_proxy(image_bgr)
            if eye_proxy:
                return eye_proxy

        if _HAS_FACE_RECOGNITION and self.use_fr_fallback:
            return self._detect_with_face_recognition(image_bgr)
        return []

    def _detect_with_insightface(self, image_bgr: np.ndarray, max_faces: int) -> List[FaceDetection]:
        out: List[FaceDetection] = []
        try:
            faces = self.app.get(image_bgr, max_num=max_faces)
        except Exception as exc:
            logger.debug("InsightFace detection failed, falling back to secondary detectors: %s", exc)
            return out

        for face in faces:
            bbox = getattr(face, "bbox", None)
            if bbox is None or len(bbox) < 4:
                continue

            x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
            w = max(0, x2 - x1)
            h = max(0, y2 - y1)
            if min(w, h) < self.min_face_size:
                continue

            kps = getattr(face, "kps", None)
            landmarks = np.asarray(kps, dtype=np.float32) if kps is not None else None
            score = float(getattr(face, "det_score", 1.0))

            out.append(
                FaceDetection(
                    bbox=(x1, y1, w, h),
                    score=score,
                    landmarks=landmarks,
                    source="insightface",
                    raw=face,
                )
            )

        out.sort(key=lambda item: item.score * max(item.bbox[2] * item.bbox[3], 1), reverse=True)
        return out

    def _detect_with_haar(self, image_bgr: np.ndarray) -> List[FaceDetection]:
        out: List[FaceDetection] = []
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        variants = [gray]
        variants.append(cv2.equalizeHist(gray))
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        variants.append(clahe.apply(gray))

        cascade_specs = [
            ("haarcascade_frontalface_default.xml", "cv2_haar_frontal", 0.55, False),
            ("haarcascade_frontalface_alt2.xml", "cv2_haar_alt2", 0.52, False),
            ("haarcascade_profileface.xml", "cv2_haar_profile", 0.45, True),
        ]
        detect_params = [
            (1.08, 3),
            (1.1, 4),
            (1.12, 5),
        ]

        candidates: List[FaceDetection] = []
        for cascade_name, source_name, base_score, with_mirror in cascade_specs:
            cascade_path = os.path.join(cv2.data.haarcascades, cascade_name)
            cascade = cv2.CascadeClassifier(str(cascade_path))
            if cascade.empty():
                continue

            for gray_img in variants:
                for scale_factor, min_neighbors in detect_params:
                    faces = cascade.detectMultiScale(
                        gray_img,
                        scaleFactor=scale_factor,
                        minNeighbors=min_neighbors,
                        minSize=(self.min_face_size, self.min_face_size),
                    )
                    for x, y, w, h in faces:
                        candidates.append(
                            FaceDetection(
                                bbox=(int(x), int(y), int(w), int(h)),
                                score=float(base_score),
                                landmarks=None,
                                source=source_name,
                                raw=None,
                            )
                        )

                    if not with_mirror:
                        continue

                    flipped = cv2.flip(gray_img, 1)
                    faces_mirror = cascade.detectMultiScale(
                        flipped,
                        scaleFactor=scale_factor,
                        minNeighbors=min_neighbors,
                        minSize=(self.min_face_size, self.min_face_size),
                    )
                    img_w = gray_img.shape[1]
                    for x, y, w, h in faces_mirror:
                        x_unflipped = img_w - (x + w)
                        candidates.append(
                            FaceDetection(
                                bbox=(int(x_unflipped), int(y), int(w), int(h)),
                                score=float(base_score - 0.03),
                                landmarks=None,
                                source=f"{source_name}_mirror",
                                raw=None,
                            )
                        )

        if not candidates:
            return out

        # NMS-lite dedupe for heavily overlapping detections from multiple cascades/variants.
        candidates.sort(key=lambda item: item.score * max(item.bbox[2] * item.bbox[3], 1), reverse=True)
        for det in candidates:
            if any(self._bbox_iou(det.bbox, kept.bbox) > 0.35 for kept in out):
                continue
            out.append(det)
            if len(out) >= 20:
                break

        out.sort(key=lambda item: item.score * max(item.bbox[2] * item.bbox[3], 1), reverse=True)
        return out

    def _detect_with_face_recognition(self, image_bgr: np.ndarray) -> List[FaceDetection]:
        out: List[FaceDetection] = []
        try:
            rgb = image_bgr[:, :, ::-1]
            h, w = rgb.shape[:2]
            scale = 1.0
            max_side = max(h, w)
            if max_side > self.fr_max_side > 0:
                scale = float(self.fr_max_side) / float(max_side)
                new_w = max(1, int(w * scale))
                new_h = max(1, int(h * scale))
                rgb = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

            locations = _fr.face_locations(rgb, number_of_times_to_upsample=max(0, self.fr_upsample), model="hog")
        except Exception as exc:
            logger.debug("face_recognition fallback detector failed: %s", exc)
            return out

        for top, right, bottom, left in locations:
            if scale != 1.0:
                top = int(round(top / scale))
                right = int(round(right / scale))
                bottom = int(round(bottom / scale))
                left = int(round(left / scale))

            x = int(max(0, left))
            y = int(max(0, top))
            w = int(max(0, right - left))
            h = int(max(0, bottom - top))
            if min(w, h) < self.min_face_size:
                continue
            out.append(
                FaceDetection(
                    bbox=(x, y, w, h),
                    score=0.6,
                    landmarks=None,
                    source="face_recognition_hog",
                    raw=None,
                )
            )

        out.sort(key=lambda item: item.bbox[2] * item.bbox[3], reverse=True)
        return out

    def _detect_with_eye_proxy(self, image_bgr: np.ndarray) -> List[FaceDetection]:
        out: List[FaceDetection] = []
        try:
            gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]
            roi_h = max(1, int(h * 0.7))
            roi = gray[:roi_h, :]

            eye_cascade = cv2.CascadeClassifier(
                str(os.path.join(cv2.data.haarcascades, "haarcascade_eye_tree_eyeglasses.xml"))
            )
            if eye_cascade.empty():
                return out

            eyes = eye_cascade.detectMultiScale(
                roi,
                scaleFactor=1.08,
                minNeighbors=4,
                minSize=(max(10, self.min_face_size // 4), max(10, self.min_face_size // 4)),
            )
            if len(eyes) < 2:
                return out

            centers = []
            for ex, ey, ew, eh in eyes:
                cx = float(ex + ew / 2.0)
                cy = float(ey + eh / 2.0)
                centers.append((cx, cy))

            best_pair = None
            best_score = -1.0
            for i in range(len(centers)):
                for j in range(i + 1, len(centers)):
                    (x1, y1) = centers[i]
                    (x2, y2) = centers[j]
                    inter_eye = abs(x2 - x1)
                    y_diff = abs(y2 - y1)
                    if inter_eye < max(20.0, self.min_face_size * 0.45):
                        continue
                    if y_diff > inter_eye * 0.35:
                        continue
                    score = inter_eye - y_diff * 0.5
                    if score > best_score:
                        best_score = score
                        best_pair = ((x1, y1), (x2, y2), inter_eye)

            if best_pair is None:
                return out

            (p1, p2, inter_eye) = best_pair
            cx = (p1[0] + p2[0]) / 2.0
            top_y = min(p1[1], p2[1])

            face_w = int(inter_eye * 2.3)
            face_h = int(inter_eye * 2.8)
            x = int(cx - face_w / 2.0)
            y = int(top_y - inter_eye * 0.75)
            x = max(0, min(w - 1, x))
            y = max(0, min(h - 1, y))
            face_w = max(self.min_face_size, min(face_w, w - x))
            face_h = max(self.min_face_size, min(face_h, h - y))

            if face_w <= 0 or face_h <= 0:
                return out

            out.append(
                FaceDetection(
                    bbox=(int(x), int(y), int(face_w), int(face_h)),
                    score=0.42,
                    landmarks=None,
                    source="cv2_eye_proxy",
                    raw=None,
                )
            )
        except Exception as exc:
            logger.debug("Eye proxy face fallback failed: %s", exc)
            return []

        return out

    def _bbox_iou(self, a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ax2, ay2 = ax + aw, ay + ah
        bx2, by2 = bx + bw, by + bh

        inter_x1 = max(ax, bx)
        inter_y1 = max(ay, by)
        inter_x2 = min(ax2, bx2)
        inter_y2 = min(ay2, by2)
        if inter_x2 <= inter_x1 or inter_y2 <= inter_y1:
            return 0.0

        inter = float((inter_x2 - inter_x1) * (inter_y2 - inter_y1))
        union = float(aw * ah + bw * bh - inter)
        if union <= 0.0:
            return 0.0
        return inter / union
