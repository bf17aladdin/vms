#!/usr/bin/env python3
import requests

urls = [
    "http://127.0.0.1:5003/health",
    "http://127.0.0.1:5003/api",
    "http://127.0.0.1:5003/docs",
    "http://127.0.0.1:5003/api/auth/login",
]

for u in urls:
    try:
        if u.endswith('/api/auth/login'):
            print(u, 'SKIP_POST_TEST (requires credentials)')
            continue
        r = requests.get(u, timeout=5)
        print(u, r.status_code, r.headers.get('content-type', ''))
        print('-' * 60)
        print(r.text[:1000])
        print('\n')
    except Exception as e:
        print(u, 'ERROR ->', repr(e))
