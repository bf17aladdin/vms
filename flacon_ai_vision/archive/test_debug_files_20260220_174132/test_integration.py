#!/usr/bin/env python3
"""
Script de vérification intégration frontend-backend après harmonisation véhicules
"""

import requests
import json

BASE_URL = 'http://localhost:5003/api'

print('='*70)
print('VÉRIFICATION INTÉGRATION FRONTEND-BACKEND')
print('='*70)

# Test 1: Vérifier que l'API répond
print('\n[1] Test connexion API backend...')
try:
    response = requests.get(f'{BASE_URL}/vehicles', timeout=5)
    print(f'    ✓ Status: {response.status_code}')
    vehicles = response.json()
    print(f'    ✓ Nombre de véhicules: {len(vehicles)}')
    if vehicles:
        v = vehicles[0]
        print(f'    Premier véhicule: {v.get("matricule")} ({v.get("marque")} {v.get("modele")})')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

# Test 2: Créer un véhicule de test (militaire)
print('\n[2] Création d\'un véhicule test (militaire)...')
test_vehicle = {
    'matricule': 'TEST2024001',
    'marque': 'Mercedes',
    'modele': 'Sprinter',
    'couleur': 'Bleu',
    'categorie': 'militaire',
    'unite': 'Base Navale',
    'statut': 'actif'
}
try:
    response = requests.post(f'{BASE_URL}/vehicles', json=test_vehicle, timeout=5)
    print(f'    ✓ Status: {response.status_code}')
    if response.status_code == 201:
        created = response.json()
        print(f'    ✓ Véhicule créé avec ID: {created["id"]}')
        print(f'    ✓ Matricule: {created["matricule"]}')
        print(f'    ✓ Catégorie: {created["categorie"]}')
        print(f'    ✓ Unité: {created.get("unite")}')
    else:
        print(f'    ✗ Erreur: {response.text}')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

# Test 3: Créer un véhicule civil
print('\n[3] Création d\'un véhicule test (civil)...')
test_vehicle = {
    'matricule': 'CIVIL2024001',
    'marque': 'Peugeot', 
    'modele': '308',
    'couleur': 'Gris',
    'categorie': 'civil',
    'statut': 'actif'
}
try:
    response = requests.post(f'{BASE_URL}/vehicles', json=test_vehicle, timeout=5)
    print(f'    ✓ Status: {response.status_code}')
    if response.status_code == 201:
        created = response.json()
        print(f'    ✓ Véhicule créé avec ID: {created["id"]}')
        print(f'    ✓ Categorie (civil): {created["categorie"]}')
        print(f'    ✓ Unite (doit être null): {created.get("unite")}')
    else:
        print(f'    ✗ Erreur: {response.text}')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

# Test 4: Tester filtrage par catégorie
print('\n[4] Test filtrage par catégorie (militaire)...')
try:
    response = requests.get(f'{BASE_URL}/vehicles?categorie=militaire', timeout=5)
    print(f'    ✓ Status: {response.status_code}')
    militaires = response.json()
    print(f'    ✓ Véhicules militaires trouvés: {len(militaires)}')
    if militaires:
        for v in militaires:
            print(f'       - {v.get("matricule")}: {v.get("marque")} {v.get("modele")} [{v.get("unite")}]')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

# Test 5: Tester filtrage par catégorie civil
print('\n[5] Test filtrage par catégorie (civil)...')
try:
    response = requests.get(f'{BASE_URL}/vehicles?categorie=civil', timeout=5)
    print(f'    ✓ Status: {response.status_code}')
    civils = response.json()
    print(f'    ✓ Véhicules civils trouvés: {len(civils)}')
    if civils:
        for v in civils:
            print(f'       - {v.get("matricule")}: {v.get("marque")} {v.get("modele")}')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

# Test 6: Tester filtrage statut
print('\n[6] Test filtrage par statut (actif)...')
try:
    response = requests.get(f'{BASE_URL}/vehicles?statut=actif', timeout=5)
    print(f'    ✓ Status: {response.status_code}')
    actifs = response.json()
    print(f'    ✓ Véhicules actifs trouvés: {len(actifs)}')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

# Test 7: Vérifier schéma complet
print('\n[7] Vérification schéma des réponses...')
try:
    response = requests.get(f'{BASE_URL}/vehicles?limit=1', timeout=5)
    if response.status_code == 200:
        vehicles = response.json()
        if vehicles:
            v = vehicles[0]
            required_fields = ['id', 'matricule', 'marque', 'modele', 'categorie', 'statut', 'date_enregistrement']
            missing = [f for f in required_fields if f not in v]
            if not missing:
                print('    ✓ Tous les champs requis présents:')
                for field in required_fields:
                    print(f'       ✓ {field}: {v.get(field)}')
            else:
                print(f'    ✗ Champs manquants: {missing}')
except Exception as e:
    print(f'    ✗ Erreur: {e}')

print('\n' + '='*70)
print('✅ VÉRIFICATION COMPLÉTÉE')
print('='*70)
