#!/usr/bin/env python3
"""
Test des endpoints POST avec authentification
"""

import requests
import json

BASE_URL = 'http://localhost:5003/api'

print('='*70)
print('TEST ENDPOINTS POST AVEC AUTHENTIFICATION')
print('='*70)

# Step 1: Obtenir un token
print('\n[1] Connexion pour obtenir un token...')
login_data = {
    "username": "admin",
    "password": "admin123"
}
try:
    response = requests.post(f'{BASE_URL}/auth/login', json=login_data, timeout=5)
    print(f'    ✓ Status: {response.status_code}')
    
    if response.status_code == 200:
        token = response.json().get('access_token')
        print(f'    ✓ Token obtenu: {token[:20]}...')
    else:
        print(f'    ✗ Erreur login: {response.text}')
        token = None
except Exception as e:
    print(f'    ✗ Erreur: {e}')
    token = None

if not token:
    print('\n❌ Impossible de continuer sans token!')
    exit(1)

# Headers avec authentification
headers = {
    'Authorization': f'Bearer {token}',
    'Content-Type': 'application/json'
}

# Test 2: Créer un véhicule (militaire)
print('\n[2] Création d\'un véhicule test (militaire) avec auth...')
test_vehicle = {
    'matricule': 'AUTH2024001',
    'marque': 'Mercedes',
    'modele': 'Sprinter',
    'couleur': 'Bleu',
    'categorie': 'militaire',
    'unite': 'Base Navale',
    'statut': 'actif'
}
try:
    response = requests.post(
        f'{BASE_URL}/vehicles',
        json=test_vehicle,
        headers=headers,
        timeout=5
    )
    print(f'    ✓ Status: {response.status_code}')
    if response.status_code == 201:
        created = response.json()
        print(f'    ✅ Véhicule créé!')
        print(f'       ID: {created["id"]}')
        print(f'       Matricule: {created["matricule"]}')
        print(f'       Catégorie: {created["categorie"]}')
        print(f'       Unité: {created.get("unite")}')
    else:
        print(f'       ✗ Status: {response.status_code}')
        print(f'       Erreur: {response.text}')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

# Test 3: Créer un personnel
print('\n[3] Création d\'un personnel test avec auth...')
test_personnel = {
    'nom': 'Dupont',
    'prenom': 'Jean',
    'cin': 'AUTH001001',
    'num_recrutement': 'AUTH2024001',
    'categorie': 'soldat',
    'grade': 'Soldat',
    'gender': 'male',
}
try:
    response = requests.post(
        f'{BASE_URL}/personnel',
        json=test_personnel,
        headers=headers,
        timeout=5
    )
    print(f'    ✓ Status: {response.status_code}')
    if response.status_code == 201:
        created = response.json()
        print(f'    ✅ Personnel créé!')
        print(f'       ID: {created["id"]}')
        print(f'       Nom: {created["nom"]} {created["prenom"]}')
        print(f'       Grade: {created["grade"]}')
    else:
        print(f'       ✗ Status: {response.status_code}')
        print(f'       Erreur: {response.text}')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

# Test 4: Lister les véhicules
print('\n[4] Listage des véhicules...')
try:
    response = requests.get(
        f'{BASE_URL}/vehicles',
        headers=headers,
        timeout=5
    )
    print(f'    ✓ Status: {response.status_code}')
    vehicles = response.json()
    print(f'    ✓ Total véhicules: {len(vehicles)}')
    if vehicles:
        for v in vehicles[-2:]:
            print(f'       - {v.get("matricule")}: {v.get("marque")} {v.get("modele")} ({v.get("categorie")})')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

print('\n' + '='*70)
print('✅ TEST COMPLÉTÉ')
print('='*70)
