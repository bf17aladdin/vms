from __future__ import annotations

from vms.backend.main import app

REQUIRED_ENDPOINTS = {
    "face": {"/api/face/recognize": {"post"}},
    "vehicle": {"/api/vehicle/recognize/camera/{camera_id}": {"post"}},
    "zone": {"/api/zones": {"get"}, "/api/zones/create": {"post"}},
    "security": {"/api/system/health/full": {"get"}, "/api/alerts/": {"get"}},
    "admin": {"/api/admin/health": {"get"}, "/api/admin/users/{user_id}/roles": {"post"}},
    "reporting": {"/api/reporting/health": {"get"}, "/api/reporting/generate": {"post"}},
}


def test_openapi_contains_required_module_endpoints() -> None:
    schema = app.openapi()
    paths = schema.get("paths", {})

    for module_name, endpoint_map in REQUIRED_ENDPOINTS.items():
        for path, required_methods in endpoint_map.items():
            assert path in paths, f"Missing endpoint path for module '{module_name}': {path}"
            methods = {m.lower() for m in paths[path].keys()}
            missing_methods = sorted(required_methods - methods)
            assert not missing_methods, (
                f"Missing endpoint methods for module '{module_name}' path '{path}': {missing_methods}. "
                f"Found: {sorted(methods)}"
            )
