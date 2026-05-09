from __future__ import annotations

from typing import Optional

from .vehicle_taxonomy import (
    get_supported_vehicle_body_styles,
    get_supported_vehicle_colors,
    get_supported_vehicle_types,
    normalize_vehicle_body_style,
    normalize_vehicle_color,
    normalize_vehicle_type,
)

UNKNOWN_ATTRIBUTE_FILTER = "__unknown__"
_UNKNOWN_FILTER_ALIASES = {"unknown", "inconnu", "na", "n/a", "n a"}


def _clean_text(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _is_unknown_alias(value: Optional[str]) -> bool:
    text = _clean_text(value)
    if text is None:
        return False
    normalized = text.lower().replace("_", " ").replace("-", " ")
    normalized = " ".join(part for part in normalized.split() if part)
    return normalized in _UNKNOWN_FILTER_ALIASES


def normalize_vehicle_color_filter(value: Optional[str]) -> Optional[str]:
    text = _clean_text(value)
    if text is None:
        return None
    normalized = normalize_vehicle_color(text)
    if normalized != "unknown":
        return normalized
    if _is_unknown_alias(text):
        return UNKNOWN_ATTRIBUTE_FILTER
    supported = ", ".join(color for color in get_supported_vehicle_colors() if color != "unknown")
    raise ValueError(f"Unsupported color '{value}'. Supported values: {supported}, unknown")


def normalize_vehicle_body_style_filter(value: Optional[str]) -> Optional[str]:
    text = _clean_text(value)
    if text is None:
        return None
    normalized = normalize_vehicle_body_style(text)
    if normalized:
        return normalized
    if _is_unknown_alias(text):
        return UNKNOWN_ATTRIBUTE_FILTER
    supported = ", ".join(get_supported_vehicle_body_styles())
    raise ValueError(f"Unsupported body_style '{value}'. Supported values: {supported}, unknown")


def normalize_vehicle_type_filter(value: Optional[str]) -> Optional[str]:
    text = _clean_text(value)
    if text is None:
        return None
    normalized = normalize_vehicle_type(text)
    if normalized and normalized != "unknown":
        return normalized
    if normalized == "unknown" or _is_unknown_alias(text):
        return UNKNOWN_ATTRIBUTE_FILTER
    supported = ", ".join(value for value in get_supported_vehicle_types() if value != "unknown")
    raise ValueError(f"Unsupported vehicle_type '{value}'. Supported values: {supported}, unknown")
