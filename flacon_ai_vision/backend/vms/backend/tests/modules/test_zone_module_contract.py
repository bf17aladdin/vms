from __future__ import annotations

from pathlib import Path

from vms.backend.modules.registry import get_contract


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def test_zone_module_contract_files_exist() -> None:
    root = _repo_root()
    contract = get_contract("zone")
    expected = (
        contract.backend_routes
        + contract.backend_services
        + contract.frontend_pages
        + contract.frontend_components
        + contract.tests
    )
    missing = [rel for rel in expected if not (root / rel).exists()]
    assert not missing, f"Missing zone module files: {missing}"

