#!/usr/bin/env python3
import os
import re
import sys
import json
import requests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ROUTERS_DIR = os.path.join(os.path.dirname(__file__), 'routers')
OPENAPI_URL = 'http://127.0.0.1:5003/openapi.json'

files = [f for f in os.listdir(ROUTERS_DIR) if f.endswith('.py') and f != '__init__.py']
modules = [os.path.splitext(f)[0] for f in files]

print('Found router modules:', modules)

try:
    r = requests.get(OPENAPI_URL, timeout=5)
    r.raise_for_status()
    openapi = r.json()
except Exception as e:
    print('ERROR fetching openapi.json:', e)
    sys.exit(2)

paths = list(openapi.get('paths', {}).keys())
all_tags = {t.get('name') for t in openapi.get('tags', [])}

results = []
for mod in modules:
    path_prefix = None
    tag_name = None
    file_path = os.path.join(ROUTERS_DIR, mod + '.py')
    with open(file_path, 'r', encoding='utf-8') as fh:
        content = fh.read()
        # try find APIRouter(... prefix="..." ...)
        m = re.search(r"APIRouter\(.*?prefix\s*=\s*['\"]([^'\"]+)['\"]", content, re.S)
        if m:
            path_prefix = m.group(1)
        t = re.search(r"APIRouter\(.*?tags\s*=\s*\[([^\]]+)\]", content, re.S)
        if t:
            # extract first tag string
            tag_match = re.search(r"['\"]([^'\"]+)['\"]", t.group(1))
            if tag_match:
                tag_name = tag_match.group(1)

    included = False
    reason = []
    if path_prefix:
        for p in paths:
            if p.startswith(path_prefix):
                included = True
                reason.append(f'path_match ({path_prefix})')
                break
    if not included and tag_name:
        if tag_name in all_tags:
            included = True
            reason.append(f'tag_present ({tag_name})')
        else:
            # check operations tags in paths
            for p, ops in openapi.get('paths', {}).items():
                for method, op in ops.items():
                    if isinstance(op, dict) and tag_name in op.get('tags', []):
                        included = True
                        reason.append(f'operation_tag ({tag_name})')
                        break
                if included:
                    break

    results.append((mod, bool(included), path_prefix, tag_name, ';'.join(reason)))

print('\nSummary:')
missing = []
for mod, inc, pref, tag, reason in results:
    status = 'OK' if inc else 'MISSING'
    print(f'- {mod}: {status} | prefix={pref} | tag={tag} | reason={reason}')
    if not inc:
        missing.append(mod)

print('\nTotal routers:', len(results))
print('Missing in OpenAPI docs:', len(missing))
if missing:
    print('\nMissing modules:')
    for m in missing:
        print('-', m)

if missing:
    sys.exit(1)
else:
    sys.exit(0)
