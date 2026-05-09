#!/usr/bin/env python3
"""
Script de test des endpoints véhicules après harmonisation du schéma
Teste: POST /api/vehicles (créer véhicule) et GET /api/vehicles (lister)
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:5003/api"

def test_vehicles_endpoints():
    """Test les endpoints véhicules avec le nouveau schéma"""
    
    print("=" * 80)
    print("TEST ENDPOINTS VÉHICULES - NOUVEAU SCHÉMA")
    print("=" * 80)
    
    # Données de test pour civil et militaire
    test_vehicles = [
        {
            "matricule": "MB2024TEST001",
            "marque": "Mercedes",
            "modele": "G-Class",
            "couleur": "Vert militaire",
            "categorie": "militaire",
            "unite": "Base Navale Monastir",
            "statut": "actif"
        },
        {
            "matricule": "TOY2024TEST001",
            "marque": "Toyota",
            "modele": "Corolla",
            "couleur": "Noir",
            "categorie": "civil",
            "statut": "actif"
        }
    ]
    
    # Test 1: Créer des véhicules
    print("\n1. TEST CRÉATION VÉHICULES (POST /vehicles)")
    print("-" * 80)
    
    created_vehicles = []
    for vehicle in test_vehicles:
        try:
            print(f"\n   📝 Création: {vehicle['matricule']} ({vehicle['categorie']})")
            response = requests.post(
                f"{BASE_URL}/vehicles",
                json=vehicle,
                timeout=10
            )
            
            if response.status_code == 201:
                data = response.json()
                created_vehicles.append(data)
                print(f"      ✓ Status: 201 - Créé avec succès")
                print(f"      ✓ ID: {data.get('id')}")
                print(f"      ✓ Matricule: {data.get('matricule')}")
                print(f"      ✓ Catégorie: {data.get('categorie')}")
                if data.get('unite'):
                    print(f"      ✓ Unité: {data.get('unite')}")
            else:
                print(f"      ✗ Status: {response.status_code}")
                print(f"      Erreur: {response.text}")
        
        except requests.exceptions.ConnectionError:
            print(f"      ✗ Erreur: Impossible de se connecter à {BASE_URL}")
            print(f"      🔴 Assurez-vous que le serveur backend est en cours d'exécution")
            return False
        except Exception as e:
            print(f"      ✗ Erreur: {e}")
    
    # Test 2: Lister les véhicules
    print("\n\n2. TEST LISTAGE VÉHICULES (GET /vehicles)")
    print("-" * 80)
    
    try:
        # Récupérer tous les véhicules
        print("\n   📋 Récupération de tous les véhicules...")
        response = requests.get(f"{BASE_URL}/vehicles", timeout=10)
        
        if response.status_code == 200:
            vehicles = response.json()
            print(f"      ✓ Status: 200")
            print(f"      ✓ Nombre total: {len(vehicles)} véhicules")
            
            if vehicles:
                print("\n   Véhicules trouvés:")
                for v in vehicles[-2:]:  # Affiche les 2 derniers (nos test)
                    print(f"\n      ID: {v.get('id')}")
                    print(f"      Matricule: {v.get('matricule')}")
                    print(f"      Marque: {v.get('marque')} {v.get('modele')}")
                    print(f"      Couleur: {v.get('couleur')}")
                    print(f"      Catégorie: {v.get('categorie')}")
                    if v.get('unite'):
                        print(f"      Unité: {v.get('unite')}")
                    print(f"      Statut: {v.get('statut')}")
                    print(f"      Date: {v.get('date_enregistrement')}")
        else:
            print(f"      ✗ Status: {response.status_code}")
            print(f"      Erreur: {response.text}")
    
    except Exception as e:
        print(f"      ✗ Erreur: {e}")
    
    # Test 3: Filtrer par catégorie
    print("\n\n3. TEST FILTRAGE VÉHICULES")
    print("-" * 80)
    
    try:
        # Filtrer militaires
        print("\n   🎖️ Filtrage véhicules MILITAIRES (categorie=militaire)...")
        response = requests.get(f"{BASE_URL}/vehicles?categorie=militaire", timeout=10)
        
        if response.status_code == 200:
            vehicles = response.json()
            print(f"      ✓ Status: 200")
            print(f"      ✓ Trouvés: {len(vehicles)} véhicule(s)")
            for v in vehicles:
                print(f"         - {v.get('matricule')} ({v.get('marque')} {v.get('modele')})")
        
        # Filtrer civiles
        print("\n   🚗 Filtrage véhicules CIVILS (categorie=civil)...")
        response = requests.get(f"{BASE_URL}/vehicles?categorie=civil", timeout=10)
        
        if response.status_code == 200:
            vehicles = response.json()
            print(f"      ✓ Status: 200")
            print(f"      ✓ Trouvés: {len(vehicles)} véhicule(s)")
            for v in vehicles:
                print(f"         - {v.get('matricule')} ({v.get('marque')} {v.get('modele')})")
        
        # Filtrer actifs
        print("\n   ✅ Filtrage véhicules ACTIFS (statut=actif)...")
        response = requests.get(f"{BASE_URL}/vehicles?statut=actif", timeout=10)
        
        if response.status_code == 200:
            vehicles = response.json()
            print(f"      ✓ Status: 200")
            print(f"      ✓ Trouvés: {len(vehicles)} véhicule(s)")
    
    except Exception as e:
        print(f"      ✗ Erreur: {e}")
    
    # Test 4: Récupérer un véhicule spécifique
    if created_vehicles:
        print("\n\n4. TEST RÉCUPÉRATION VÉHICULE SPÉCIFIQUE (GET /vehicles/{id})")
        print("-" * 80)
        
        vehicle_id = created_vehicles[0].get('id')
        print(f"\n   🔍 Récupération véhicule ID: {vehicle_id}...")
        
        try:
            response = requests.get(f"{BASE_URL}/vehicles/{vehicle_id}", timeout=10)
            
            if response.status_code == 200:
                v = response.json()
                print(f"      ✓ Status: 200")
                print(f"      ✓ Matricule: {v.get('matricule')}")
                print(f"      ✓ Marque/Modèle: {v.get('marque')} {v.get('modele')}")
                print(f"      ✓ Catégorie: {v.get('categorie')}")
                print(f"      ✓ Statut: {v.get('statut')}")
            else:
                print(f"      ✗ Status: {response.status_code}")
        
        except Exception as e:
            print(f"      ✗ Erreur: {e}")
    
    print("\n" + "=" * 80)
    print("✓ TESTS TERMINÉS")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = test_vehicles_endpoints()
    exit(0 if success else 1)
