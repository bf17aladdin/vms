#!/usr/bin/env python3
"""Test POST endpoints for Personnel and Vehicles"""

import requests
import json
from datetime import datetime

API_BASE = "http://localhost:5003/api"

def test_login():
    """Login and get JWT token"""
    print("\n" + "=" * 60)
    print("1️⃣  TESTING LOGIN")
    print("=" * 60)
    
    response = requests.post(
        f"{API_BASE}/auth/login",
        json={"username": "admin", "password": "admin123"}
    )
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    
    if response.status_code == 200:
        token = response.json().get("access_token")
        print(f"✅ Login successful, token: {token[:20]}...")
        return token
    else:
        print("❌ Login failed!")
        return None

def test_post_personnel(token):
    """Test POST /api/personnel"""
    print("\n" + "=" * 60)
    print("2️⃣  TESTING POST /api/personnel")
    print("=" * 60)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "nom": "Dupont",
        "prenom": "Jean",
        "cin": "12345678",
        "num_recrutement": "REC001",
        "categorie": "soldat",
        "grade": "Soldat",
        "unité": "Unit Navale",
        "gender": "male",
        "email": "jean.dupont@navy.tn",
        "telephone": "+216 92 123 456"
    }
    
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(
        f"{API_BASE}/personnel/",
        json=payload,
        headers=headers
    )
    
    print(f"\nStatus: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 201:
        print("✅ Personnel created successfully!")
        return response.json()
    else:
        print("❌ Personnel creation failed!")
        return None

def test_post_vehicles(token):
    """Test POST /api/vehicles"""
    print("\n" + "=" * 60)
    print("3️⃣  TESTING POST /api/vehicles")
    print("=" * 60)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "type_vehicule": "militaire",
        "marque_modele": "Toyota Land Cruiser",
        "immatriculation": "TN-001-MIL-2026",
        "numero_serie": "VIN123456789",
        "couleur": "Vert Militaire",
        "proprietaire": "Base Navale Monastir",
        "nom_conducteur": "Capitaine Ahmed",
        "etat": "actif",
        "allowed_zones": ["zone_1", "zone_2"],
        "authorized_hours_start": "06:00",
        "authorized_hours_end": "22:00"
    }
    
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(
        f"{API_BASE}/vehicles/",
        json=payload,
        headers=headers
    )
    
    print(f"\nStatus: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 201:
        print("✅ Vehicle created successfully!")
        return response.json()
    else:
        print("❌ Vehicle creation failed!")
        return None

def test_get_personnel(token):
    """Test GET /api/personnel"""
    print("\n" + "=" * 60)
    print("4️⃣  TESTING GET /api/personnel (Verification)")
    print("=" * 60)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{API_BASE}/personnel/",
        headers=headers
    )
    
    print(f"Status: {response.status_code}")
    data = response.json()
    
    if isinstance(data, list):
        print(f"✅ Retrieved {len(data)} personnel records")
        if data:
            print(f"Latest: {data[-1].get('nom')} {data[-1].get('prenom')}")
    else:
        print(f"Response: {json.dumps(data, indent=2)}")

def test_get_vehicles(token):
    """Test GET /api/vehicles"""
    print("\n" + "=" * 60)
    print("5️⃣  TESTING GET /api/vehicles (Verification)")
    print("=" * 60)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{API_BASE}/vehicles/",
        headers=headers
    )
    
    print(f"Status: {response.status_code}")
    data = response.json()
    
    if isinstance(data, list):
        print(f"✅ Retrieved {len(data)} vehicle records")
        if data:
            print(f"Latest: {data[-1].get('immatriculation')} - {data[-1].get('marque_modele')}")
    else:
        print(f"Response: {json.dumps(data, indent=2)}")

if __name__ == "__main__":
    print("\n" + "🔬 BACKEND POST ENDPOINTS TEST SUITE" + "\n")
    
    # Step 1: Login
    token = test_login()
    
    if not token:
        print("\n❌ Cannot proceed without token!")
        exit(1)
    
    # Step 2: Test Personnel
    personnel = test_post_personnel(token)
    
    # Step 3: Test Vehicles
    vehicle = test_post_vehicles(token)
    
    # Step 4: Verify Personnel
    test_get_personnel(token)
    
    # Step 5: Verify Vehicles
    test_get_vehicles(token)
    
    print("\n" + "=" * 60)
    print("✅ TEST SUITE COMPLETE")
    print("=" * 60 + "\n")
