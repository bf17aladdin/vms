#!/usr/bin/env python
"""Vérifier le hash du mot de passe dans la base de données"""

from .core.database import SessionLocal
from .core.security import verify_password
from . import models

print("=" * 70)
print("VÉRIFICATION DU HASH DU MOT DE PASSE ADMIN")
print("=" * 70)
print()

db = SessionLocal()

try:
    # Récupérer l'utilisateur admin
    admin = db.query(models.User).filter(models.User.username == "admin").first()
    
    if not admin:
        print("✗ Utilisateur admin NON trouvé en BD")
    else:
        print(f"✓ Utilisateur trouvé: {admin.username} (ID: {admin.id})")
        print(f"  Email: {admin.email}")
        print(f"  Is Admin: {admin.is_admin}")
        print(f"  Is Active: {admin.is_active}")
        print()
        
        # Afficher le hash stocké
        print("Hash stocké en BD:")
        print(f"  {admin.hashed_password}")
        print()
        
        # Tester la vérification du mot de passe
        password_to_test = "admin123"
        result = verify_password(password_to_test, admin.hashed_password)
        
        print(f"Test verify_password('{password_to_test}', hash):")
        print(f"  Résultat: {result}")
        print()
        
        if result:
            print("✓ Le mot de passe 'admin123' est CORRECT")
        else:
            print("✗ Le mot de passe 'admin123' est INCORRECT")
            print("\nTesting other common passwords...")
            
            for pwd in ["admin", "password", "123456", "admin123456"]:
                result = verify_password(pwd, admin.hashed_password)
                print(f"  {pwd}: {result}")
        
        print()
        print("=" * 70)
        
except Exception as e:
    print(f"✗ ERREUR: {str(e)}")
    import traceback
    traceback.print_exc()
    
finally:
    db.close()
