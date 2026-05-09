from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from vms.backend.routers.vehicle_recognition import _build_detect_payload_from_modular_result
from vms.backend.services.vehicle_ai.vehicle_attributes_module import VehicleAttributesModule
from vms.backend.services.vehicle_ai.vehicle_anomaly_module import VehicleAnomalyModule
from vms.backend.services.vehicle_ai.vehicle_alert_engine_module import VehicleAlertEngineModule
from vms.backend.services.vehicle_ai.vehicle_consistency_module import VehicleConsistencyModule
from vms.backend.services.vehicle_ai.vehicle_live_monitoring_module import VehicleLiveMonitoringModule
from vms.backend.services.vehicle_ai.vehicle_detection_module import VehicleDetectionModule
from vms.backend.services.vehicle_ai.vehicle_detector import VehicleDetection
from vms.backend.services.vehicle_ai.ocr_stabilizer_module import OcrStabilizerModule
from vms.backend.services.vehicle_ai.vehicle_taxonomy import (
    normalize_vehicle_brand,
    normalize_vehicle_body_style,
    normalize_vehicle_category,
    normalize_vehicle_color,
    vehicle_brand_logo_path,
    vehicle_brand_key,
)


class _DummyDb:
    pass


class _FakeDetector:
    def __init__(self, sequences):
        self._sequences = list(sequences)
        self._idx = 0

    def detect(self, _frame):
        if not self._sequences:
            return []
        idx = min(self._idx, len(self._sequences) - 1)
        self._idx += 1
        return self._sequences[idx]


def test_vehicle_detection_module_assigns_stable_track_id(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TRACK_ENABLED", "true")
    monkeypatch.setenv("VEHICLE_TRACKER_MODE", "iou")
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    detector = _FakeDetector(
        [
            [VehicleDetection(bbox=(100, 120, 220, 130), confidence=0.91, class_name="car", source="yolo")],
            [VehicleDetection(bbox=(106, 123, 218, 128), confidence=0.89, class_name="car", source="yolo")],
        ]
    )
    module = VehicleDetectionModule(
        detector=detector,
        min_vehicle_conf=0.30,
        plate_only_fallback_enabled=True,
    )

    first = module.detect_and_select_primary(frame, camera_id=3, ocr_available=True)
    second = module.detect_and_select_primary(frame, camera_id=3, ocr_available=True)

    assert first.primary is not None
    assert second.primary is not None
    assert first.primary_track_id is not None
    assert second.primary_track_id is not None
    assert first.primary_track_id == second.primary_track_id
    assert first.tracker_backend == "iou"
    assert second.tracker_backend == "iou"


def test_vehicle_detection_module_assigns_stable_track_id_sort(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TRACK_ENABLED", "true")
    monkeypatch.setenv("VEHICLE_TRACKER_MODE", "sort")
    monkeypatch.setenv("VEHICLE_SORT_MATCH_IOU", "0.10")
    monkeypatch.setenv("VEHICLE_SORT_MATCH_DISTANCE_RATIO", "2.0")
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    detector = _FakeDetector(
        [
            [VehicleDetection(bbox=(320, 210, 180, 96), confidence=0.93, class_name="car", source="yolo")],
            [VehicleDetection(bbox=(335, 218, 182, 98), confidence=0.91, class_name="car", source="yolo")],
        ]
    )
    module = VehicleDetectionModule(
        detector=detector,
        min_vehicle_conf=0.30,
        plate_only_fallback_enabled=True,
    )

    first = module.detect_and_select_primary(frame, camera_id=11, ocr_available=True)
    second = module.detect_and_select_primary(frame, camera_id=11, ocr_available=True)

    assert first.primary_track_id is not None
    assert second.primary_track_id is not None
    assert first.primary_track_id == second.primary_track_id
    assert first.tracker_backend == "sort"
    assert second.tracker_backend == "sort"


def test_vehicle_detection_module_invalid_tracker_mode_falls_back_to_iou(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TRACK_ENABLED", "true")
    monkeypatch.setenv("VEHICLE_TRACKER_MODE", "unsupported-mode")
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    detector = _FakeDetector(
        [[VehicleDetection(bbox=(90, 90, 120, 90), confidence=0.88, class_name="car", source="yolo")]]
    )
    module = VehicleDetectionModule(
        detector=detector,
        min_vehicle_conf=0.30,
        plate_only_fallback_enabled=True,
    )

    result = module.detect_and_select_primary(frame, camera_id=4, ocr_available=True)

    assert result.primary_track_id is not None
    assert result.tracker_backend == "iou"


def test_vehicle_detection_module_fallback_when_no_vehicle(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TRACK_ENABLED", "true")
    monkeypatch.setenv("VEHICLE_TRACKER_MODE", "iou")
    frame = np.zeros((640, 640, 3), dtype=np.uint8)
    detector = _FakeDetector([[]])
    module = VehicleDetectionModule(
        detector=detector,
        min_vehicle_conf=0.30,
        plate_only_fallback_enabled=True,
    )

    result = module.detect_and_select_primary(frame, camera_id=1, ocr_available=True)

    assert result.plate_only_fallback_attempted is True
    assert result.plate_only_fallback_used is True
    assert result.primary is not None
    assert result.primary.class_name == "unknown"
    assert result.primary_track_id is None
    assert result.tracker_backend == "iou"


def test_vehicle_attributes_module_infers_profile_and_identity() -> None:
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")

    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(0, 0, 240, 100),
    )
    assert profile["vehicle_type"] == "passenger"
    assert profile["body_style"] in {"sedan_coupe", "suv_crossover", "compact_hatch"}
    assert profile["model_hint"] in {"sedan_like", "crossover_like", "compact_like"}
    assert profile["dominant_color"] == "unknown"
    assert profile["registry_match"] is False
    assert profile["make"] is None
    assert isinstance(profile["confidence"], float)

    identity = module.resolve_plate_identity(
        plate_reliable=True,
        plate_type="civil",
        normalized_text="316 تونس 1975",
        raw_text="316 تونس 1975",
        plate_code="316",
        plate_city=None,
        plate_sequence="1975",
        plate_display=None,
    )
    assert identity.plate_city == "Tunis"
    assert identity.plate_number is not None


def test_vehicle_attributes_module_estimates_color_from_frame() -> None:
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")
    frame = np.zeros((120, 220, 3), dtype=np.uint8)
    frame[:, :] = (255, 0, 0)  # BGR blue
    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(10, 10, 180, 80),
        frame_bgr=frame,
    )
    assert profile["dominant_color"] in {"blue", "cyan"}
    assert float(profile["confidence"]) > 0.0


def test_vehicle_attributes_module_registry_enrichment(monkeypatch) -> None:
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")
    monkeypatch.setattr(
        module,
        "_find_registry_profile",
        lambda **_: {
            "marque": "Renault",
            "modele": "Clio",
            "couleur": "white",
            "categorie": "civil",
        },
    )
    frame = np.zeros((100, 180, 3), dtype=np.uint8)
    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(0, 0, 160, 70),
        frame_bgr=frame,
        plate_number="316 TUNIS 1975",
    )
    assert profile["registry_match"] is True
    assert profile["make"] == "Renault"
    assert profile["brand"] == "Renault"
    assert profile["model"] == "Clio"
    assert profile["registry_category"] == "civil"


def test_vehicle_taxonomy_alias_normalization() -> None:
    assert normalize_vehicle_color("gris") == "gray"
    assert normalize_vehicle_color("ARGENT") == "silver"
    assert normalize_vehicle_color("bleu") == "blue"
    assert normalize_vehicle_brand("vw") == "Volkswagen"
    assert normalize_vehicle_brand("sangyoung") == "SsangYong"
    assert vehicle_brand_key("Mercedes-Benz") == "mercedesbenz"
    assert vehicle_brand_logo_path("Toyota") == "/assets/vehicle-brands/toyota.svg"
    assert normalize_vehicle_category("militaire") == "military"
    assert normalize_vehicle_category("civile") == "civil"
    assert normalize_vehicle_body_style("SUV") == "suv_crossover"
    assert normalize_vehicle_body_style("berline") == "sedan_coupe"
    assert normalize_vehicle_body_style("pickup") == "truck"


def test_vehicle_attributes_module_normalizes_registry_aliases(monkeypatch) -> None:
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")
    monkeypatch.setattr(
        module,
        "_find_registry_profile",
        lambda **_: {
            "marque": "vw",
            "modele": " Golf 7 ",
            "couleur": "gris",
            "categorie": "militaire",
        },
    )
    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(0, 0, 160, 70),
        frame_bgr=np.zeros((100, 180, 3), dtype=np.uint8),
        plate_number="36 207",
    )
    assert profile["registry_match"] is True
    assert profile["brand"] == "Volkswagen"
    assert profile["make"] == "Volkswagen"
    assert profile["brand_key"] == "volkswagen"
    assert profile["model"] == "Golf 7"
    assert profile["registry_color"] == "gray"
    assert profile["dominant_color"] in {"black", "gray"}
    assert profile["registry_category"] == "military"
    assert profile["logo_path"] == "/assets/vehicle-brands/volkswagen.svg"


def test_vehicle_attributes_module_onnx_brand_feature_flag(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TINY_BRAND_ONNX_ENABLE", "true")
    monkeypatch.setenv("VEHICLE_TINY_BRAND_ONNX_MIN_CONF", "0.55")
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")

    class _FakeOnnxBrand:
        available = True

        class _Out:
            brand = "Toyota"
            confidence = 0.91
            class_index = 3
            source = "onnxruntime"

        def predict(self, **_kwargs):
            return self._Out()

    monkeypatch.setattr(module, "_onnx_brand_classifier", _FakeOnnxBrand())
    monkeypatch.setattr(module, "_find_registry_profile", lambda **_: None)

    frame = np.zeros((120, 220, 3), dtype=np.uint8)
    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(10, 10, 180, 80),
        frame_bgr=frame,
        plate_number="UNKNOWN",
    )

    assert profile["registry_match"] is False
    assert profile["brand"] == "Toyota"
    assert profile["make"] == "Toyota"
    assert profile["brand_source"] == "onnxruntime"
    assert profile["source"].endswith("+onnx_brand")


def test_vehicle_attributes_module_onnx_brand_normalization(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TINY_BRAND_ONNX_ENABLE", "true")
    monkeypatch.setenv("VEHICLE_TINY_BRAND_ONNX_MIN_CONF", "0.55")
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")

    class _FakeOnnxBrand:
        available = True

        class _Out:
            brand = "sangyoung"
            confidence = 0.88
            class_index = 4
            source = "onnxruntime"

        def predict(self, **_kwargs):
            return self._Out()

    monkeypatch.setattr(module, "_onnx_brand_classifier", _FakeOnnxBrand())
    monkeypatch.setattr(module, "_find_registry_profile", lambda **_: None)

    frame = np.zeros((120, 220, 3), dtype=np.uint8)
    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(10, 10, 180, 80),
        frame_bgr=frame,
        plate_number="UNKNOWN",
    )

    assert profile["brand"] == "SsangYong"
    assert profile["make"] == "SsangYong"
    assert profile["brand_key"] == "ssangyong"
    assert profile["brand_source"] == "onnxruntime"
    assert profile["logo_path"] == "/assets/vehicle-brands/ssangyong.svg"


def test_vehicle_attributes_module_onnx_terrain_enrichment(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TINY_BRAND_ONNX_ENABLE", "true")
    monkeypatch.setenv("VEHICLE_TINY_TERRAIN_BRAND_MIN_CONF", "0.60")
    monkeypatch.setenv("VEHICLE_TINY_TERRAIN_COLOR_MIN_CONF", "0.40")
    monkeypatch.setenv("VEHICLE_TINY_TERRAIN_MODEL_MIN_CONF", "0.50")
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")

    class _FakeTerrain:
        available = True

        class _Out:
            brand = "vw"
            brand_confidence = 0.84
            color = "gris"
            color_confidence = 0.73
            model = "Golf 7"
            model_confidence = 0.66
            source = "onnxruntime"

        def predict(self, **_kwargs):
            return self._Out()

    class _DisabledBrand:
        available = False

        def predict(self, **_kwargs):
            return None

    monkeypatch.setattr(module, "_onnx_terrain_classifier", _FakeTerrain())
    monkeypatch.setattr(module, "_onnx_brand_classifier", _DisabledBrand())
    monkeypatch.setattr(module, "_find_registry_profile", lambda **_: None)

    frame = np.zeros((120, 220, 3), dtype=np.uint8)
    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(10, 10, 180, 80),
        frame_bgr=frame,
        plate_number="UNKNOWN",
    )

    assert profile["brand"] == "Volkswagen"
    assert profile["make"] == "Volkswagen"
    assert profile["model"] == "Golf 7"
    assert profile["dominant_color"] == "gray"
    assert profile["brand_confidence"] == 0.84
    assert profile["color_confidence"] == 0.73
    assert profile["model_confidence"] == 0.66
    assert profile["brand_source"] == "onnxruntime"
    assert profile["color_source"] == "onnxruntime"
    assert profile["model_source"] == "onnxruntime"
    assert profile["source"].endswith("+onnx_terrain")


def test_vehicle_attributes_module_onnx_terrain_brand_fallback_to_legacy(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TINY_BRAND_ONNX_ENABLE", "true")
    monkeypatch.setenv("VEHICLE_TINY_BRAND_ONNX_MIN_CONF", "0.55")
    monkeypatch.setenv("VEHICLE_TINY_TERRAIN_BRAND_MIN_CONF", "0.90")
    monkeypatch.setenv("VEHICLE_TINY_TERRAIN_COLOR_MIN_CONF", "0.40")
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")

    class _FakeTerrain:
        available = True

        class _Out:
            brand = "bmw"
            brand_confidence = 0.31
            color = "bleu"
            color_confidence = 0.74
            model = ""
            model_confidence = 0.0
            source = "onnxruntime"

        def predict(self, **_kwargs):
            return self._Out()

    class _FakeOnnxBrand:
        available = True

        class _Out:
            brand = "Toyota"
            confidence = 0.92
            class_index = 2
            source = "onnxruntime"

        def predict(self, **_kwargs):
            return self._Out()

    monkeypatch.setattr(module, "_onnx_terrain_classifier", _FakeTerrain())
    monkeypatch.setattr(module, "_onnx_brand_classifier", _FakeOnnxBrand())
    monkeypatch.setattr(module, "_find_registry_profile", lambda **_: None)

    frame = np.zeros((120, 220, 3), dtype=np.uint8)
    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(10, 10, 180, 80),
        frame_bgr=frame,
        plate_number="UNKNOWN",
    )

    assert profile["dominant_color"] == "blue"
    assert profile["color_confidence"] == 0.74
    assert profile["brand"] == "Toyota"
    assert profile["make"] == "Toyota"
    assert profile["brand_confidence"] == 0.92
    assert profile["brand_source"] == "onnxruntime"
    assert "+onnx_brand" in str(profile["source"])


def test_vehicle_attributes_module_registry_priority_over_onnx(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_TINY_BRAND_ONNX_ENABLE", "true")
    module = VehicleAttributesModule(db=_DummyDb(), default_civil_city="Tunis")

    class _FakeOnnxBrand:
        available = True

        class _Out:
            brand = "BMW"
            confidence = 0.96
            class_index = 1
            source = "onnxruntime"

        def predict(self, **_kwargs):
            return self._Out()

    monkeypatch.setattr(module, "_onnx_brand_classifier", _FakeOnnxBrand())
    monkeypatch.setattr(
        module,
        "_find_registry_profile",
        lambda **_: {
            "marque": "Renault",
            "modele": "Clio",
            "couleur": "white",
            "categorie": "civil",
        },
    )

    frame = np.zeros((100, 180, 3), dtype=np.uint8)
    profile = module.infer_vehicle_profile(
        class_name="car",
        bbox=(0, 0, 160, 70),
        frame_bgr=frame,
        plate_number="316 TUNIS 1975",
    )

    assert profile["registry_match"] is True
    assert profile["brand"] == "Renault"
    assert profile["make"] == "Renault"
    assert profile["brand_source"] == "registry"
    assert profile["source"].endswith("+registry")


def test_vehicle_consistency_module_all_aligned_high_score() -> None:
    module = VehicleConsistencyModule()
    result = module.compute(
        camera_id=1,
        track_id=11,
        plate_number="36 207",
        plate_type="military",
        plate_reliable=True,
        plate_confidence=0.95,
        vehicle_detected=True,
        vehicle_class="car",
        matched_registry=True,
        ocr_stabilization={"applied": True, "stability_ratio": 0.96},
        vehicle_profile={
            "brand": "Renault",
            "brand_source": "registry",
            "dominant_color": "white",
            "registry_color": "white",
            "registry_category": "military",
            "registry_match": True,
        },
        plate_only_fallback_used=False,
    )
    assert float(result["consistency_score"]) >= 0.85
    assert result["confidence_level"] == "high"
    assert result["flags"] == []


def test_vehicle_consistency_module_flags_low_ocr_and_mismatch() -> None:
    module = VehicleConsistencyModule()
    result = module.compute(
        camera_id=1,
        track_id=5,
        plate_number="12 999",
        plate_type="civil",
        plate_reliable=False,
        plate_confidence=0.15,
        vehicle_detected=True,
        vehicle_class="car",
        matched_registry=True,
        ocr_stabilization={"applied": False, "stability_ratio": 0.10},
        vehicle_profile={
            "brand": "Toyota",
            "brand_source": "onnxruntime",
            "dominant_color": "red",
            "registry_color": "white",
            "registry_category": "military",
            "registry_match": True,
        },
        plate_only_fallback_used=False,
    )
    flags = set(result["flags"])
    assert "low_ocr_stability" in flags
    assert "brand_mismatch_registry" in flags
    assert "color_mismatch_registry" in flags
    assert "plate_type_mismatch" in flags
    assert float(result["consistency_score"]) < 0.6


def test_vehicle_consistency_module_no_signal_no_crash() -> None:
    module = VehicleConsistencyModule()
    result = module.compute(
        camera_id=2,
        track_id=None,
        plate_number=None,
        plate_type="unknown",
        plate_reliable=False,
        plate_confidence=0.0,
        vehicle_detected=False,
        vehicle_class="unknown",
        matched_registry=False,
        ocr_stabilization=None,
        vehicle_profile=None,
        plate_only_fallback_used=True,
    )
    assert "consistency_score" in result
    assert "reasons" in result
    assert "flags" in result
    assert float(result["consistency_score"]) <= 0.5
    assert "tracker_unstable" in set(result["flags"])


def test_vehicle_consistency_module_smoothing_multi_frame() -> None:
    module = VehicleConsistencyModule()
    low = module.compute(
        camera_id=9,
        track_id=77,
        plate_number="11111",
        plate_type="civil",
        plate_reliable=True,
        plate_confidence=0.50,
        vehicle_detected=True,
        vehicle_class="car",
        matched_registry=False,
        ocr_stabilization={"applied": False, "stability_ratio": 0.20},
        vehicle_profile={"dominant_color": "gray"},
        plate_only_fallback_used=False,
    )
    high = module.compute(
        camera_id=9,
        track_id=77,
        plate_number="11111",
        plate_type="civil",
        plate_reliable=True,
        plate_confidence=0.95,
        vehicle_detected=True,
        vehicle_class="car",
        matched_registry=False,
        ocr_stabilization={"applied": True, "stability_ratio": 0.95},
        vehicle_profile={"dominant_color": "gray"},
        plate_only_fallback_used=False,
    )
    assert float(high["consistency_score"]) > float(low["consistency_score"])
    assert float(high["consistency_score"]) < 1.0
    assert int((high.get("debug") or {}).get("samples", 0)) >= 2


def test_vehicle_anomaly_module_simple_high_score_no_anomaly() -> None:
    module = VehicleAnomalyModule()
    out = module.evaluate(
        consistency={
            "consistency_score": 0.92,
            "flags": [],
        }
    )
    assert out["detected"] is False
    assert out["level"] == "none"
    assert out["reason"] == "none"


def test_vehicle_anomaly_module_low_score_detected() -> None:
    module = VehicleAnomalyModule()
    out = module.evaluate(
        consistency={
            "consistency_score": 0.41,
            "flags": ["low_ocr_stability"],
        }
    )
    assert out["detected"] is True
    assert out["level"] in {"high", "critical"}
    assert "score_below_high" in set(out["rules_triggered"]) or "score_below_critical" in set(out["rules_triggered"])


def test_vehicle_anomaly_module_mismatch_rules_triggered() -> None:
    module = VehicleAnomalyModule()
    out = module.evaluate(
        consistency={
            "consistency_score": 0.74,
            "flags": ["brand_mismatch_registry", "color_mismatch_registry"],
        }
    )
    assert out["detected"] is True
    assert out["level"] in {"medium", "high", "critical"}
    assert "multi_registry_mismatch" in set(out["rules_triggered"])


def test_vehicle_alert_engine_cooldown_and_suppression(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_ALERT_ENGINE_ENABLE", "true")
    monkeypatch.setenv("VEHICLE_ALERT_COOLDOWN_SEC", "30")
    module = VehicleAlertEngineModule()
    t0 = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
    anomaly = {"detected": True, "level": "medium", "reason": "medium_low_consistency", "anomaly_score": 0.62}
    consistency = {"consistency_score": 0.48, "flags": ["low_ocr_stability"]}

    first = module.evaluate(
        camera_id=1,
        track_id=10,
        plate_number="36 207",
        anomaly=anomaly,
        consistency=consistency,
        reference_time=t0,
    )
    second = module.evaluate(
        camera_id=1,
        track_id=10,
        plate_number="36 207",
        anomaly=anomaly,
        consistency=consistency,
        reference_time=t0 + timedelta(seconds=4),
    )

    assert first["should_emit"] is True
    assert second["should_emit"] is False
    assert second["suppressed"] is True
    assert second["suppression_reason"] == "cooldown"


def test_vehicle_alert_engine_anti_spam(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_ALERT_ENGINE_ENABLE", "true")
    monkeypatch.setenv("VEHICLE_ALERT_COOLDOWN_SEC", "0")
    monkeypatch.setenv("VEHICLE_ALERT_SPAM_WINDOW_SEC", "120")
    monkeypatch.setenv("VEHICLE_ALERT_SPAM_MAX_EMITS", "2")
    monkeypatch.setenv("VEHICLE_ALERT_ESCALATE_HIGH_COUNT", "99")
    monkeypatch.setenv("VEHICLE_ALERT_ESCALATE_CRITICAL_COUNT", "199")
    module = VehicleAlertEngineModule()
    anomaly = {"detected": True, "level": "medium", "reason": "medium_low_consistency", "anomaly_score": 0.55}
    consistency = {"consistency_score": 0.52, "flags": ["low_ocr_stability"]}
    base = datetime(2026, 3, 5, 12, 10, 0, tzinfo=timezone.utc)

    out1 = module.evaluate(
        camera_id=2,
        track_id=20,
        plate_number="11 111",
        anomaly=anomaly,
        consistency=consistency,
        reference_time=base,
    )
    out2 = module.evaluate(
        camera_id=2,
        track_id=20,
        plate_number="11 111",
        anomaly=anomaly,
        consistency=consistency,
        reference_time=base + timedelta(seconds=2),
    )
    out3 = module.evaluate(
        camera_id=2,
        track_id=20,
        plate_number="11 111",
        anomaly=anomaly,
        consistency=consistency,
        reference_time=base + timedelta(seconds=3),
    )

    assert out1["should_emit"] is True
    assert out2["should_emit"] is True
    assert out3["should_emit"] is False
    assert out3["suppression_reason"] == "anti_spam"


def test_vehicle_alert_engine_frequency_escalation(monkeypatch) -> None:
    monkeypatch.setenv("VEHICLE_ALERT_ENGINE_ENABLE", "true")
    monkeypatch.setenv("VEHICLE_ALERT_COOLDOWN_SEC", "0")
    monkeypatch.setenv("VEHICLE_ALERT_SPAM_MAX_EMITS", "20")
    monkeypatch.setenv("VEHICLE_ALERT_ESCALATE_HIGH_COUNT", "3")
    monkeypatch.setenv("VEHICLE_ALERT_ESCALATE_CRITICAL_COUNT", "5")
    module = VehicleAlertEngineModule()
    anomaly = {"detected": True, "level": "medium", "reason": "medium_low_consistency", "anomaly_score": 0.64}
    consistency = {"consistency_score": 0.44, "flags": ["low_ocr_stability", "tracker_unstable"]}
    base = datetime(2026, 3, 5, 12, 30, 0, tzinfo=timezone.utc)

    levels = []
    for i in range(5):
        out = module.evaluate(
            camera_id=3,
            track_id=30,
            plate_number="22 222",
            anomaly=anomaly,
            consistency=consistency,
            reference_time=base + timedelta(seconds=i),
        )
        levels.append(str(out["level"]))

    assert levels[0] in {"medium", "high"}
    assert levels[2] in {"high", "critical"}
    assert levels[4] == "critical"


def test_vehicle_live_monitoring_snapshot_from_rows() -> None:
    ref = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
    events = [
        {
            "id": 1,
            "timestamp": ref - timedelta(minutes=8),
            "confidence": 0.80,
            "consistency_score": 0.78,
            "anomaly_detected": False,
            "is_priority": False,
        },
        {
            "id": 2,
            "timestamp": ref - timedelta(minutes=2),
            "confidence": 0.74,
            "consistency_score": 0.43,
            "anomaly_detected": True,
            "is_priority": True,
        },
        {
            "id": 3,
            "timestamp": ref - timedelta(minutes=1),
            "confidence": 0.92,
            "consistency_score": 0.91,
            "anomaly_detected": False,
            "is_priority": False,
        },
    ]
    alerts = [
        {
            "id": 11,
            "timestamp": ref - timedelta(minutes=2, seconds=10),
            "type": "anomaly_consistency",
            "severity_level": "high",
            "resolution_status": "open",
            "message": "High anomaly frequency",
            "plate_number": "36 207",
            "camera_id": 1,
            "event_id": 2,
        },
        {
            "id": 12,
            "timestamp": ref - timedelta(minutes=1, seconds=20),
            "type": "anomaly_consistency",
            "severity_level": "critical",
            "resolution_status": "open",
            "message": "Critical anomaly",
            "plate_number": "11 111",
            "camera_id": 1,
            "event_id": 3,
        },
        {
            "id": 13,
            "timestamp": ref - timedelta(minutes=7),
            "type": "unknown_plate",
            "severity_level": "medium",
            "resolution_status": "resolved",
            "message": "Unknown plate",
            "plate_number": "22 222",
            "camera_id": 1,
            "event_id": 1,
        },
    ]

    snap = VehicleLiveMonitoringModule.build_snapshot_from_rows(
        event_rows=events,
        alert_rows=alerts,
        camera_id=1,
        window_minutes=10,
        bucket_seconds=60,
        recent_limit=2,
        reference_time=ref,
    )

    stats = snap["stats"]
    assert int(stats["events_total"]) == 3
    assert int(stats["anomalies_total"]) == 1
    assert int(stats["priority_events_total"]) == 1
    assert int(stats["alerts_total"]) == 3
    assert int(stats["alerts_open"]) == 2
    assert int(stats["alerts_resolved"]) == 1
    assert int(stats["alerts_by_severity"]["critical"]) == 1
    assert int(stats["alerts_by_severity"]["high"]) == 1
    assert len(snap["recent_alerts"]) == 2
    assert str(snap["recent_alerts"][0]["severity_level"]) in {"critical", "high"}
    assert len(snap["timeline"]) >= 1


def test_vehicle_live_monitoring_snapshot_handles_empty_rows() -> None:
    ref = datetime(2026, 3, 5, 12, 30, 0, tzinfo=timezone.utc)
    snap = VehicleLiveMonitoringModule.build_snapshot_from_rows(
        event_rows=[],
        alert_rows=[],
        camera_id=None,
        window_minutes=20,
        bucket_seconds=30,
        recent_limit=5,
        reference_time=ref,
    )

    stats = snap["stats"]
    assert int(stats["events_total"]) == 0
    assert int(stats["alerts_total"]) == 0
    assert float(stats["avg_consistency_score"]) == 0.0
    assert float(stats["anomaly_rate"]) == 0.0
    assert snap["recent_alerts"] == []
    assert len(snap["timeline"]) >= 1


def test_detect_payload_adapter_from_modular_result() -> None:
    modular = {
        "success": True,
        "vehicle_detected": True,
        "vehicle_class": "car",
        "vehicle_confidence": 0.91,
        "vehicle_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
        "plate_number": "36 207",
        "plate_type": "military",
        "dominant_color": "white",
        "plate_confidence": 0.84,
        "plate_bbox": {"x": 24, "y": 33, "w": 40, "h": 16},
        "track_id": 12,
        "latency_ms": 123.4,
        "pipeline": {"detector": "yolo", "tracker": "sort", "ocr": "easyocr", "classifier": "hybrid"},
        "vehicle_profile": {
            "vehicle_type": "passenger",
            "logo_path": "/assets/vehicle-brands/renault.svg",
        },
        "consistency": {"consistency_score": 0.88, "confidence_level": "high", "flags": []},
        "anomaly": {"detected": False, "level": "none", "reason": "none", "flags": []},
        "anomaly_alert": {"should_emit": False, "suppressed": False, "severity_level": "low"},
    }
    payload = _build_detect_payload_from_modular_result(
        modular=modular,
        confidence=0.25,
        iou_threshold=0.45,
        max_detections=100,
        vehicle_only=True,
        plate_only_fallback=True,
    )

    assert payload["success"] is True
    assert payload["backend"] == "vehicle_modular_pipeline"
    assert payload["vehicles_count"] == 1
    assert payload["detections_count"] == 1
    assert payload["vehicles"][0]["bbox"] == [10, 20, 110, 70]
    assert payload["vehicles"][0]["track_id"] == 12
    assert payload["vehicles"][0]["logo_path"] == "/assets/vehicle-brands/renault.svg"
    assert float(payload["vehicles"][0]["consistency"]["consistency_score"]) == 0.88
    assert float(payload["consistency"]["consistency_score"]) == 0.88
    assert bool(payload["anomaly"]["detected"]) is False
    assert bool(payload["vehicles"][0]["anomaly"]["detected"]) is False
    assert bool(payload["anomaly_alert"]["should_emit"]) is False
    assert bool(payload["vehicles"][0]["anomaly_alert"]["should_emit"]) is False
    assert payload["pipeline"]["tracker"] == "sort"


def test_ocr_stabilizer_applies_on_stable_weighted_votes() -> None:
    stabilizer = OcrStabilizerModule(
        window_sec=2.0,
        max_samples=6,
        decay_sec=0.9,
        min_samples=2,
        min_stability=0.55,
        min_margin=0.05,
    )

    first = stabilizer.update(
        camera_id=1,
        track_id=10,
        compact_text="36207",
        normalized_text="36 207",
        raw_text="36 207",
        confidence=0.72,
    )
    second = stabilizer.update(
        camera_id=1,
        track_id=10,
        compact_text="36207",
        normalized_text="36 207",
        raw_text="36 207",
        confidence=0.84,
    )

    assert first is not None
    assert second is not None
    assert bool(second.get("applied")) is True
    assert second.get("winner_compact") == "36207"
    assert float(second.get("stability_ratio", 0.0)) >= 0.55


def test_ocr_stabilizer_rejects_unstable_conflicting_votes() -> None:
    stabilizer = OcrStabilizerModule(
        window_sec=2.0,
        max_samples=6,
        decay_sec=1.0,
        min_samples=2,
        min_stability=0.80,
        min_margin=0.40,
    )

    stabilizer.update(
        camera_id=2,
        track_id=5,
        compact_text="36207",
        normalized_text="36 207",
        raw_text="36 207",
        confidence=0.65,
    )
    out = stabilizer.update(
        camera_id=2,
        track_id=5,
        compact_text="36287",
        normalized_text="36 287",
        raw_text="36 287",
        confidence=0.64,
    )

    assert out is not None
    assert bool(out.get("applied")) is False


def test_ocr_stabilizer_isolated_by_track_id() -> None:
    stabilizer = OcrStabilizerModule(
        window_sec=2.0,
        max_samples=6,
        decay_sec=1.0,
        min_samples=2,
        min_stability=0.55,
        min_margin=0.05,
    )

    stabilizer.update(
        camera_id=7,
        track_id=1,
        compact_text="11111",
        normalized_text="11 111",
        raw_text="11 111",
        confidence=0.8,
    )
    stabilizer.update(
        camera_id=7,
        track_id=2,
        compact_text="22222",
        normalized_text="22 222",
        raw_text="22 222",
        confidence=0.8,
    )
    a2 = stabilizer.update(
        camera_id=7,
        track_id=1,
        compact_text="11111",
        normalized_text="11 111",
        raw_text="11 111",
        confidence=0.78,
    )
    b2 = stabilizer.update(
        camera_id=7,
        track_id=2,
        compact_text="22222",
        normalized_text="22 222",
        raw_text="22 222",
        confidence=0.79,
    )

    assert a2 is not None and b2 is not None
    assert bool(a2.get("applied")) is True
    assert bool(b2.get("applied")) is True
    assert a2.get("winner_compact") == "11111"
    assert b2.get("winner_compact") == "22222"
    assert a2.get("stream_key") != b2.get("stream_key")
