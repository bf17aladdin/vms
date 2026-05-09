#!/usr/bin/env python3
"""Debug API endpoints"""

import requests
import json

BASE_URL = "http://localhost:5003"
HEADERS = {"Content-Type": "application/json"}

# Test 1: Health check
print("=" * 60)
print("Test 1: Health Check")
try:
    resp = requests.get(f"{BASE_URL}/health", timeout=5)
    print(f"✓ GET /health: {resp.status_code}")
except Exception as e:
    print(f"✗ Error: {e}")

# Test 2: Login
print("\n" + "=" * 60)
print("Test 2: Login")
login_data = {"username": "admin", "password": "admin123"}
try:
    resp = requests.post(f"{BASE_URL}/api/auth/login", json=login_data, timeout=5)
    print(f"✓ POST /api/auth/login: {resp.status_code}")
    if resp.status_code == 200:
        token = resp.json().get("access_token")
        print(f"  Token: {token[:30]}...")
    else:
        print(f"  Response: {resp.text}")
        token = None
except Exception as e:
    print(f"✗ Error: {e}")
    token = None

if token:
    auth_headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    
    # Test 3: List Personnel
    print("\n" + "=" * 60)
    print("Test 3: GET /api/personnel (List)")
    try:
        resp = requests.get(f"{BASE_URL}/api/personnel", headers=auth_headers, timeout=5)
        print(f"✓ GET /api/personnel: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Response type: {type(data)}")
            print(f"  Count: {len(data) if isinstance(data, list) else 'N/A'}")
        elif resp.status_code != 405:
            print(f"  Response: {resp.text[:200]}")
        else:
            print(f"  Method Not Allowed (405) - This is the problem!")
    except Exception as e:
        print(f"✗ Error: {e}")

    # Test 4: Create Personnel
    print("\n" + "=" * 60)
    print("Test 4: POST /api/personnel (Create)")
    personnel_data = {
        "nom": "TestNom",
        "prenom": "TestPrenom",
        "cin": "12345678",
        "num_recrutement": "REC001",
        "categorie": "soldat",
        "grade": "Soldat 1ère classe",
        "unite": "Unité Test",
        "email": "test@example.com"
    }
    try:
        resp = requests.post(f"{BASE_URL}/api/personnel", json=personnel_data, headers=auth_headers, timeout=5)
        print(f"✓ POST /api/personnel: {resp.status_code}")
        if resp.status_code in [200, 201]:
            print(f"  Success! Response: {resp.json()}")
        else:
            print(f"  Error Response: {resp.text[:300]}")
    except Exception as e:
        print(f"✗ Error: {e}")

    # Test 5: Create Vehicle
    print("\n" + "=" * 60)
    print("Test 5: POST /api/vehicles (Create)")
    vehicle_data = {
        "type_vehicule": "militaire",
        "marque_modele": "Toyota Land Cruiser",
        "immatriculation": "TN123456",
        "proprietaire": "Armée",
        "etat": "actif"
    }
    try:
        resp = requests.post(f"{BASE_URL}/api/vehicles", json=vehicle_data, headers=auth_headers, timeout=5)
        print(f"✓ POST /api/vehicles: {resp.status_code}")
        if resp.status_code in [200, 201]:
            print(f"  Success! Response: {resp.json()}")
        else:
            print(f"  Error Response: {resp.text[:300]}")
    except Exception as e:
        print(f"✗ Error: {e}")

else:
    print("\n⚠️ Could not get token - skipping authenticated tests")

print("\n" + "=" * 60)
print("Debug Summary:")
print("- If POST returns 405, the router may not be included")
print("- Check main.py logs for router inclusion")
print("- Verify PersonnelService import works")
