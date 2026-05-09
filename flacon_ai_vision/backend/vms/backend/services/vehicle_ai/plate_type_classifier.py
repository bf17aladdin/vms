from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import List, Optional

import numpy as np
from sqlalchemy.orm import Session


@dataclass
class PlateTypeClassification:
    plate_type: str
    confidence: float
    reason: str
    military_score: float
    civil_score: float
    security_tag: Optional[str] = None
    matched_registry: bool = False
    reasons: List[str] = field(default_factory=list)


class PlateTypeClassifier:
    """Hybrid classifier (registry + regex + keyword + visual cues)."""

    _registry_lock = Lock()
    _registry_cache: List[tuple[str, str]] = []
    _registry_cache_ts: float = 0.0

    def __init__(self, db: Session):
        self.db = db
        self.registry_cache_ttl = int(os.getenv("VEHICLE_REGISTRY_CACHE_TTL_SEC", "30"))
        self.min_margin = float(os.getenv("VEHICLE_MILITARY_MARGIN", "0.05"))

        self._military_keywords = self._csv_env(
            "MILITARY_PLATE_KEYWORDS",
            "MIL,ARMY,ARMEE,MILITAIRE,DEFENSE,GENDARMERIE,FORCE,\u0639\u0633\u0643\u0631\u064A,\u0639\u0633\u0643\u0631\u064A\u0629,\u062C\u064A\u0634",
        )
        self._civil_keywords = self._csv_env(
            "CIVIL_PLATE_KEYWORDS",
            "TUNIS,TN,\u062A\u0648\u0646\u0633,CIVIL",
        )
        self._military_patterns = self._compile_patterns(
            self._pattern_env(
                "MILITARY_PLATE_REGEX",
                [
                    r"(^|\W)M[0-9]{2,6}($|\W)",
                    r"(^|\W)(MIL|ARMY|DEFENSE)($|\W)",
                    r"(^|\W)[0-9]{2,3}\s*[0-9]{2,4}($|\W)",
                ],
            )
        )
        self._civil_patterns = self._compile_patterns(
            self._pattern_env(
                "CIVIL_PLATE_REGEX",
                [
                    r"[0-9]{2,4}\s*(TN|TUNIS|\u062A\u0648\u0646\u0633)\s*[0-9]{2,4}",
                    r"(^|\W)[A-Z]{1,3}\s*[0-9]{1,4}($|\W)",
                ],
            )
        )

    def classify(
        self,
        normalized_text: str,
        compact_text: str,
        raw_text: str,
        plate_crop: Optional[np.ndarray] = None,
    ) -> PlateTypeClassification:
        if not normalized_text and not compact_text and not raw_text:
            return PlateTypeClassification(
                plate_type="unknown",
                confidence=0.50,
                reason="empty_plate_text",
                military_score=0.0,
                civil_score=0.0,
                matched_registry=False,
                reasons=["empty_plate_text"],
            )

        # 1) Strong override from registry if known plate.
        registry = self._classify_from_registry(normalized_text=normalized_text, compact_text=compact_text)
        if registry is not None:
            return registry

        military_score = 0.0
        civil_score = 0.0
        reasons: List[str] = []

        payload = f"{raw_text} {normalized_text} {compact_text}".upper()
        numeric_pair_like = bool(re.fullmatch(r"\s*\d{2,3}\s+\d{2,4}\s*", (normalized_text or raw_text or "").strip()))

        # 2) Keyword signals.
        for keyword in self._military_keywords:
            if keyword and keyword in payload:
                military_score += 0.45
                reasons.append(f"military_keyword:{keyword}")
                break
        for keyword in self._civil_keywords:
            if keyword and keyword in payload:
                if numeric_pair_like and keyword in {"TN", "TUNIS", "تونس"}:
                    civil_score += 0.10
                    reasons.append(f"civil_keyword_weak:{keyword}")
                else:
                    civil_score += 0.35
                    reasons.append(f"civil_keyword:{keyword}")
                break

        # 3) Pattern signals.
        military_pattern = self._match_patterns(payload, self._military_patterns)
        civil_pattern = self._match_patterns(payload, self._civil_patterns)
        if military_pattern:
            military_score += 0.35
            reasons.append("military_pattern")
        if civil_pattern:
            if numeric_pair_like and re.search(r"(TUNIS|TN|تونس)", payload):
                civil_score += 0.10
                reasons.append("civil_pattern_weak_numeric_pair")
            else:
                civil_score += 0.35
                reasons.append("civil_pattern")

        # 3b) Numeric pair format (e.g., "36 207") is a frequent military fallback pattern.
        # Keep score moderate to avoid overriding strong civil signals.
        if numeric_pair_like:
            military_score += 0.22
            reasons.append("military_numeric_pair_format")

        # 4) Visual cue (red emblem on left side often military identifiers).
        visual_red = self._estimate_left_red_ratio(plate_crop)
        if visual_red >= 0.06:
            military_score += 0.20
            reasons.append("visual_red_emblem")
        if numeric_pair_like and visual_red >= 0.04:
            military_score += 0.28
            reasons.append("military_red_numeric_pair")

        # Prior: civil default unless military evidence is stronger.
        civil_score += 0.20

        if not reasons and len(compact_text) < 4:
            return PlateTypeClassification(
                plate_type="unknown",
                confidence=0.55,
                reason="insufficient_signal",
                military_score=military_score,
                civil_score=civil_score,
                matched_registry=False,
                reasons=["insufficient_signal"],
            )

        is_military = military_score >= (civil_score + self.min_margin)
        margin = abs(military_score - civil_score)
        best_score = max(military_score, civil_score)
        confidence = float(max(0.50, min(0.99, 0.50 + (0.8 * margin) + (0.2 * best_score))))

        if is_military:
            return PlateTypeClassification(
                plate_type="military",
                confidence=confidence,
                reason="rule_based_military",
                military_score=military_score,
                civil_score=civil_score,
                security_tag="military_vehicle",
                matched_registry=False,
                reasons=reasons,
            )
        return PlateTypeClassification(
            plate_type="civil",
            confidence=confidence,
            reason="rule_based_civil",
            military_score=military_score,
            civil_score=civil_score,
            security_tag=None,
            matched_registry=False,
            reasons=reasons,
        )

    def _classify_from_registry(
        self,
        normalized_text: str,
        compact_text: str,
    ) -> Optional[PlateTypeClassification]:
        if not compact_text and not normalized_text:
            return None

        target = compact_text or normalized_text.replace(" ", "")
        rows = self._get_registry_entries()

        best_category = None
        best_score = -1
        for plate_compact, category in rows:
            if plate_compact == target:
                best_category = category
                best_score = 10_000
                break
            if not plate_compact or not target:
                continue
            if plate_compact in target or target in plate_compact:
                score = min(len(plate_compact), len(target))
                if score > best_score:
                    best_score = score
                    best_category = category

        if best_category is None or best_score <= 2:
            return None

        plate_type = "military" if str(best_category).lower().startswith("mil") else "civil"
        return PlateTypeClassification(
            plate_type=plate_type,
            confidence=0.98,
            reason="registry_match",
            military_score=1.0 if plate_type == "military" else 0.0,
            civil_score=1.0 if plate_type == "civil" else 0.0,
            security_tag="military_vehicle" if plate_type == "military" else None,
            matched_registry=True,
            reasons=["registry_match"],
        )

    def _get_registry_entries(self) -> List[tuple[str, str]]:
        now = time.time()
        with self._registry_lock:
            if (now - self._registry_cache_ts) <= self.registry_cache_ttl and self._registry_cache:
                return self._registry_cache

            from vms.backend.models import VehicleRegistry

            rows = self.db.query(VehicleRegistry.matricule, VehicleRegistry.categorie).all()
            cache: List[tuple[str, str]] = []
            for plate, category in rows:
                compact = re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", str(plate or "").strip().upper())
                if not compact:
                    continue
                cache.append((compact, str(category or "civil").strip().lower()))

            self._registry_cache = cache
            self._registry_cache_ts = now
            return cache

    def _estimate_left_red_ratio(self, plate_crop: Optional[np.ndarray]) -> float:
        if plate_crop is None or plate_crop.size == 0:
            return 0.0
        try:
            _h, w = plate_crop.shape[:2]
            left = plate_crop[:, : max(1, int(w * 0.35))]
            b = left[:, :, 0].astype(np.int16)
            g = left[:, :, 1].astype(np.int16)
            r = left[:, :, 2].astype(np.int16)
            mask = (r > 120) & (r - g > 45) & (r - b > 45)
            return float(mask.mean())
        except Exception:
            return 0.0

    def _csv_env(self, key: str, default: str) -> List[str]:
        raw = os.getenv(key, default)
        return [item.strip().upper() for item in raw.split(",") if item.strip()]

    def _pattern_env(self, key: str, default: List[str]) -> List[str]:
        """
        Regex env parser that avoids splitting by ',' because quantifiers use commas.
        Supported separators for multiple regexes: ';' or newline.
        """
        raw = str(os.getenv(key, "") or "").strip()
        if not raw:
            return list(default)
        if "\n" in raw:
            rows = [row.strip() for row in raw.splitlines() if row.strip()]
            return rows or list(default)
        if ";" in raw:
            rows = [row.strip() for row in raw.split(";") if row.strip()]
            return rows or list(default)
        # Single regex payload.
        return [raw]

    def _compile_patterns(self, patterns: List[str]) -> List[re.Pattern]:
        out: List[re.Pattern] = []
        for pattern in patterns:
            try:
                out.append(re.compile(pattern, re.IGNORECASE))
            except Exception:
                continue
        return out

    def _match_patterns(self, text: str, patterns: List[re.Pattern]) -> bool:
        for pattern in patterns:
            if pattern.search(text):
                return True
        return False
