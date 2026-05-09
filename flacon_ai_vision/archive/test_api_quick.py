#!/usr/bin/env python3
"""
Quick API test script to verify backend endpoints and authentication issues
"""

import requests
import json
from typing import Optional

BASE_URL = "http://localhost:5003"

def test_endpoint(method: str, endpoint: str, auth_token: Optional[str] = None, data: dict = None):
    """Test an API endpoint"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    
    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=2)
        elif method == "POST":
            resp = requests.post(url, json=data, headers=headers, timeout=2)
        else:
            return None
        
        status_icon = "✅" if resp.status_code < 400 else "❌"
        print(f"{status_icon} {method:4s} {endpoint:30s} → {resp.status_code}", end="")
        
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", "No detail")
                print(f" ({detail})")
            except:
                print(f" ({resp.text[:50]})")
        else:
            print()
        
        return resp
    
    except requests.exceptions.ConnectionError:
        print(f"❌ {method:4s} {endpoint:30s} → CONN ERROR (backend not running)")
        return None
    except Exception as e:
        print(f"❌ {method:4s} {endpoint:30s} → ERROR ({str(e)[:40]})")
        return None

def main():
    print("""
╔════════════════════════════════════════════════════════════╗
║           QUICK API ENDPOINT TEST                          ║
║  (Testing to verify authentication & indentation issues)   ║
╚════════════════════════════════════════════════════════════╝
    """)
    
    print("Testing UNAUTHENTICATED endpoints (should be accessible):")
    print("-" * 60)
    test_endpoint("GET", "/docs")
    test_endpoint("GET", "/openapi.json")
    
    print("\nTesting AUTHENTICATED endpoints (expect 401 without token):")
    print("-" * 60)
    test_endpoint("GET", "/api/cameras")
    test_endpoint("GET", "/api/personnel")
    test_endpoint("GET", "/api/events")
    test_endpoint("GET", "/api/zones")
    
    print("\nTesting HEALTH/STATUS endpoints:")
    print("-" * 60)
    test_endpoint("GET", "/api/health")
    test_endpoint("GET", "/health")
    
    print("\nInterpretation:")
    print("=" * 60)
    print("""
✅ /docs, /openapi.json, /health          → Should work (no auth needed)
❌ /api/cameras, /api/personnel, etc.     → Expected 401 (need auth token)
   This is NORMAL behavior - not a failure

The 401 errors indicate that:
1. Backend is running correctly ✓
2. Authentication is enforced ✓
3. Endpoints exist and are protected ✓

To access protected endpoints, you need to:
1. Login: POST /api/auth/login (get token)
2. Add header: Authorization: Bearer <token>
3. Retry endpoin
    """)

if __name__ == "__main__":
    main()
