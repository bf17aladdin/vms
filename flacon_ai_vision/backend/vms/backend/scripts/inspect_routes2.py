import sys
from pathlib import Path

# Ajouter la racine du workspace au path pour permettre l'import du package `vms`
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from vms.backend.main import app


def list_routes():
    routes = []
    for r in app.router.routes:
        methods = None
        try:
            methods = r.methods
        except Exception:
            methods = None
        routes.append((r.path, methods, getattr(r, 'name', None)))
    # sort
    for path, methods, name in sorted(routes):
        print(f"PATH: {path} | METHODS: {methods} | NAME: {name}")


if __name__ == '__main__':
    list_routes()
