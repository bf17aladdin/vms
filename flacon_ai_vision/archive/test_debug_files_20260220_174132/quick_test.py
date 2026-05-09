#!/usr/bin/env python3
"""Quick test - verify POST endpoints work"""
import requests

API = "http://localhost:5003/api"
r = requests.post(f"{API}/auth/login", json={"username": "admin", "password": "admin123"})
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# Test POST Personnel
p = requests.post(f"{API}/personnel/", json={
    "nom": "Test", "prenom": "User", "cin": "CIN999", "num_recrutement": "REC999", 
    "categorie": "soldat", "grade": "Soldat"
}, headers=h)
print(f"POST /api/personnel: {p.status_code} {'✅' if p.status_code in [201, 200] else '❌'}")

# Test POST Vehicle
v = requests.post(f"{API}/vehicles/", json={
    "type_vehicule": "civile", "marque_modele": "Toyota",
    "immatriculation": f"VH-TEST-999", "proprietaire": "Owner"
}, headers=h)
print(f"POST /api/vehicles:  {v.status_code} {'✅' if v.status_code in [201, 200] else '❌'}")

if p.status_code in [201, 200] and v.status_code in [201, 200]:
    print("\n✅ BOTH ENDPOINTS WORKING - Frontend can save data!")
