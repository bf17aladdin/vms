from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

from .face_detector import FaceDetection


@dataclass
class FaceAlignResult:
    aligned_face: np.ndarray
    yaw: float
    pitch: float
    roll: float
    source: str


class FaceAligner:
    """Align faces using five landmarks compatible with ArcFace input."""

    ARCFACE_TEMPLATE = np.array(
        [
            [38.2946, 51.6963],
            [73.5318, 51.5014],
            [56.0252, 71.7366],
            [41.5493, 92.3655],
            [70.7299, 92.2041],
        ],
        dtype=np.float32,
    )

    def __init__(self, output_size: Tuple[int, int] = (112, 112)):
        self.output_size = output_size

    def align(self, image_bgr: np.ndarray, detection: FaceDetection) -> FaceAlignResult:
        if detection.landmarks is not None and detection.landmarks.shape[0] >= 5 and _HAS_CV2:
            aligned = self._align_by_landmarks(image_bgr, detection.landmarks[:5])
            if aligned is not None:
                yaw, pitch, roll = self._estimate_pose(detection.landmarks[:5])
                return FaceAlignResult(
                    aligned_face=aligned,
                    yaw=yaw,
                    pitch=pitch,
                    roll=roll,
                    source="landmarks_affine",
                )

        fallback = self._crop_and_resize(image_bgr, detection.bbox)
        return FaceAlignResult(
            aligned_face=fallback,
            yaw=0.0,
            pitch=0.0,
            roll=0.0,
            source="bbox_crop",
        )

    def _align_by_landmarks(self, image_bgr: np.ndarray, landmarks_5: np.ndarray) -> Optional[np.ndarray]:
        dst = self.ARCFACE_TEMPLATE.copy()
        if self.output_size != (112, 112):
            scale_x = self.output_size[0] / 112.0
            scale_y = self.output_size[1] / 112.0
            dst[:, 0] *= scale_x
            dst[:, 1] *= scale_y

        transform, _ = cv2.estimateAffinePartial2D(landmarks_5, dst, method=cv2.LMEDS)
        if transform is None:
            return None

        return cv2.warpAffine(
            image_bgr,
            transform,
            self.output_size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )

    def _crop_and_resize(self, image_bgr: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        x, y, w, h = bbox
        ih, iw = image_bgr.shape[:2]

        margin_x = int(w * 0.15)
        margin_y = int(h * 0.2)
        x1 = max(0, x - margin_x)
        y1 = max(0, y - margin_y)
        x2 = min(iw, x + w + margin_x)
        y2 = min(ih, y + h + margin_y)

        face = image_bgr[y1:y2, x1:x2]
        if face.size == 0:
            face = image_bgr

        if _HAS_CV2:
            return cv2.resize(face, self.output_size, interpolation=cv2.INTER_LINEAR)

        # cv2 may be unavailable in constrained environments
        # Keep deterministic behavior with NumPy nearest-neighbor fallback.
        ys = np.linspace(0, face.shape[0] - 1, self.output_size[1]).astype(int)
        xs = np.linspace(0, face.shape[1] - 1, self.output_size[0]).astype(int)
        return face[np.ix_(ys, xs)]

    def _estimate_pose(self, landmarks_5: np.ndarray) -> Tuple[float, float, float]:
        left_eye, right_eye, nose, mouth_left, mouth_right = landmarks_5
        eye_dx = float(right_eye[0] - left_eye[0])
        eye_dy = float(right_eye[1] - left_eye[1])
        roll = math.degrees(math.atan2(eye_dy, eye_dx + 1e-6))

        eye_center = (left_eye + right_eye) / 2.0
        inter_eye = max(abs(eye_dx), 1e-6)
        yaw = ((float(nose[0]) - float(eye_center[0])) / inter_eye) * 35.0
        yaw = float(np.clip(yaw, -45.0, 45.0))

        mouth_center = (mouth_left + mouth_right) / 2.0
        eye_to_mouth = max(float(mouth_center[1] - eye_center[1]), 1e-6)
        pitch_ratio = (float(nose[1] - eye_center[1]) / eye_to_mouth) - 0.5
        pitch = float(np.clip(pitch_ratio * 40.0, -35.0, 35.0))

        return yaw, pitch, roll
