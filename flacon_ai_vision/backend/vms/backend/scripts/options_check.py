import requests

for path in ['/api/vehicles', '/api/personnel']:
    url = f'http://127.0.0.1:5003{path}'
    try:
        r = requests.options(url, timeout=5)
        print(path, '->', r.status_code, r.headers.get('allow'), r.headers)
    except Exception as e:
        print(path, '-> error', e)
