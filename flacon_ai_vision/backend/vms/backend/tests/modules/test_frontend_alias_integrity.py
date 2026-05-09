from __future__ import annotations

from pathlib import Path


def test_frontend_duplicate_filenames_are_limited_to_known_aliases() -> None:
    repo_root = Path(__file__).resolve().parents[5]
    frontend_src = repo_root / "frontend" / "src"

    duplicates: dict[str, list[Path]] = {}
    for path in frontend_src.rglob("*"):
        if not path.is_file():
            continue
        duplicates.setdefault(path.name, []).append(path)

    duplicate_names = {
        name: sorted(paths)
        for name, paths in duplicates.items()
        if len(paths) > 1 and name != "index.ts"
    }

    assert set(duplicate_names) == {
        "ButtonGroup.tsx",
        "Dashboard.tsx",
        "DataTable.tsx",
        "MainLayout.tsx",
        "ZonesPage.tsx",
    }, f"Unexpected duplicate frontend filenames: {sorted(duplicate_names)}"


def test_frontend_alias_files_delegate_to_canonical_implementations() -> None:
    repo_root = Path(__file__).resolve().parents[5]

    expected_markers = {
        repo_root / "frontend" / "src" / "pages" / "ZonesPage.tsx": [
            "export { ZonesPage } from './zones/ZonesPage'",
            "export { default } from './zones/ZonesPage'",
        ],
        repo_root / "frontend" / "src" / "components" / "Dashboard.tsx": [
            "export { Dashboard } from '../pages/Dashboard'",
            "export { default } from '../pages/Dashboard'",
        ],
        repo_root / "frontend" / "src" / "layouts" / "MainLayout.tsx": [
            "export { MainLayout } from '../components/layout/MainLayout'",
            "export { default } from '../components/layout/MainLayout'",
        ],
        repo_root / "frontend" / "src" / "components" / "ButtonGroup" / "ButtonGroup.tsx": [
            "import { ButtonGroup as BaseButtonGroup } from '../ButtonGroup'",
            "<BaseButtonGroup buttons={normalizedButtons} />",
        ],
        repo_root / "frontend" / "src" / "components" / "DataTable" / "DataTable.tsx": [
            "import { DataTable as BaseDataTable } from '../DataTable'",
            "<BaseDataTable",
        ],
    }

    for path, markers in expected_markers.items():
        content = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker in content, f"Missing alias marker {marker!r} in {path}"
