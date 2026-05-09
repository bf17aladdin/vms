#!/usr/bin/env python3
import requests
import json

# Test login endpoint
url = 'http://localhost:5003/api/auth/login'
data = {'username': 'admin', 'password': 'admin123'}
headers = {'Content-Type': 'application/json'}

print("Testing login endpoint...")
try:
    response = requests.post(url, json=data, headers=headers, timeout=5)
    print(f'Status: {response.status_code}')
    print(f'Response: {json.dumps(response.json(), indent=2)}')
except Exception as e:
    print(f'Error: {str(e)}')

# Test cameras endpoint without token
print("\n\nTesting cameras endpoint (no token)...")
url2 = 'http://localhost:5003/api/cameras'
try:
    response = requests.get(url2, timeout=5)
    print(f'Status: {response.status_code}')
    print(f'Response: {json.dumps(response.json(), indent=2)}')
except Exception as e:
    print(f'Error: {str(e)}')
