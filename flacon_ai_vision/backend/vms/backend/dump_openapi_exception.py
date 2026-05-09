#!/usr/bin/env python3
import sys, os, traceback
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from vms.backend.main import app
except Exception as e:
    print('ERROR importing app:', e)
    traceback.print_exc()
    raise SystemExit(1)

try:
    spec = app.openapi()
    import json
    print(json.dumps(spec)[:1000])
except Exception as e:
    print('ERROR generating openapi:', e)
    traceback.print_exc()
    raise SystemExit(2)
