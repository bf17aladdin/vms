from __future__ import annotations

from dataclasses import dataclass
import os
import re
import time
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

from .plate_normalizer import PlateNormalizer
from .plate_type_classifier import PlateTypeClassification, PlateTypeClassifier
from .vehicle_profile_classifier import LightVehicleProfileClassifier
from .tiny_onnx_brand_classifier import TinyOnnxBrandClassifier
from .tiny_onnx_terrain_classifier import TinyOnnxTerrainClassifier
from .vehicle_taxonomy import (
    normalize_vehicle_brand,
    normalize_vehicle_category,
    normalize_vehicle_color,
    normalize_vehicle_model,
    vehicle_brand_logo_path,
    vehicle_brand_key,
)


@dataclass
class PlateIdentity:
    plate_number: Optional[str]
    plate_display: Optional[str]
    plate_code: Optional[str]
    plate_city: Optional[str]
    plate_sequence: Optional[str]


class VehicleAttributesModule:
    """Single responsibility: classify and format vehicle/plate attributes."""

    _registry_lock = Lock()
    _registry_cache: List[Dict[str, Any]] = []
    _registry_cache_ts: float = 0.0

    def __init__(self, *, db: Session, default_civil_city: str):
        self.db = db
        self.default_civil_city = str(default_civil_city or "").strip()
        self.normalizer = PlateNormalizer()
        self.profile_classifier = LightVehicleProfileClassifier()
        self.registry_cache_ttl = int(os.getenv("VEHICLE_REGISTRY_CACHE_TTL_SEC", "30"))
        onnx_enabled = str(os.getenv("VEHICLE_TINY_BRAND_ONNX_ENABLE", "false")).strip().lower() == "true"
        onnx_input_size = int(os.getenv("VEHICLE_TINY_BRAND_ONNX_INPUT_SIZE", "112"))
        self.tiny_brand_min_conf = float(os.getenv("VEHICLE_TINY_BRAND_ONNX_MIN_CONF", "0.55"))
        self.tiny_terrain_brand_min_conf = float(
            os.getenv("VEHICLE_TINY_TERRAIN_BRAND_MIN_CONF", str(self.tiny_brand_min_conf))
        )
        self.tiny_terrain_color_min_conf = float(os.getenv("VEHICLE_TINY_TERRAIN_COLOR_MIN_CONF", "0.45"))
        self.tiny_terrain_model_min_conf = float(os.getenv("VEHICLE_TINY_TERRAIN_MODEL_MIN_CONF", "0.50"))
        self._onnx_brand_classifier = TinyOnnxBrandClassifier(
            enabled=onnx_enabled,
            model_path=os.getenv("VEHICLE_TINY_BRAND_ONNX_MODEL_PATH", ""),
            labels_path=os.getenv("VEHICLE_TINY_BRAND_ONNX_LABELS_PATH", ""),
            input_size=onnx_input_size,
        )
        self._onnx_terrain_classifier = TinyOnnxTerrainClassifier(
            enabled=onnx_enabled,
            brand_model_path=(
                os.getenv("VEHICLE_TINY_TERRAIN_ONNX_BRAND_MODEL_PATH", "").strip()
                or os.getenv("VEHICLE_TINY_BRAND_ONNX_MODEL_PATH", "").strip()
            ),
            brand_labels_path=(
                os.getenv("VEHICLE_TINY_TERRAIN_ONNX_BRAND_LABELS_PATH", "").strip()
                or os.getenv("VEHICLE_TINY_BRAND_ONNX_LABELS_PATH", "").strip()
            ),
            color_model_path=os.getenv("VEHICLE_TINY_TERRAIN_ONNX_COLOR_MODEL_PATH", ""),
            color_labels_path=os.getenv("VEHICLE_TINY_TERRAIN_ONNX_COLOR_LABELS_PATH", ""),
            model_model_path=os.getenv("VEHICLE_TINY_TERRAIN_ONNX_MODEL_MODEL_PATH", ""),
            model_labels_path=os.getenv("VEHICLE_TINY_TERRAIN_ONNX_MODEL_LABELS_PATH", ""),
            input_size=int(os.getenv("VEHICLE_TINY_TERRAIN_ONNX_INPUT_SIZE", str(onnx_input_size))),
        )

    def classify_plate_type(
        self,
        *,
        plate_reliable: bool,
        normalized_text: str,
        compact_text: str,
        raw_text: str,
        plate_crop,
    ) -> Optional[PlateTypeClassification]:
        if not plate_reliable:
            return None
        if not (normalized_text or compact_text or raw_text):
            return None
        return PlateTypeClassifier(self.db).classify(
            normalized_text=normalized_text,
            compact_text=compact_text,
            raw_text=raw_text,
            plate_crop=plate_crop,
        )

    def resolve_plate_identity(
        self,
        *,
        plate_reliable: bool,
        plate_type: str,
        normalized_text: str,
        raw_text: str,
        plate_code: Optional[str],
        plate_city: Optional[str],
        plate_sequence: Optional[str],
        plate_display: Optional[str],
    ) -> PlateIdentity:
        next_plate_code = plate_code
        next_plate_city = plate_city
        next_plate_sequence = plate_sequence
        next_plate_display = plate_display

        if plate_reliable and plate_type == "civil" and next_plate_code and next_plate_sequence:
            next_plate_city = next_plate_city or self.default_civil_city
            next_plate_display = f"{next_plate_code} {next_plate_city} {next_plate_sequence}"

        plate_number = (
            next_plate_display
            or normalized_text
            or str(raw_text or "").strip().upper()
            or None
        ) if plate_reliable else None

        return PlateIdentity(
            plate_number=plate_number,
            plate_display=plate_number,
            plate_code=next_plate_code,
            plate_city=next_plate_city,
            plate_sequence=next_plate_sequence,
        )

    def infer_vehicle_profile(
        self,
        *,
        class_name: Optional[str],
        bbox: Optional[Tuple[int, int, int, int]],
        frame_bgr: Optional[np.ndarray] = None,
        plate_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        predicted = self.profile_classifier.predict(
            class_name=class_name,
            bbox=bbox,
            frame_bgr=frame_bgr,
        )
        profile = predicted.to_dict()
        profile["dominant_color"] = normalize_vehicle_color(profile.get("dominant_color"))
        profile["make"] = None
        profile["brand"] = None
        profile["brand_key"] = None
        profile["logo_path"] = None
        profile["model"] = None
        profile["registry_category"] = None
        profile["registry_color"] = None
        profile["registry_make"] = None
        profile["registry_match"] = False
        profile["brand_confidence"] = None
        profile["brand_source"] = None
        profile["color_confidence"] = None
        profile["color_source"] = None
        profile["model_confidence"] = None
        profile["model_source"] = None

        registry = self._find_registry_profile(plate_number=plate_number)
        if registry is not None:
            registry_brand = normalize_vehicle_brand(registry.get("marque"))
            registry_model = normalize_vehicle_model(registry.get("modele"))
            registry_category = normalize_vehicle_category(registry.get("categorie"))
            registry_color = normalize_vehicle_color(registry.get("couleur"))
            profile["make"] = registry_brand
            profile["brand"] = registry_brand
            profile["brand_key"] = vehicle_brand_key(registry_brand)
            profile["model"] = registry_model
            profile["registry_category"] = registry_category
            profile["registry_color"] = registry_color if registry_color != "unknown" else None
            profile["registry_make"] = registry_brand
            profile["registry_match"] = True
            profile["brand_source"] = "registry"

            current_color = normalize_vehicle_color(profile.get("dominant_color"))
            if registry_color != "unknown" and current_color in {"unknown", "gray", "silver"}:
                profile["dominant_color"] = registry_color

            profile["source"] = f'{profile.get("source", "light_profile_classifier_v1")}+registry'
            profile["confidence"] = round(float(max(float(profile.get("confidence", 0.0)), 0.86)), 3)
        else:
            terrain_applied = False
            terrain_brand_applied = False
            terrain = self._predict_onnx_terrain(frame_bgr=frame_bgr, bbox=bbox)
            if terrain is not None:
                terrain_source = str(terrain.get("source") or "onnxruntime")
                color_conf = float(terrain.get("color_confidence", 0.0))
                color_value = normalize_vehicle_color(str(terrain.get("color") or "").strip())
                if color_value != "unknown" and color_conf >= self.tiny_terrain_color_min_conf:
                    profile["dominant_color"] = color_value
                    profile["color_confidence"] = round(color_conf, 3)
                    profile["color_source"] = terrain_source
                    terrain_applied = True

                model_conf = float(terrain.get("model_confidence", 0.0))
                model_value = normalize_vehicle_model(str(terrain.get("model") or "").strip() or None)
                if model_value and model_conf >= self.tiny_terrain_model_min_conf:
                    profile["model"] = model_value
                    profile["model_confidence"] = round(model_conf, 3)
                    profile["model_source"] = terrain_source
                    terrain_applied = True

                brand_conf = float(terrain.get("brand_confidence", 0.0))
                brand_value = normalize_vehicle_brand(str(terrain.get("brand") or "").strip())
                if brand_value and brand_conf >= self.tiny_terrain_brand_min_conf:
                    profile["make"] = brand_value
                    profile["brand"] = brand_value
                    profile["brand_key"] = vehicle_brand_key(brand_value)
                    profile["brand_confidence"] = round(brand_conf, 3)
                    profile["brand_source"] = terrain_source
                    terrain_applied = True
                    terrain_brand_applied = True

                if terrain_applied:
                    profile["source"] = f'{profile.get("source", "light_profile_classifier_v1")}+onnx_terrain'
                    base_conf = float(profile.get("confidence", 0.0))
                    conf_candidates = [
                        float(value)
                        for value in (
                            terrain.get("brand_confidence"),
                            terrain.get("color_confidence"),
                            terrain.get("model_confidence"),
                        )
                        if value is not None and float(value) > 0.0
                    ]
                    if conf_candidates:
                        merged = (0.75 * base_conf) + (0.25 * max(conf_candidates))
                        profile["confidence"] = round(float(max(base_conf, min(0.96, merged))), 3)

            if not terrain_brand_applied:
                onnx_brand = self._predict_onnx_brand(frame_bgr=frame_bgr, bbox=bbox)
                if onnx_brand is not None and float(onnx_brand.get("confidence", 0.0)) >= self.tiny_brand_min_conf:
                    brand_value = normalize_vehicle_brand(str(onnx_brand.get("brand") or "").strip())
                    if brand_value:
                        profile["make"] = brand_value
                        profile["brand"] = brand_value
                        profile["brand_key"] = vehicle_brand_key(brand_value)
                        profile["brand_confidence"] = round(float(onnx_brand.get("confidence", 0.0)), 3)
                        profile["brand_source"] = str(onnx_brand.get("source") or "onnxruntime")
                        profile["source"] = f'{profile.get("source", "light_profile_classifier_v1")}+onnx_brand'
                        base_conf = float(profile.get("confidence", 0.0))
                        merged = (0.70 * base_conf) + (0.30 * float(onnx_brand.get("confidence", 0.0)))
                        profile["confidence"] = round(float(max(base_conf, min(0.96, merged))), 3)

        if profile.get("brand"):
            normalized_brand = normalize_vehicle_brand(profile.get("brand"))
            profile["brand"] = normalized_brand
            profile["make"] = normalized_brand
            profile["brand_key"] = vehicle_brand_key(normalized_brand)
            profile["logo_path"] = vehicle_brand_logo_path(normalized_brand)
        else:
            profile["brand"] = None
            profile["make"] = None
            profile["brand_key"] = None
            profile["logo_path"] = None

        profile["model"] = normalize_vehicle_model(profile.get("model"))
        profile["dominant_color"] = normalize_vehicle_color(profile.get("dominant_color"))
        registry_color_value = normalize_vehicle_color(profile.get("registry_color"))
        profile["registry_color"] = registry_color_value if registry_color_value != "unknown" else None
        registry_make_value = normalize_vehicle_brand(profile.get("registry_make"))
        profile["registry_make"] = registry_make_value
        registry_category_value = normalize_vehicle_category(profile.get("registry_category"))
        profile["registry_category"] = registry_category_value if registry_category_value != "unknown" else None

        return profile

    def _predict_onnx_brand(
        self,
        *,
        frame_bgr: Optional[np.ndarray],
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> Optional[Dict[str, Any]]:
        classifier = self._onnx_brand_classifier
        if classifier is None or not getattr(classifier, "available", False):
            return None
        try:
            prediction = classifier.predict(frame_bgr=frame_bgr, bbox=bbox)
        except Exception:
            return None
        if prediction is None:
            return None
        return {
            "brand": prediction.brand,
            "confidence": float(prediction.confidence),
            "class_index": int(prediction.class_index),
            "source": prediction.source,
        }

    def _predict_onnx_terrain(
        self,
        *,
        frame_bgr: Optional[np.ndarray],
        bbox: Optional[Tuple[int, int, int, int]],
    ) -> Optional[Dict[str, Any]]:
        classifier = self._onnx_terrain_classifier
        if classifier is None or not getattr(classifier, "available", False):
            return None
        try:
            prediction = classifier.predict(frame_bgr=frame_bgr, bbox=bbox)
        except Exception:
            return None
        if prediction is None:
            return None
        return {
            "brand": prediction.brand,
            "brand_confidence": float(max(0.0, min(1.0, prediction.brand_confidence))),
            "color": prediction.color,
            "color_confidence": float(max(0.0, min(1.0, prediction.color_confidence))),
            "model": prediction.model,
            "model_confidence": float(max(0.0, min(1.0, prediction.model_confidence))),
            "source": prediction.source,
        }

    def _find_registry_profile(self, *, plate_number: Optional[str]) -> Optional[Dict[str, Any]]:
        if not plate_number:
            return None
        normalized = self.normalizer.normalize(str(plate_number))
        target = normalized.compact_text or re.sub(
            r"[^0-9A-Z\u0600-\u06FF]+",
            "",
            str(plate_number).strip().upper(),
        )
        if not target:
            return None

        best_row: Optional[Dict[str, Any]] = None
        best_score = -1
        for row in self._get_registry_rows():
            compact = str(row.get("compact") or "")
            if not compact:
                continue
            if compact == target:
                return row
            if compact in target or target in compact:
                score = min(len(compact), len(target))
                if score > best_score:
                    best_score = score
                    best_row = row
        return best_row if best_score >= 4 else None

    def _get_registry_rows(self) -> List[Dict[str, Any]]:
        now = time.time()
        with self._registry_lock:
            if (now - self._registry_cache_ts) <= self.registry_cache_ttl and self._registry_cache:
                return self._registry_cache

            from vms.backend.models import VehicleRegistry

            try:
                rows = self.db.query(
                    VehicleRegistry.matricule,
                    VehicleRegistry.marque,
                    VehicleRegistry.modele,
                    VehicleRegistry.couleur,
                    VehicleRegistry.categorie,
                ).all()
            except Exception:
                return []

            cache: List[Dict[str, Any]] = []
            for matricule, marque, modele, couleur, categorie in rows:
                compact = re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", str(matricule or "").strip().upper())
                if not compact:
                    continue
                normalized_brand = normalize_vehicle_brand(str(marque or "").strip() or None)
                normalized_model = normalize_vehicle_model(str(modele or "").strip() or None)
                normalized_color = normalize_vehicle_color(str(couleur or "").strip() or None)
                normalized_category = normalize_vehicle_category(str(categorie or "").strip() or None)
                cache.append(
                    {
                        "compact": compact,
                        "marque": normalized_brand,
                        "modele": normalized_model,
                        "couleur": normalized_color if normalized_color != "unknown" else None,
                        "categorie": normalized_category if normalized_category != "unknown" else None,
                    }
                )

            self._registry_cache = cache
            self._registry_cache_ts = now
            return cache
