"""Vehicle AI recognition pipeline package."""

from .vehicle_attributes_module import VehicleAttributesModule
from .vehicle_detection_module import VehicleDetectionModule
from .tracker_backends import IouTrackerBackend, SortTrackerBackend, create_tracker_backend
from .tiny_onnx_brand_classifier import TinyOnnxBrandClassifier
from .vehicle_profile_classifier import LightVehicleProfileClassifier
from .vehicle_consistency_module import VehicleConsistencyModule
from .vehicle_anomaly_module import VehicleAnomalyModule
from .vehicle_alert_engine_module import VehicleAlertEngineModule
from .vehicle_live_monitoring_module import VehicleLiveMonitoringModule
from .vehicle_search_contract import (
    UNKNOWN_ATTRIBUTE_FILTER,
    normalize_vehicle_body_style_filter,
    normalize_vehicle_color_filter,
    normalize_vehicle_type_filter,
)
from .vehicle_taxonomy import (
    get_supported_vehicle_body_styles,
    get_supported_vehicle_colors,
    get_supported_vehicle_types,
    normalize_vehicle_brand,
    normalize_vehicle_body_style,
    normalize_vehicle_category,
    normalize_vehicle_color,
    normalize_vehicle_model,
    normalize_vehicle_type,
    vehicle_brand_logo_path,
    vehicle_brand_key,
)
from .plate_scanner_module import PlateScannerModule
from .ocr_stabilizer_module import OcrStabilizerModule
from .vehicle_pipeline import VehicleRecognitionPipeline

__all__ = [
    "VehicleRecognitionPipeline",
    "VehicleDetectionModule",
    "create_tracker_backend",
    "IouTrackerBackend",
    "SortTrackerBackend",
    "TinyOnnxBrandClassifier",
    "LightVehicleProfileClassifier",
    "VehicleConsistencyModule",
    "VehicleAnomalyModule",
    "VehicleAlertEngineModule",
    "VehicleLiveMonitoringModule",
    "UNKNOWN_ATTRIBUTE_FILTER",
    "normalize_vehicle_color_filter",
    "normalize_vehicle_body_style_filter",
    "normalize_vehicle_type_filter",
    "normalize_vehicle_color",
    "normalize_vehicle_brand",
    "normalize_vehicle_body_style",
    "vehicle_brand_key",
    "vehicle_brand_logo_path",
    "normalize_vehicle_category",
    "normalize_vehicle_model",
    "normalize_vehicle_type",
    "get_supported_vehicle_colors",
    "get_supported_vehicle_body_styles",
    "get_supported_vehicle_types",
    "PlateScannerModule",
    "OcrStabilizerModule",
    "VehicleAttributesModule",
]
