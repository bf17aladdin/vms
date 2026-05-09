#!/usr/bin/env python
"""Vérification complète de la fonction verify_password et de l'endpoint login"""

import requests
import json
from .core.database import SessionLocal
from .core.security import verify_password
from . import models, crud

print("=" * 80)
print("ÉTAPE 2 : VÉRIFICATION DE verify_password ET DE L'ENDPOINT LOGIN")
print("=" * 80)
print()

db = SessionLocal()

try:
    # ============================================================================
    # PARTIE 1: VÉRIFIER LA FONCTION verify_password
    # ============================================================================
    print("PARTIE 1: VÉRIFICATION DE LA FONCTION verify_password")
    print("-" * 80)
    print()
    
    # Récupérer l'utilisateur admin
    admin = db.query(models.User).filter(models.User.username == "admin").first()
    
    if not admin:
        print("✗ Utilisateur admin NON trouvé")
        exit(1)
    
    print(f"✓ Utilisateur admin trouvé")
    print(f"  Username: {admin.username}")
    print(f"  Hash: {admin.hashed_password[:50]}...")
    print()
    
    # Test 1: verify_password directement
    print("Test 1: Appel direct à verify_password()")
    pwd = "admin123"
    result = verify_password(pwd, admin.hashed_password)
    print(f"  verify_password('{pwd}', hash) = {result}")
    print(f"  ✓ RÉSULTAT: {'CORRECT' if result else 'INCORRECT'}")
    print()
    
    # Test 2: Vérifier via CRUD authenticate_user
    print("Test 2: Utilisation de CRUD authenticate_user()")
    user = crud.authenticate_user(db, "admin", "admin123")
    if user:
        print(f"  ✓ RÉSULTAT: Utilisateur authentifié (ID: {user.id})")
    else:
        print(f"  ✗ RÉSULTAT: Authentification échouée")
    print()
    
    # ============================================================================
    # PARTIE 2: VÉRIFIER L'ENDPOINT LOGIN
    # ============================================================================
    print()
    print("PARTIE 2: VÉRIFICATION DE L'ENDPOINT /api/auth/login")
    print("-" * 80)
    print()
    
    url = "http://127.0.0.1:5003/api/auth/login"
    payload = {
        "username": "admin",
        "password": "admin123"
    }
    headers = {"Content-Type": "application/json"}
    
    print(f"Envoi requête HTTP POST à {url}")
    print(f"Payload: {json.dumps(payload)}")
    print()
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        
        print(f"Status Code: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        print()
        
        if response.status_code == 200:
            data = response.json()
            print("✓ RÉPONSE 200 OK")
            print()
            print("Contenu de la réponse:")
            print(f"  access_token: {data.get('access_token', 'N/A')[:50]}...")
            print(f"  token_type: {data.get('token_type', 'N/A')}")
            print(f"  user.username: {data.get('user', {}).get('username', 'N/A')}")
            print(f"  user.is_admin: {data.get('user', {}).get('is_admin', 'N/A')}")
            print(f"  user.is_active: {data.get('user', {}).get('is_active', 'N/A')}")
            print()
            print("✓ ENDPOINT LOGIN FONCTIONNE CORRECTEMENT")
            
        elif response.status_code == 401:
            print("✗ ERREUR 401: Credentials invalides")
            print(f"  Détail: {response.json().get('detail', 'N/A')}")
            
        elif response.status_code == 403:
            print("✗ ERREUR 403: Utilisateur désactivé")
            print(f"  Détail: {response.json().get('detail', 'N/A')}")
            
        else:
            print(f"✗ ERREUR {response.status_code}")
            print(f"  Réponse: {response.text}")
            
    except requests.exceptions.ConnectionError:
        print("✗ ERREUR: Impossible de se connecter au serveur")
        print("  Assurez-vous que le serveur FastAPI est en cours d'exécution sur http://127.0.0.1:5003/")
        
    except Exception as e:
        print(f"✗ ERREUR: {str(e)}")
    
    print()
    print("=" * 80)
    print("VÉRIFICATION COMPLÉTÉE")
    print("=" * 80)
    
except Exception as e:
    print(f"✗ ERREUR: {str(e)}")
    import traceback
    traceback.print_exc()
    
finally:
    db.close()
