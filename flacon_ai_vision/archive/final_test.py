#!/usr/bin/env python
"""
Script de test final pour Falcon AI Vision
Vérifie que tous les endpoints sont accessibles
"""

import requests
import time
import sys

# Configuration
API_BASE_URL = "http://localhost:5003"
TIMEOUT = 5

# Liste des endpoints à tester
ENDPOINTS = [
    ("/health", "Health Check"),
    ("/", "Main Interface (Index/Login)"),
    ("/admin", "Admin Dashboard"),
    ("/user", "User Dashboard"),
    ("/docs", "Swagger API Docs"),
    ("/redoc", "ReDoc"),
    ("/admin/index.html", "Admin Page"),
    ("/user/index.html", "User Page"),
]

# Fichiers statiques à vérifier
STATIC_FILES = [
    "/static/dash board.css",
    "/static/style.css",
    "/static/login.css",
    "/shared/",
]

def print_header(text):
    """Affiche un header formaté"""
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)

def test_endpoint(path, description):
    """Teste un endpoint spécifique"""
    url = f"{API_BASE_URL}{path}"
    try:
        response = requests.get(url, timeout=TIMEOUT, allow_redirects=True)
        status = response.status_code
        content_type = response.headers.get('Content-Type', 'unknown')
        content_len = len(response.content)
        
        # Détermine le symbole
        if status == 200:
            symbol = "✅"
        elif status in [301, 302]:
            symbol = "↪️"
        else:
            symbol = "⚠️"
        
        # Affiche le résultat
        print(f"{symbol} {description:40} → HTTP {status} ({content_len} bytes)")
        
        # Affiche le Content-Type si HTML
        if 'html' in content_type.lower():
            print(f"   Content-Type: {content_type}")
            # Vérifie que c'est du HTML valide
            if b'<!DOCTYPE' in response.content[:200] or b'<html' in response.content[:200]:
                print(f"   ✓ Valid HTML document")
            else:
                print(f"   ⚠ Could be HTML but not detected")
        
        return status == 200 or status in [301, 302]
    
    except requests.exceptions.ConnectionError:
        print(f"❌ {description:40} → CONNECTION ERROR (Server not running?)")
        return False
    except requests.exceptions.Timeout:
        print(f"❌ {description:40} → TIMEOUT (Server not responding)")
        return False
    except Exception as e:
        print(f"❌ {description:40} → ERROR: {str(e)[:40]}")
        return False

def main():
    """Lance tous les tests"""
    print_header("🧪 FALCON AI VISION - FINAL TEST SUITE")
    
    print(f"\n📍 Base URL: {API_BASE_URL}")
    print(f"⏱️  Timeout: {TIMEOUT}s\n")
    
    # Test de connexion au serveur
    print("\n1️⃣  Server Connection Test...")
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=TIMEOUT)
        if response.status_code == 200:
            print("✅ Server is running and responding")
        else:
            print(f"⚠️  Server is running but health check returned {response.status_code}")
    except Exception as e:
        print(f"❌ Cannot connect to server: {e}")
        print("\n💡 Start the server with:")
        print('   cd "C:\\Users\\boufm\\Desktop\\ey_of_falcon_platforme\\ey_of_falcon_platforme"')
        print("   .\\venv\\Scripts\\activate")
        print("   uvicorn vms.backend.main:app --reload --host 127.0.0.1 --port 5003")
        return False
    
    # Test des endpoints
    print("\n2️⃣  API Endpoints Test...")
    print("-" * 70)
    
    passed = 0
    total = len(ENDPOINTS)
    
    for path, description in ENDPOINTS:
        if test_endpoint(path, description):
            passed += 1
    
    # Test des fichiers statiques
    print("\n3️⃣  Static Files Test...")
    print("-" * 70)
    
    static_passed = 0
    static_total = len(STATIC_FILES)
    
    for path in STATIC_FILES:
        url = f"{API_BASE_URL}{path}"
        try:
            response = requests.head(url, timeout=TIMEOUT, allow_redirects=True)
            if response.status_code == 200:
                symbol = "✅"
                static_passed += 1
            else:
                symbol = "⚠️"
            print(f"{symbol} {path:40} → HTTP {response.status_code}")
        except Exception as e:
            print(f"⚠️  {path:40} → Skipped ({str(e)[:30]})")
    
    # Résumé
    print_header("📊 TEST SUMMARY")
    
    print(f"\n✅ API Endpoints:     {passed}/{total} passed")
    print(f"✅ Static Files:      {static_passed}/{static_total} working")
    
    total_tests = passed + total
    total_passed = passed + static_passed
    
    if total_passed == total_tests:
        print("\n🎉 ALL TESTS PASSED! Falcon AI Vision is ready to use!")
        print_header("🚀 NEXT STEPS")
        print(f"""
1. Open your browser to: http://localhost:5003/
2. Login with your credentials
3. Explore the dashboards:
   - Admin:  http://localhost:5003/admin
   - User:   http://localhost:5003/user
4. Check API docs: http://localhost:5003/docs
        """)
        return True
    else:
        print(f"\n⚠️  {total_tests - total_passed} test(s) failed")
        print("\n💡 Debugging tips:")
        print("  - Check server logs for errors")
        print("  - Verify file paths in backend/core/config.py")
        print("  - Ensure vms/frontend/ directory exists and contains all files")
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏹️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
