#!/usr/bin/env python3
"""
Script de test de l'authentification frontend
"""
import requests
import json

print("=" * 60)
print("TESTING AUTHENTICATION FLOW")
print("=" * 60)

# Step 1: Login
print("\n1️⃣  LOGIN")
login_url = 'http://localhost:5003/api/auth/login'
login_data = {'username': 'admin', 'password': 'admin123'}

try:
    response = requests.post(login_url, json=login_data, timeout=5)
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        login_response = response.json()
        token = login_response.get('access_token')
        print(f"   ✅ Token obtained: {token[:50]}...")
    else:
        print(f"   ❌ Login failed: {response.text}")
        exit(1)
except Exception as e:
    print(f"   ❌ Error: {e}")
    exit(1)

# Step 2: Test cameras without token
print("\n2️⃣  CAMERAS WITHOUT TOKEN")
cameras_url = 'http://localhost:5003/api/cameras'
try:
    response = requests.get(cameras_url, timeout=5)
    print(f"   Status: {response.status_code}")
    if response.status_code != 200:
        print(f"   ⚠️  Expected 401, got {response.status_code}")
        print(f"   Response: {response.json()}")
except Exception as e:
    print(f"   Error: {e}")

# Step 3: Test cameras WITH token
print("\n3️⃣  CAMERAS WITH TOKEN")
headers = {'Authorization': f'Bearer {token}'}
try:
    response = requests.get(cameras_url, headers=headers, timeout=5)
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        camera_count = len(data.get('cameras', []))
        print(f"   ✅ Got {camera_count} cameras")
    else:
        print(f"   ❌ Failed: {response.json()}")
except Exception as e:
    print(f"   Error: {e}")

# Step 4: Check frontend SPA
print("\n4️⃣  FRONTEND SPA")
try:
    response = requests.get('http://localhost:5003/', timeout=5)
    print(f"   Status: {response.status_code}")
    if response.status_code == 200:
        if '<html' in response.text:
            print(f"   ✅ Frontend HTML served (size: {len(response.text)} bytes)")
        else:
            print(f"   ⚠️  Response is not HTML")
    else:
        print(f"   ❌ Frontend not found")
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "=" * 60)
