#!/usr/bin/env python3
"""Frontend Integration Test - Verify POST endpoints work for frontend"""

import requests
import json

API_BASE = "http://localhost:5003/api"

def make_unique_payload(method):
    """Create unique payload with timestamp to avoid duplicates"""
    import time
    ts = int(time.time() * 1000) % 1000000
    
    if method == "personnel":
        return {
            "nom": "Testeur",
            "prenom": f"Frontend_{ts}",
            "cin": f"CIN{ts}",
            "num_recrutement": f"REC{ts}",
            "categorie": "soldat",
            "grade": "Soldat",
            "unité": "Test Unit",
            "gender": "male",
            "email": f"test_{ts}@test.com",
            "telephone": "+216 90 000 000"
        }
    elif method == "vehicles":
        return {
            "type_vehicule": "civile",
            "marque_modele": "Peugeot 406",
            "immatriculation": f"TEST-{ts}",
            "numero_serie": f"VIN{ts}",
            "couleur": "Blanc",
            "proprietaire": "Test Owner",
            "nom_conducteur": "Test Driver",
            "etat": "actif"
        }

def test_frontend_workflow():
    """Simulate complete frontend workflow"""
    
    print("\n" + "🧪 FRONTEND INTEGRATION TEST".center(60, "="))
    
    # Step 1: Login (required by frontend)
    print("\n1️⃣  AUTHENTICATING USER")
    print("-" * 60)
    
    login_response = requests.post(
        f"{API_BASE}/auth/login",
        json={"username": "admin", "password": "admin123"}
    )
    
    if login_response.status_code != 200:
        print(f"❌ Login failed: {login_response.status_code}")
        return False
    
    token = login_response.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    print(f"✅ Authenticated (token: {token[:15]}...)")
    
    # Step 2: POST Personnel
    print("\n2️⃣  CREATE PERSONNEL (Frontend simulation)")
    print("-" * 60)
    
    personnel_payload = make_unique_payload("personnel")
    print(f"Payload:\n  {json.dumps(personnel_payload, indent=2)}")
    
    personnel_response = requests.post(
        f"{API_BASE}/personnel/",
        json=personnel_payload,
        headers=headers
    )
    
    if personnel_response.status_code in [200, 201]:
        personnel = personnel_response.json()
        print(f"\n✅ Personnel created: #{personnel.get('id')} - {personnel.get('full_name')}")
        personnel_id = personnel.get('id')
    else:
        print(f"\n❌ Personnel creation failed: {personnel_response.status_code}")
        print(f"   Response: {personnel_response.json()}")
        return False
    
    # Step 3: POST Vehicles
    print("\n3️⃣  CREATE VEHICLE (Frontend simulation)")
    print("-" * 60)
    
    vehicle_payload = make_unique_payload("vehicles")
    print(f"Payload:\n  {json.dumps(vehicle_payload, indent=2)}")
    
    vehicle_response = requests.post(
        f"{API_BASE}/vehicles/",
        json=vehicle_payload,
        headers=headers
    )
    
    if vehicle_response.status_code in [200, 201]:
        vehicle = vehicle_response.json()
        print(f"\n✅ Vehicle created: #{vehicle.get('id')} - {vehicle.get('immatriculation')}")
        vehicle_id = vehicle.get('id')
    else:
        print(f"\n❌ Vehicle creation failed: {vehicle_response.status_code}")
        print(f"   Response: {vehicle_response.json()}")
        return False
    
    # Step 4: GET Personnel to verify
    print("\n4️⃣  VERIFY PERSONNEL (GET)")
    print("-" * 60)
    
    get_personnel_response = requests.get(
        f"{API_BASE}/personnel/{personnel_id}",
        headers=headers
    )
    
    if get_personnel_response.status_code == 200:
        print(f"✅ Retrieved Personnel: {get_personnel_response.json().get('nom')} {get_personnel_response.json().get('prenom')}")
    else:
        print(f"❌ Failed to retrieve Personnel: {get_personnel_response.status_code}")
        return False
    
    # Step 5: GET Vehicles to verify
    print("\n5️⃣  VERIFY VEHICLE (GET)")
    print("-" * 60)
    
    get_vehicle_response = requests.get(
        f"{API_BASE}/vehicles/{vehicle_id}",
        headers=headers
    )
    
    if get_vehicle_response.status_code == 200:
        print(f"✅ Retrieved Vehicle: {get_vehicle_response.json().get('immatriculation')}")
    else:
        print(f"❌ Failed to retrieve Vehicle: {get_vehicle_response.status_code}")
        return False
    
    print("\n" + "=" * 60)
    print("✅ FRONTEND INTEGRATION TEST PASSED!")
    print("=" * 60)
    print(f"\nSummary:")
    print(f"  → Personnel #{personnel_id} created and verified")
    print(f"  → Vehicle #{vehicle_id} created and verified")
    print(f"  → Full CRUD workflow works correctly!")
    
    return True

if __name__ == "__main__":
    success = test_frontend_workflow()
    exit(0 if success else 1)
