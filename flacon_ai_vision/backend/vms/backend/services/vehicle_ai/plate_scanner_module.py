from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .plate_normalizer import PlateNormalizer
from .plate_reader import PlateReadResult, PlateReader


@dataclass
class PlateScanResult:
    plate_result: Optional[PlateReadResult]
    raw_text: str
    plate_confidence: float
    plate_bbox: Optional[Dict[str, int]]
    plate_crop: Optional[np.ndarray]
    normalized_text: str
    compact_text: str
    plate_code: Optional[str]
    plate_city: Optional[str]
    plate_sequence: Optional[str]
    plate_display: Optional[str]
    plate_reliable: bool


class PlateScannerModule:
    """Single responsibility: scan/normalize plate text from an image region."""

    def __init__(
        self,
        *,
        reader: PlateReader,
        normalizer: PlateNormalizer,
        min_plate_conf: float,
        min_plate_chars: int,
        min_plate_digits: int,
        strict_tn_plate: bool,
    ):
        self.reader = reader
        self.normalizer = normalizer
        self.min_plate_conf = float(min_plate_conf)
        self.min_plate_chars = int(max(1, min_plate_chars))
        self.min_plate_digits = int(max(1, min_plate_digits))
        self.strict_tn_plate = bool(strict_tn_plate)

    def scan(
        self,
        *,
        frame_bgr: np.ndarray,
        vehicle_bbox: Optional[Tuple[int, int, int, int]],
    ) -> PlateScanResult:
        plate_result = self.reader.read_plate(frame_bgr, vehicle_bbox=vehicle_bbox)
        if plate_result is None:
            return PlateScanResult(
                plate_result=None,
                raw_text="",
                plate_confidence=0.0,
                plate_bbox=None,
                plate_crop=None,
                normalized_text="",
                compact_text="",
                plate_code=None,
                plate_city=None,
                plate_sequence=None,
                plate_display=None,
                plate_reliable=False,
            )

        raw_text = str(plate_result.raw_text or "").strip()
        plate_confidence = float(plate_result.confidence or 0.0)
        plate_bbox = self._bbox_to_dict(plate_result.bbox)
        plate_crop = plate_result.plate_crop

        selected_text, selected_conf = self._select_plate_text_from_candidates(
            raw_text=raw_text,
            raw_confidence=plate_confidence,
            candidates=plate_result.candidates,
        )
        if selected_text:
            raw_text = selected_text
            plate_confidence = max(float(plate_confidence), float(selected_conf))

        normalized_text = ""
        compact_text = ""
        plate_code: Optional[str] = None
        plate_city: Optional[str] = None
        plate_sequence: Optional[str] = None
        plate_display: Optional[str] = None
        plate_reliable = False

        if plate_confidence >= self.min_plate_conf and self._is_plate_text_plausible(raw_text):
            normalized = self.normalizer.normalize(raw_text)
            normalized_text = normalized.normalized_text
            compact_text = normalized.compact_text
            plate_code = normalized.plate_code
            plate_city = normalized.plate_city
            plate_sequence = normalized.plate_sequence
            plate_display = normalized.display_text
            plate_reliable = True

        return PlateScanResult(
            plate_result=plate_result,
            raw_text=raw_text,
            plate_confidence=plate_confidence,
            plate_bbox=plate_bbox,
            plate_crop=plate_crop,
            normalized_text=normalized_text,
            compact_text=compact_text,
            plate_code=plate_code,
            plate_city=plate_city,
            plate_sequence=plate_sequence,
            plate_display=plate_display,
            plate_reliable=plate_reliable,
        )

    def normalize_text(self, raw_text: str) -> Dict[str, Optional[str]]:
        normalized = self.normalizer.normalize(raw_text or "")
        return {
            "normalized_text": normalized.normalized_text,
            "compact_text": normalized.compact_text,
            "plate_code": normalized.plate_code,
            "plate_city": normalized.plate_city,
            "plate_sequence": normalized.plate_sequence,
            "plate_display": normalized.display_text,
        }

    def is_text_plausible(self, text: str) -> bool:
        return self._is_plate_text_plausible(text)

    def _bbox_to_dict(self, bbox: Optional[Tuple[int, int, int, int]]) -> Optional[Dict[str, int]]:
        if bbox is None:
            return None
        x, y, w, h = bbox
        return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}

    def _is_plate_text_plausible(self, text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False

        compact = re.sub(r"[^0-9A-Za-z\u0600-\u06FF]+", "", raw)
        if len(compact) < self.min_plate_chars:
            return False

        digit_count = sum(1 for ch in compact if ch.isdigit())
        if digit_count < self.min_plate_digits:
            return False

        if not self.strict_tn_plate:
            return True

        normalized = self.normalizer.normalize(raw)
        if normalized.plate_code and normalized.plate_sequence:
            return True

        compact_up = normalized.compact_text.upper()
        if re.fullmatch(r"\d{3,8}", compact_up):
            return True
        if re.search(r"(TUNIS|TN|\u062a\u0648\u0646\u0633)", normalized.normalized_text.upper()) and digit_count >= 3:
            return True
        return False

    def _select_plate_text_from_candidates(
        self,
        *,
        raw_text: str,
        raw_confidence: float,
        candidates: Optional[List[Dict[str, Any]]],
    ) -> tuple[str, float]:
        best_text = str(raw_text or "").strip()
        best_conf = float(raw_confidence or 0.0)

        if best_text and self._is_plate_text_plausible(best_text):
            return best_text, best_conf

        rows = list(candidates or [])
        if not rows:
            return best_text, best_conf

        rows_sorted = sorted(
            rows,
            key=lambda r: (
                float(r.get("score", 0.0)),
                float(r.get("confidence", 0.0)),
            ),
            reverse=True,
        )
        for row in rows_sorted:
            txt = str(row.get("text") or "").strip()
            conf = float(row.get("confidence", 0.0))
            if not txt:
                continue
            if conf < max(0.05, float(self.min_plate_conf) * 0.6):
                continue
            if self._is_plate_text_plausible(txt):
                return txt, conf

        merged_text, merged_conf = self._merge_numeric_candidate_tokens(rows_sorted)
        if merged_text and self._is_plate_text_plausible(merged_text):
            return merged_text, merged_conf

        return best_text, best_conf

    def _merge_numeric_candidate_tokens(self, rows: List[Dict[str, Any]]) -> tuple[str, float]:
        if not rows:
            return "", 0.0

        parts: List[Dict[str, Any]] = []
        for row in rows:
            txt = str(row.get("text") or "").strip()
            if not txt:
                continue
            conf = float(row.get("confidence", 0.0))
            x_center = float(row.get("x_center", 0.0))
            tokens = [t for t in re.split(r"\s+", txt) if t]
            for token in tokens:
                token_compact = re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", token.upper())
                if not token_compact:
                    continue
                if not re.search(r"\d", token_compact):
                    continue
                parts.append(
                    {
                        "token": token_compact,
                        "confidence": conf,
                        "x_center": x_center,
                    }
                )

        if len(parts) < 2:
            return "", 0.0

        dedup: Dict[str, Dict[str, Any]] = {}
        for part in parts:
            key = f"{part['token']}:{int(float(part['x_center']) // 10)}"
            if key not in dedup or float(part["confidence"]) > float(dedup[key]["confidence"]):
                dedup[key] = part

        ordered = sorted(dedup.values(), key=lambda p: (float(p["x_center"]), -float(p["confidence"])))
        token_values = [str(part["token"]) for part in ordered]
        if len(token_values) < 2:
            return "", 0.0

        merged = " ".join(token_values[:3]).strip()
        confs = [float(part["confidence"]) for part in ordered[:3]]
        return merged, (sum(confs) / max(1, len(confs)))
