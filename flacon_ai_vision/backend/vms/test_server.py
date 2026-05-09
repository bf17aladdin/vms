#!/usr/bin/env python3
"""Test script for unified server"""

import time
import requests
import json

# Wait for server to start
print("[*] Waiting for server startup...")
time.sleep(3)

try:
    # Test /health endpoint
    print("[*] Testing /health endpoint...")
    r = requests.get('http://127.0.0.1:5001//health', timeout=5)
    print(f"[OK] Status: {r.status_code}")
    print(f"[OK] Response: {json.dumps(r.json(), indent=2)}")
    
    # Test /api/cameras endpoint
    print("\n[*] Testing /api/cameras endpoint...")
    r = requests.get('http://127.0.0.1:5001//api/cameras', timeout=5)
    print(f"[OK] Status: {r.status_code}")
    print(f"[OK] Response: {json.dumps(r.json(), indent=2)}")
    
    # Test /api/auth/login endpoint
    print("\n[*] Testing /api/auth/login endpoint...")
    payload = {"username": "admin", "password": "admin123"}
    r = requests.post('http://127.0.0.1:5001//api/auth/login', json=payload, timeout=5)
    print(f"[OK] Status: {r.status_code}")
    print(f"[OK] Response: {json.dumps(r.json(), indent=2)}")
    
    print("\n[OK] All tests passed!")
    
except Exception as e:
    print(f"[!] Error: {e}")
