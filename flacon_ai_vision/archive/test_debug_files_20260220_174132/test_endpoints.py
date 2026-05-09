#!/usr/bin/env python3
"""Script de test des endpoints créés"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:5003"
print("🧪 Testing new backend endpoints...\n")

# 1. Login
print("1️⃣  Authenticating...")
login_response = requests.post(
    f"{BASE_URL}/api/auth/login",
    json={"username": "admin", "password": "admin123"}
)

if login_response.status_code != 200:
    print(f"❌ Login failed: {login_response.status_code}")
    print(login_response.text)
    exit(1)

token = login_response.json()["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print(f"✓ Authenticated (token: {token[:20]}...)\n")

# 2. Test POST /api/personnel
print("2️⃣  Testing POST /api/personnel...")
personnel_data = {
    "nom": "Dupont",
    "prenom": "Jean",
    "cin": "AB123456",
    "num_recrutement": "REC001234",
    "categorie": "officier",
    "grade": "Capitaine",
    "unité": "Base Navale Monastir",
    "gender": "male",
    "email": "jean.dupont@example.com",
    "telephone": "+216 71 234 567",
    "authorized_hours_start": "06:00",
    "authorized_hours_end": "22:00"
}

personnel_response = requests.post(
    f"{BASE_URL}/api/personnel",
    json=personnel_data,
    headers=headers
)

if personnel_response.status_code == 201:
    personnel = personnel_response.json()
    personnel_id = personnel.get("id")
    print(f"✓ Personnel created: {personnel.get('full_name')} (ID: {personnel_id})\n")
else:
    print(f"❌ Personnel creation failed: {personnel_response.status_code}")
    print(personnel_response.text)
    print()

# 3. Test POST /api/vehicles
print("3️⃣  Testing POST /api/vehicles...")
vehicle_data = {
    "type_vehicule": "militaire",
    "marque_modele": "Toyota Land Cruiser",
    "immatriculation": "TN123ABC",
    "numero_serie": "JT2RJ16K9X0124567",
    "couleur": "kaki",
    "proprietaire": "Base Militaire Monastir",
    "nom_conducteur": "Ahmed Belkhaled",
    "etat": "actif",
    "authorized_hours_start": "06:00",
    "authorized_hours_end": "22:00"
}

vehicle_response = requests.post(
    f"{BASE_URL}/api/vehicles",
    json=vehicle_data,
    headers=headers
)

if vehicle_response.status_code == 201:
    vehicle = vehicle_response.json()
    vehicle_id = vehicle.get("id")
    print(f"✓ Vehicle created: {vehicle.get('immatriculation')} (ID: {vehicle_id})\n")
else:
    print(f"❌ Vehicle creation failed: {vehicle_response.status_code}")
    print(vehicle_response.text)
    print()

# 4. Test GET /api/personnel
print("4️⃣  Testing GET /api/personnel...")
personnel_list = requests.get(
    f"{BASE_URL}/api/personnel",
    headers=headers
)

if personnel_list.status_code == 200:
    personnel = personnel_list.json()
    print(f"✓ Personnel list retrieved: {len(personnel)} records\n")
else:
    print(f"❌ Personnel list failed: {personnel_list.status_code}\n")

# 5. Test GET /api/vehicles
print("5️⃣  Testing GET /api/vehicles...")
vehicle_list = requests.get(
    f"{BASE_URL}/api/vehicles",
    headers=headers
)

if vehicle_list.status_code == 200:
    vehicles = vehicle_list.json()
    print(f"✓ Vehicle list retrieved: {len(vehicles)} records\n")
else:
    print(f"❌ Vehicle list failed: {vehicle_list.status_code}\n")

# 6. Test PUT /api/personnel/{id}
if 'personnel_id' in locals():
    print("6️⃣  Testing PUT /api/personnel/{id}...")
    update_data = {
        "grade": "Commandant"
    }
    
    update_response = requests.put(
        f"{BASE_URL}/api/personnel/{personnel_id}",
        json=update_data,
        headers=headers
    )
    
    if update_response.status_code == 200:
        updated = update_response.json()
        print(f"✓ Personnel updated: {updated.get('full_name')} - {updated.get('grade')}\n")
    else:
        print(f"❌ Personnel update failed: {update_response.status_code}\n")

# 7. Test PUT /api/vehicles/{id}
if 'vehicle_id' in locals():
    print("7️⃣  Testing PUT /api/vehicles/{id}...")
    update_data = {
        "etat": "maintenance"
    }
    
    update_response = requests.put(
        f"{BASE_URL}/api/vehicles/{vehicle_id}",
        json=update_data,
        headers=headers
    )
    
    if update_response.status_code == 200:
        updated = update_response.json()
        print(f"✓ Vehicle updated: {updated.get('immatriculation')} - {updated.get('etat')}\n")
    else:
        print(f"❌ Vehicle update failed: {update_response.status_code}\n")

# 8. Test POST /api/vehicles/{id}/flag
if 'vehicle_id' in locals():
    print("8️⃣  Testing POST /api/vehicles/{id}/flag...")
    flag_response = requests.post(
        f"{BASE_URL}/api/vehicles/{vehicle_id}/flag?reason=Inspection%20requise",
        headers=headers
    )
    
    if flag_response.status_code == 200:
        flagged = flag_response.json()
        print(f"✓ Vehicle flagged: {flagged.get('immatriculation')} - {flagged.get('flag_reason')}\n")
    else:
        print(f"❌ Vehicle flag failed: {flag_response.status_code}\n")

print("=" * 60)
print("✅ ALL TESTS COMPLETED!")
print("=" * 60)
