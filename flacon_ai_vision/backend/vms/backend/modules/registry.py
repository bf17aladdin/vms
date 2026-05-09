from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, Tuple


@dataclass(frozen=True)
class ModuleContract:
    name: str
    backend_routes: Tuple[str, ...]
    backend_services: Tuple[str, ...]
    frontend_pages: Tuple[str, ...]
    frontend_components: Tuple[str, ...]
    tests: Tuple[str, ...]


MODULE_CONTRACTS: Dict[str, ModuleContract] = {
    "face": ModuleContract(
        name="face",
        backend_routes=(
            "backend/vms/backend/routers/face.py",
            "backend/vms/backend/routers/facial.py",
        ),
        backend_services=(
            "backend/vms/backend/services/face_ai/face_pipeline.py",
            "backend/vms/backend/services/face_ai/face_detector.py",
            "backend/vms/backend/services/face_ai/face_embedder.py",
            "backend/vms/backend/services/face_ai/face_matcher.py",
            "backend/vms/backend/services/face_ai/face_align.py",
        ),
        frontend_pages=(
            "frontend/src/pages/FacialRecognitionPage.tsx",
        ),
        frontend_components=(
            "frontend/src/components/FacialRecognitionWebcam.tsx",
        ),
        tests=(
            "backend/vms/backend/tests/modules/test_face_module_contract.py",
        ),
    ),
    "vehicle": ModuleContract(
        name="vehicle",
        backend_routes=(
            "backend/vms/backend/routers/vehicle_recognition.py",
            "backend/vms/backend/routers/vehicle_registry.py",
            "backend/vms/backend/routers/vehicle_detection.py",
            "backend/vms/backend/routers/vehicle_entries.py",
            "backend/vms/backend/routers/vehicles.py",
        ),
        backend_services=(
            "backend/vms/backend/services/vehicle_ai/vehicle_pipeline.py",
            "backend/vms/backend/services/vehicle_ai/vehicle_detector.py",
            "backend/vms/backend/services/vehicle_ai/plate_reader.py",
            "backend/vms/backend/services/vehicle_ai/plate_type_classifier.py",
            "backend/vms/backend/services/vehicle_ai/access_control.py",
        ),
        frontend_pages=(
            "frontend/src/pages/VehiclesPage.tsx",
            "frontend/src/pages/VehicleRegistryPage.tsx",
            "frontend/src/pages/VehicleMultiCamMonitorPage.tsx",
        ),
        frontend_components=(),
        tests=(
            "backend/vms/backend/tests/modules/test_vehicle_module_contract.py",
        ),
    ),
    "zone": ModuleContract(
        name="zone",
        backend_routes=(
            "backend/vms/backend/routers/zones.py",
            "backend/vms/backend/routers/security_config.py",
            "backend/vms/backend/routers/sites.py",
        ),
        backend_services=(
            "backend/vms/backend/services/zone_service.py",
            "backend/vms/backend/services/virtual_zones.py",
        ),
        frontend_pages=(
            "frontend/src/pages/zones/ZonesPage.tsx",
            "frontend/src/pages/SecurityConfigPage.tsx",
        ),
        frontend_components=(),
        tests=(
            "backend/vms/backend/tests/modules/test_zone_module_contract.py",
        ),
    ),
    "security": ModuleContract(
        name="security",
        backend_routes=(
            "backend/vms/backend/routers/alerts.py",
            "backend/vms/backend/routers/events.py",
            "backend/vms/backend/routers/realtime_router.py",
            "backend/vms/backend/routers/system_health.py",
        ),
        backend_services=(
            "backend/vms/backend/services/alert_service.py",
            "backend/vms/backend/services/event_service.py",
            "backend/vms/backend/services/system_health_service.py",
            "backend/vms/backend/services/logging_service.py",
        ),
        frontend_pages=(
            "frontend/src/pages/SecurityCenterPage.tsx",
            "frontend/src/pages/SecurityRealtimePage.tsx",
            "frontend/src/pages/AlertsPage.tsx",
            "frontend/src/pages/EventsPage.tsx",
        ),
        frontend_components=(),
        tests=(
            "backend/vms/backend/tests/modules/test_security_module_contract.py",
        ),
    ),
    "admin": ModuleContract(
        name="admin",
        backend_routes=(
            "backend/vms/backend/routers/admin_router.py",
            "backend/vms/backend/routers/users.py",
            "backend/vms/backend/routers/auth.py",
        ),
        backend_services=(
            "backend/vms/backend/services/camera_service.py",
            "backend/vms/backend/services/personnel_service.py",
            "backend/vms/backend/services/logging_service.py",
        ),
        frontend_pages=(
            "frontend/src/pages/UsersPage.tsx",
        ),
        frontend_components=(
            "frontend/src/components/AdminPanel.tsx",
        ),
        tests=(
            "backend/vms/backend/tests/modules/test_admin_module_contract.py",
        ),
    ),
    "reporting": ModuleContract(
        name="reporting",
        backend_routes=(
            "backend/vms/backend/routers/reporting_router.py",
        ),
        backend_services=(
            "backend/vms/backend/services/reporting_service.py",
        ),
        frontend_pages=(
            "frontend/src/pages/ReportingPage.tsx",
        ),
        frontend_components=(
            "frontend/src/components/ReportingDashboard.tsx",
        ),
        tests=(
            "backend/vms/backend/tests/modules/test_reporting_module_contract.py",
        ),
    ),
}


def iter_contracts() -> Iterator[ModuleContract]:
    return iter(MODULE_CONTRACTS.values())


def get_contract(name: str) -> ModuleContract:
    return MODULE_CONTRACTS[name]
