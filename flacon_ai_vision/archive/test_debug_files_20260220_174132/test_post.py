import requests

# Get token
login = requests.post('http://localhost:5003/api/auth/login',
    json={'username': 'admin', 'password': 'admin123'})
token = login.json()['access_token']

print('Testing POST /api/personnel with token...')
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

data = {
    'nom': 'TestUser',
    'prenom': 'Test',
    'cin': 'TEST123',
    'num_recrutement': 'REC999',
    'categorie': 'soldat',
    'grade': 'Soldat',
}

r = requests.post('http://localhost:5003/api/personnel', json=data, headers=headers)
print(f'Status: {r.status_code}')
print(f'Response: {r.text}')
