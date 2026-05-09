from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, List, Tuple


def _collect_missing(root: Path, paths: Iterable[str]) -> List[str]:
    missing: List[str] = []
    for rel in paths:
        if not (root / rel).exists():
            missing.append(rel)
    return missing


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from vms.backend.modules.registry import iter_contracts

    failures: List[Tuple[str, str, List[str]]] = []

    print("Module Structure Verification")
    print("=" * 40)

    for module in iter_contracts():
        checks = (
            ("routes", module.backend_routes),
            ("services", module.backend_services),
            ("pages", module.frontend_pages),
            ("components", module.frontend_components),
            ("tests", module.tests),
        )
        print(f"\n[{module.name}]")
        for label, paths in checks:
            missing = _collect_missing(repo_root, paths)
            if missing:
                failures.append((module.name, label, missing))
                print(f"  FAIL {label}: {len(missing)} missing")
                for rel in missing:
                    print(f"    - {rel}")
            else:
                print(f"  OK   {label}")

    print("\n" + "=" * 40)
    if failures:
        print(f"FAILED: {len(failures)} section(s) missing")
        return 1
    print("PASSED: all module contracts satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

