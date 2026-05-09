#!/usr/bin/env python
# Debug script pour tester verify_password

from core.security import verify_password, hash_password
from core.database import SessionLocal
import models


# Connect to database
def main():
    db = SessionLocal()
    try:
        # Get admin user
        admin = db.query(models.User).filter(models.User.username == "admin").first()

        if admin:
            print(f"✅ User found: {admin.username}")
            print(f"Hashed password in DB: {admin.hashed_password}")
            print(f"Password to test: admin123")
            
            # Test verify
            result = verify_password("admin123", admin.hashed_password)
            print(f"\nverify_password('admin123', db_hash) = {result}")
            
            # Test with wrong password
            result2 = verify_password("wrongpassword", admin.hashed_password)
            print(f"verify_password('wrongpassword', db_hash) = {result2}")
            
            # Test hash creation
            new_hash = hash_password("admin123")
            print(f"\nNew hash of 'admin123': {new_hash}")
            print(f"Verify new hash: {verify_password('admin123', new_hash)}")
        else:
            print("❌ Admin user not found!")

    finally:
        db.close()


if __name__ == "__main__":
    main()
