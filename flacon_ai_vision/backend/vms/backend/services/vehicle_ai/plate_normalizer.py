from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


_ARABIC_INDIC_DIGITS = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")
_EXT_ARABIC_INDIC_DIGITS = str.maketrans("\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9", "0123456789")
_TUNIS_CITY = "\u062a\u0648\u0646\u0633"


@dataclass
class PlateNormalizationResult:
    raw_text: str
    normalized_text: str
    compact_text: str
    tokens: List[str]
    plate_code: Optional[str] = None
    plate_city: Optional[str] = None
    plate_sequence: Optional[str] = None
    display_text: Optional[str] = None


class PlateNormalizer:
    """Normalize OCR text into a stable plate representation."""

    _space_re = re.compile(r"\s+")
    _strip_re = re.compile(r"[^0-9A-Z\u0600-\u06FF]+", re.IGNORECASE)
    _compact_re = re.compile(r"[^0-9A-Z\u0600-\u06FF]", re.IGNORECASE)
    _digit_re = re.compile(r"^\d+$")

    def normalize(self, text: str) -> PlateNormalizationResult:
        raw = (text or "").strip()
        stage = raw.translate(_ARABIC_INDIC_DIGITS).translate(_EXT_ARABIC_INDIC_DIGITS)
        stage = stage.upper()
        stage = self._strip_re.sub(" ", stage)
        stage = self._space_re.sub(" ", stage).strip()
        compact = self._compact_re.sub("", stage)
        tokens = [token for token in stage.split(" ") if token]
        code, sequence = self._extract_code_and_sequence(tokens)
        city = self._extract_city(tokens)
        display_text = f"{code} {_TUNIS_CITY} {sequence}" if code and sequence and city else None

        return PlateNormalizationResult(
            raw_text=raw,
            normalized_text=stage,
            compact_text=compact,
            tokens=tokens,
            plate_code=code,
            plate_city=city,
            plate_sequence=sequence,
            display_text=display_text,
        )

    def _extract_city(self, tokens: List[str]) -> Optional[str]:
        for token in tokens:
            if token in {_TUNIS_CITY, "TUNIS", "TN"}:
                return _TUNIS_CITY
        return None

    def _extract_code_and_sequence(self, tokens: List[str]) -> Tuple[Optional[str], Optional[str]]:
        digits = [token for token in tokens if self._digit_re.match(token)]
        if len(digits) < 2:
            return None, None

        first = digits[0]
        second = digits[1]
        return self._choose_code_and_sequence(first, second)

    def _choose_code_and_sequence(self, first: str, second: str) -> Tuple[str, str]:
        if len(first) < len(second):
            return first, second
        if len(second) < len(first):
            return second, first

        # Equal length fallback: prefer the smallest numeric token as code.
        try:
            if int(first) <= int(second):
                return first, second
            return second, first
        except Exception:
            return first, second
