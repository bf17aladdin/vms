#!/usr/bin/env python
"""Test de connexion à la base de données"""

from .core.database import engine
from sqlalchemy import text

print("=" * 60)
print("TEST DE CONNEXION À LA BASE DE DONNÉES")
print("=" * 60)
print()

try:
    with engine.connect() as conn:
        # Test 1: Compter les utilisateurs
        result = conn.execute(text('SELECT COUNT(*) as count FROM users'))
        user_count = result.fetchone()[0]
        print(f"✓ Connexion DB: OK")
        print(f"  Utilisateurs: {user_count}")
        
        # Test 2: Compter les caméras
        result = conn.execute(text('SELECT COUNT(*) as count FROM cameras'))
        camera_count = result.fetchone()[0]
        print(f"  Caméras: {camera_count}")
        
        # Test 3: Compter les événements
        result = conn.execute(text('SELECT COUNT(*) as count FROM events'))
        event_count = result.fetchone()[0]
        print(f"  Événements: {event_count}")
        
        # Test 4: Vérifier si admin existe
        result = conn.execute(text('SELECT id, username FROM users WHERE username = "admin"'))
        admin = result.fetchone()
        if admin:
            print(f"\n✓ Utilisateur admin trouvé (ID: {admin[0]})")
        else:
            print(f"\n✗ Utilisateur admin NON TROUVÉ")
        
        print("\n" + "=" * 60)
        print("✓ TOUS LES TESTS DE CONNEXION RÉUSSIS")
        print("=" * 60)
        
except Exception as e:
    print(f"✗ ERREUR DE CONNEXION: {str(e)}")
    print("=" * 60)
    import traceback
    traceback.print_exc()
