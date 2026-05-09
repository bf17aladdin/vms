from __future__ import annotations

import colorsys
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image

UNKNOWN_COLOR = "unknown"
UNKNOWN_ACCESSORY = "unknown"

KNOWN_COLORS: tuple[str, ...] = (
    "black",
    "white",
    "gray",
    "silver",
    "red",
    "blue",
    "green",
    "yellow",
    "orange",
    "brown",
    "purple",
    "pink",
    "unknown",
)

COLOR_ALIASES = {
    "grey": "gray",
    "maroon": "red",
}

ACCESSORY_STATES: tuple[str, ...] = ("yes", "no", "unknown")
COLOR_PROTOTYPES: dict[str, tuple[float, float, float]] = {
    "black": (0.05, 0.05, 0.05),
    "white": (0.98, 0.98, 0.98),
    "gray": (0.55, 0.55, 0.55),
    "silver": (0.75, 0.75, 0.78),
    "red": (0.82, 0.16, 0.18),
    "blue": (0.18, 0.36, 0.82),
    "green": (0.20, 0.64, 0.28),
    "yellow": (0.90, 0.82, 0.18),
    "orange": (0.92, 0.54, 0.16),
    "brown": (0.45, 0.28, 0.16),
    "purple": (0.52, 0.30, 0.72),
    "pink": (0.90, 0.58, 0.72),
    "unknown": (0.0, 0.0, 0.0),
}


@dataclass(frozen=True)
class PersonAppearanceAttributes:
    top_color: str = UNKNOWN_COLOR
    bottom_color: str = UNKNOWN_COLOR
    has_backpack: Optional[bool] = None
    has_hat: Optional[bool] = None
    person_bbox: Optional[dict[str, int]] = None
    top_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bottom_rgb: tuple[float, float, float] = (0.0, 0.0, 0.0)
    embedding: Optional[list[float]] = None


def normalize_color(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    normalized = COLOR_ALIASES.get(value.strip().lower(), value.strip().lower())
    if not normalized:
        return None
    if normalized not in KNOWN_COLORS:
        raise ValueError(
            f"Invalid color '{value}'. Allowed values: {', '.join(KNOWN_COLORS)}"
        )
    return normalized


def serialize_color(value: Optional[str]) -> str:
    if not value:
        return UNKNOWN_COLOR
    normalized = COLOR_ALIASES.get(value.strip().lower(), value.strip().lower())
    return normalized if normalized in KNOWN_COLORS else UNKNOWN_COLOR


def parse_accessory_filter(value: Optional[str]) -> Optional[bool | str]:
    if value is None:
        return None

    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    if normalized == UNKNOWN_ACCESSORY:
        return UNKNOWN_ACCESSORY

    raise ValueError(
        f"Invalid accessory state '{value}'. Allowed values: {', '.join(ACCESSORY_STATES)}"
    )


def serialize_accessory_state(value: Optional[bool]) -> str:
    if value is None:
        return UNKNOWN_ACCESSORY
    return "yes" if value else "no"


def build_appearance_embedding(
    top_color: Optional[str],
    bottom_color: Optional[str],
    has_backpack: Optional[bool],
    has_hat: Optional[bool],
    top_rgb: Optional[tuple[float, float, float]] = None,
    bottom_rgb: Optional[tuple[float, float, float]] = None,
) -> list[float]:
    normalized_top = serialize_color(top_color)
    normalized_bottom = serialize_color(bottom_color)
    top_rgb = top_rgb or COLOR_PROTOTYPES[normalized_top]
    bottom_rgb = bottom_rgb or COLOR_PROTOTYPES[normalized_bottom]

    embedding: list[float] = []
    for color in KNOWN_COLORS:
        embedding.append(1.0 if normalized_top == color else 0.0)
    for color in KNOWN_COLORS:
        embedding.append(1.0 if normalized_bottom == color else 0.0)

    embedding.extend(
        [
            _encode_accessory(has_backpack),
            _encode_accessory(has_hat),
            *top_rgb,
            *bottom_rgb,
        ]
    )
    return embedding


def appearance_similarity(
    left_embedding: Optional[list[float]],
    right_embedding: Optional[list[float]],
) -> float:
    if not left_embedding or not right_embedding:
        return 0.0

    left = np.asarray(left_embedding, dtype=np.float32)
    right = np.asarray(right_embedding, dtype=np.float32)
    left_norm = np.linalg.norm(left)
    right_norm = np.linalg.norm(right)
    if left_norm == 0 or right_norm == 0:
        return 0.0

    similarity = float(np.dot(left, right) / (left_norm * right_norm))
    return max(0.0, min(1.0, similarity))


def extract_person_appearance(
    image_path: str,
    face_bbox: Optional[dict[str, int]] = None,
) -> PersonAppearanceAttributes:
    try:
        with Image.open(image_path) as image:
            frame = np.asarray(image.convert("RGB"))
    except Exception:
        return PersonAppearanceAttributes()

    if frame.size == 0:
        return PersonAppearanceAttributes()

    top_region, bottom_region, person_bbox = _estimate_body_regions(frame, face_bbox)
    top_rgb = _representative_rgb(top_region)
    bottom_rgb = _representative_rgb(bottom_region)
    top_color = _classify_region_color(top_region, top_rgb)
    bottom_color = _classify_region_color(bottom_region, bottom_rgb)
    has_backpack = _estimate_backpack(frame, face_bbox)
    has_hat = _estimate_hat(frame, face_bbox)

    return PersonAppearanceAttributes(
        top_color=top_color,
        bottom_color=bottom_color,
        has_backpack=has_backpack,
        has_hat=has_hat,
        person_bbox=person_bbox,
        top_rgb=top_rgb,
        bottom_rgb=bottom_rgb,
        embedding=build_appearance_embedding(
            top_color=top_color,
            bottom_color=bottom_color,
            has_backpack=has_backpack,
            has_hat=has_hat,
            top_rgb=top_rgb,
            bottom_rgb=bottom_rgb,
        ),
    )


def _estimate_body_regions(
    frame: np.ndarray,
    face_bbox: Optional[dict[str, int]],
) -> tuple[np.ndarray, np.ndarray, Optional[dict[str, int]]]:
    height, width = frame.shape[:2]

    if not face_bbox:
        top_region = _crop_region(
            frame,
            int(width * 0.20),
            int(height * 0.20),
            int(width * 0.80),
            int(height * 0.58),
        )
        bottom_region = _crop_region(
            frame,
            int(width * 0.22),
            int(height * 0.58),
            int(width * 0.78),
            int(height * 0.95),
        )
        return top_region, bottom_region, None

    x = int(face_bbox.get("x", 0))
    y = int(face_bbox.get("y", 0))
    w = max(1, int(face_bbox.get("w", 1)))
    h = max(1, int(face_bbox.get("h", 1)))
    center_x = x + (w // 2)

    body_left = max(0, int(center_x - (w * 1.6)))
    body_right = min(width, int(center_x + (w * 1.6)))
    body_top = max(0, int(y + (h * 0.85)))
    body_bottom = min(height, int(y + (h * 4.4)))

    top_region = _crop_region(
        frame,
        body_left,
        body_top,
        body_right,
        min(height, int(y + (h * 2.35))),
    )
    bottom_region = _crop_region(
        frame,
        body_left,
        min(height, int(y + (h * 2.35))),
        body_right,
        body_bottom,
    )
    person_bbox = {
        "x": int(body_left),
        "y": int(body_top),
        "w": int(max(0, body_right - body_left)),
        "h": int(max(0, body_bottom - body_top)),
    }
    return top_region, bottom_region, person_bbox


def _crop_region(
    frame: np.ndarray,
    left: int,
    top: int,
    right: int,
    bottom: int,
) -> np.ndarray:
    left = max(0, left)
    top = max(0, top)
    right = min(frame.shape[1], right)
    bottom = min(frame.shape[0], bottom)
    if right <= left or bottom <= top:
        return np.empty((0, 0, 3), dtype=np.uint8)
    return frame[top:bottom, left:right]


def _classify_region_color(
    region: np.ndarray,
    representative_rgb: Optional[tuple[float, float, float]] = None,
) -> str:
    if region.size == 0:
        return UNKNOWN_COLOR

    r, g, b = representative_rgb or _representative_rgb(region)
    hue, saturation, value = colorsys.rgb_to_hsv(r, g, b)

    if value < 0.18:
        return "black"
    if saturation < 0.12:
        if value > 0.9:
            return "white"
        if value > 0.7:
            return "silver"
        if value > 0.4:
            return "gray"
        return "black"
    if value < 0.42 and hue < 0.16:
        return "brown"
    if hue < 0.04 or hue >= 0.96:
        return "red"
    if hue < 0.10:
        return "orange"
    if hue < 0.18:
        return "yellow"
    if hue < 0.42:
        return "green"
    if hue < 0.68:
        return "blue"
    if hue < 0.82:
        return "purple"
    if value > 0.65:
        return "pink"
    return "red"


def _representative_rgb(region: np.ndarray) -> tuple[float, float, float]:
    if region.size == 0:
        return (0.0, 0.0, 0.0)

    pixels = region.reshape(-1, 3).astype(np.float32) / 255.0
    if pixels.size == 0:
        return (0.0, 0.0, 0.0)

    representative = np.median(pixels, axis=0)
    return tuple(float(channel) for channel in representative.tolist())


def _estimate_backpack(
    frame: np.ndarray,
    face_bbox: Optional[dict[str, int]],
) -> Optional[bool]:
    if not face_bbox:
        return None

    torso, left_band, right_band = _shoulder_regions(frame, face_bbox)
    if torso.size == 0 or left_band.size == 0 or right_band.size == 0:
        return None

    torso_darkness = _darkness_score(torso)
    side_darkness = max(_darkness_score(left_band), _darkness_score(right_band))
    torso_saturation = _saturation_score(torso)
    side_saturation = max(_saturation_score(left_band), _saturation_score(right_band))
    return side_darkness > (torso_darkness + 0.12) or side_saturation > (
        torso_saturation + 0.10
    )


def _estimate_hat(
    frame: np.ndarray,
    face_bbox: Optional[dict[str, int]],
) -> Optional[bool]:
    if not face_bbox:
        return None

    x = int(face_bbox.get("x", 0))
    y = int(face_bbox.get("y", 0))
    w = max(1, int(face_bbox.get("w", 1)))
    h = max(1, int(face_bbox.get("h", 1)))
    center_x = x + (w // 2)

    hat_band = _crop_region(
        frame,
        int(center_x - (w * 0.75)),
        int(y - (h * 0.60)),
        int(center_x + (w * 0.75)),
        int(y + (h * 0.18)),
    )
    forehead_band = _crop_region(
        frame,
        int(center_x - (w * 0.40)),
        int(y),
        int(center_x + (w * 0.40)),
        int(y + (h * 0.30)),
    )

    if hat_band.size == 0 or forehead_band.size == 0:
        return None

    hat_darkness = _darkness_score(hat_band)
    forehead_darkness = _darkness_score(forehead_band)
    hat_saturation = _saturation_score(hat_band)
    forehead_saturation = _saturation_score(forehead_band)
    return hat_darkness > (forehead_darkness + 0.14) or hat_saturation > (
        forehead_saturation + 0.14
    )


def _shoulder_regions(
    frame: np.ndarray,
    face_bbox: dict[str, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = int(face_bbox.get("x", 0))
    y = int(face_bbox.get("y", 0))
    w = max(1, int(face_bbox.get("w", 1)))
    h = max(1, int(face_bbox.get("h", 1)))
    center_x = x + (w // 2)

    torso = _crop_region(
        frame,
        int(center_x - (w * 0.65)),
        int(y + (h * 0.65)),
        int(center_x + (w * 0.65)),
        int(y + (h * 1.95)),
    )
    left_band = _crop_region(
        frame,
        int(center_x - (w * 1.65)),
        int(y + (h * 0.70)),
        int(center_x - (w * 0.75)),
        int(y + (h * 1.95)),
    )
    right_band = _crop_region(
        frame,
        int(center_x + (w * 0.75)),
        int(y + (h * 0.70)),
        int(center_x + (w * 1.65)),
        int(y + (h * 1.95)),
    )
    return torso, left_band, right_band


def _darkness_score(region: np.ndarray) -> float:
    pixels = region.reshape(-1, 3).astype(np.float32) / 255.0
    if pixels.size == 0:
        return 0.0
    brightness = np.mean(np.max(pixels, axis=1))
    return float(1.0 - brightness)


def _saturation_score(region: np.ndarray) -> float:
    pixels = region.reshape(-1, 3).astype(np.float32) / 255.0
    if pixels.size == 0:
        return 0.0

    sample = pixels[:: max(1, len(pixels) // 256)]
    saturations = [colorsys.rgb_to_hsv(*pixel)[1] for pixel in sample]
    return float(np.mean(saturations)) if saturations else 0.0


def _encode_accessory(value: Optional[bool]) -> float:
    if value is None:
        return 0.0
    return 1.0 if value else -1.0
