#!/usr/bin/env python
"""Quick authentication test"""

import requests
import json

BASE_URL = "http://127.0.0.1:5003"

# Test different credentials
test_credentials = [
    ("admin", "admin123"),
    ("admin", "password"),
    ("admin", "admin"),
]

print("\n[TEST] Authentication Attempts")
print("=" * 60)

for username, password in test_credentials:
    try:
        response = requests.post(
            BASE_URL + "/api/auth/login",
            json={"username": username, "password": password},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token") or data.get("token")
            print(f"✓ {username}:{password:<15} → SUCCESS")
            if token:
                print(f"  Token: {token[:40]}...")
        else:
            print(f"✗ {username}:{password:<15} → {response.status_code} - {response.json().get('detail', 'Unknown error')}")
    except Exception as e:
        print(f"✗ {username}:{password:<15} → ERROR: {e}")
