#!/usr/bin/env python
"""Initialize admin user in database"""

from vms.backend.core.database import SessionLocal, engine
from vms.backend.models import User, Base

# Create tables
Base.metadata.create_all(bind=engine)
print("✅ Tables créées")

# Check if admin exists
with SessionLocal() as db:
    admin = db.query(User).filter(User.username == 'admin').first()
    if admin:
        print(f"✅ Utilisateur admin existe (ID: {admin.id})")
    else:
        print("❌ Utilisateur admin n'existe pas - création...")
        from vms.backend.crud import create_user
        from vms.backend.schemas import UserCreate
        
        admin_data = UserCreate(
            username='admin',
            email='admin@falcon.local',
            password='admin123',
            is_admin=True
        )
        admin = create_user(db, admin_data)
        print(f"✅ Utilisateur admin créé (ID: {admin.id})")
        print(f"   Credentials: admin / admin123")
