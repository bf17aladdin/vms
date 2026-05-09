import requests

BASE='http://127.0.0.1:5003'
# login
r = requests.post(BASE + '/api/auth/login', json={'username':'admin','password':'admin123'})
print('login', r.status_code, r.text)
if r.status_code!=200:
    raise SystemExit('cannot login')

token = r.json().get('access_token') or r.json().get('token') or r.json().get('accessToken') or r.json().get('detail')
if not token:
    # try common key
    token = r.json().get('token')

headers={'Authorization': f'Bearer {token}'}

payload={'matricule':'TEST-123','marque':'Test','modele':'T1','categorie':'militaire','statut':'actif'}

for path in ['/api/vehicles', '/api/vehicles/']:
    print('\nPOST to', path)
    resp = requests.post(BASE + path, json=payload, headers=headers)
    print('->', resp.status_code, resp.text)
