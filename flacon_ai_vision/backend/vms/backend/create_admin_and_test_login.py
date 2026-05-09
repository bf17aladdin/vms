#!/usr/bin/env python3
"""Créer un admin de test (si manquant) et tester POST /api/auth/login"""
import time
import sys
import os
import requests

# Ensure project root is on sys.path so `vms` package is importable when running script directly
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from vms.backend.core.database import SessionLocal
from vms.backend.core.security import hash_password
from vms.backend import models

DB_USER = "admin"
DB_PASS = "admin123"
LOGIN_URL = "http://127.0.0.1:5003/api/auth/login"


def ensure_admin():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == DB_USER).first()
        if user:
            print(f"Admin exists: {user.username} (id={user.id})")
            return True
        # create admin
        hashed = hash_password(DB_PASS)
        new = models.User(
            username=DB_USER,
            email="admin@example.local",
            full_name="Admin Test",
            hashed_password=hashed,
            is_active=True,
            is_admin=True,
        )
        db.add(new)
        db.commit()
        db.refresh(new)
        print(f"Created admin: {new.username} (id={new.id})")
        return True
    except Exception as e:
        print("Error creating admin:", e)
        return False
    finally:
        db.close()


def test_login():
    payload = {"username": DB_USER, "password": DB_PASS}
    try:
        r = requests.post(LOGIN_URL, json=payload, timeout=5)
        print("POST", LOGIN_URL, "=>", r.status_code)
        try:
            print(r.json())
        except Exception:
            print(r.text[:1000])
    except Exception as e:
        print("Request error:", e)


if __name__ == '__main__':
    ok = ensure_admin()
    if not ok:
        print("Cannot ensure admin; aborting login test")
    else:
        # Wait briefly to ensure server ready
        time.sleep(0.5)
        test_login()
