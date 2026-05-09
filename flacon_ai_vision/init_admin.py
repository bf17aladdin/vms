#!/usr/bin/env python3
"""
Initialiser l'utilisateur admin dans la base de données
"""

import sys
sys.path.insert(0, 'backend')

from vms.backend.core.database import SessionLocal, engine
from vms.backend.models import User, Base
from vms.backend.core.security import hash_password

# Créer les tables
Base.metadata.create_all(bind=engine)
print("✅ Tables créées/vérifiées")

# Vérifier/créer admin
db = SessionLocal()
try:
    admin = db.query(User).filter(User.username == 'admin').first()
    if admin:
        print(f"✅ Utilisateur 'admin' existe déjà (ID: {admin.id})")
    else:
        print("Création de l'utilisateur admin...")
        admin_user = User(
            username='admin',
            email='admin@falcon.local',
            hashed_password=hash_password('admin123'),
            is_admin=True
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        print(f"✅ Utilisateur admin créé (ID: {admin_user.id})")
        print(f"   Username: admin")
        print(f"   Password: admin123")
finally:
    db.close()
