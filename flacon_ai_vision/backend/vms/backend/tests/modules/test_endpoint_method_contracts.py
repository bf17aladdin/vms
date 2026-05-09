from __future__ import annotations

import re
from pathlib import Path

from vms.backend.modules.registry import get_contract

ROUTE_METHOD_RE = re.compile(r"@router\.(get|post|put|delete|patch)\(")

MODULE_REQUIRED_METHODS = {
    "face": {"get", "post", "delete"},
    "vehicle": {"get", "post", "put", "delete"},
    "zone": {"get", "post", "put", "delete"},
    "security": {"get", "post", "delete"},
    "admin": {"get", "post", "delete"},
    "reporting": {"get", "post", "delete"},
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _collect_route_methods(route_paths: tuple[str, ...]) -> set[str]:
    root = _repo_root()
    methods: set[str] = set()
    for rel in route_paths:
        content = (root / rel).read_text(encoding="utf-8", errors="ignore")
        methods.update(m.lower() for m in ROUTE_METHOD_RE.findall(content))
    return methods


def test_module_endpoint_method_contracts() -> None:
    for module_name, required in MODULE_REQUIRED_METHODS.items():
        contract = get_contract(module_name)
        methods = _collect_route_methods(contract.backend_routes)
        missing = sorted(required - methods)
        assert not missing, (
            f"Module '{module_name}' is missing required endpoint methods: {missing}. "
            f"Found methods: {sorted(methods)}"
        )
