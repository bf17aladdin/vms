import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from vms.backend.main import app

def inspect():
    for r in app.router.routes:
        if r.path in ('/api/vehicles', '/api/vehicles/'):
            print('PATH:', r.path, 'METHODS:', getattr(r, 'methods', None), 'NAME:', getattr(r, 'name', None))
        if r.path in ('/api/personnel', '/api/personnel/'):
            print('PATH:', r.path, 'METHODS:', getattr(r, 'methods', None), 'NAME:', getattr(r, 'name', None))

if __name__ == '__main__':
    inspect()
