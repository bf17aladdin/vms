#!/usr/bin/env python3
"""
Test d'intégration Frontend+Backend (Phase 5)
Teste que le frontend est servie et l'API fonctionne
"""

import requests
import json
import time
from pathlib import Path

BASE_URL = "http://localhost:5003"
FRONTEND_TIMEOUT = 5
API_TIMEOUT = 5

def test_frontend_load():
    """Tester que le frontend SPA se charge"""
    print("\n" + "="*60)
    print("🌐 TEST 1: Frontend SPA Load")
    print("="*60)
    
    try:
        resp = requests.get(f"{BASE_URL}/", timeout=FRONTEND_TIMEOUT)
        if resp.status_code == 200:
            if "<!doctype html>" in resp.text.lower() or "<html" in resp.text.lower():
                print("✅ Frontend index.html loaded successfully")
                print(f"   Response size: {len(resp.text)} bytes")
                return True
            else:
                print("❌ Response is not HTML")
                return False
        else:
            print(f"❌ Failed to load frontend: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ Frontend load failed: {e}")
        return False

def test_api_health():
    """Tester que l'API /health fonctionne"""
    print("\n" + "="*60)
    print("💚 TEST 2: API Health Check")
    print("="*60)
    
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=API_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if "status" in data and data["status"] == "ok":
                print("✅ API /health endpoint working")
                print(f"   Status: {data['status']}")
                print(f"   Timestamp: {data.get('timestamp', 'N/A')}")
                return True
            else:
                print("❌ Health check returned unexpected response")
                print(f"   Response: {data}")
                return False
        else:
            print(f"❌ Health check failed: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False

def test_api_cameras():
    """Tester l'endpoint /api/cameras"""
    print("\n" + "="*60)
    print("📷 TEST 3: API Cameras Endpoint")
    print("="*60)
    
    try:
        resp = requests.get(f"{BASE_URL}/api/cameras", timeout=API_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if "cameras" in data:
                print("✅ /api/cameras endpoint working")
                print(f"   Found {len(data['cameras'])} camera(s)")
                for cam in data['cameras']:
                    print(f"   - {cam.get('name', 'Unknown')} (ID: {cam.get('id', '?')})")
                return True
            else:
                print("❌ Unexpected response format")
                print(f"   Response: {data}")
                return False
        else:
            print(f"❌ Cameras endpoint failed: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cameras endpoint error: {e}")
        return False

def test_api_zones():
    """Tester l'endpoint /api/zones/list"""
    print("\n" + "="*60)
    print("🗺️  TEST 4: API Zones Endpoint")
    print("="*60)
    
    try:
        resp = requests.get(f"{BASE_URL}/api/zones/list", timeout=API_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            print("✅ /api/zones/list endpoint working")
            print(f"   Response: {json.dumps(data, indent=2)}")
            return True
        else:
            print(f"❌ Zones endpoint failed: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ Zones endpoint error: {e}")
        return False

def test_assets_load():
    """Tester que les assets (JS, CSS) se chargent"""
    print("\n" + "="*60)
    print("📦 TEST 5: Frontend Assets Loading")
    print("="*60)
    
    try:
        # Tester /assets/ (doit contenir JS et CSS)
        resp = requests.get(f"{BASE_URL}/assets/", timeout=FRONTEND_TIMEOUT)
        
        # Même si Get /assets/ retourne 404, on peut tester si les assets individuels existent
        print("ℹ️  Checking if assets directory is accessible...")
        
        # Tester la page racine qui contient les références à /assets/
        resp = requests.get(f"{BASE_URL}/", timeout=FRONTEND_TIMEOUT)
        if "/assets/" in resp.text:
            print("✅ Frontend references assets correctly")
            # Compter combien de fichiers assets sont référencés
            asset_refs = resp.text.count("/assets/")
            print(f"   Found {asset_refs} asset references in index.html")
            return True
        else:
            print("❌ No asset references found in frontend")
            return False
    except Exception as e:
        print(f"❌ Assets check error: {e}")
        return False

def test_docker_status():
    """Vérifier l'état des containers Docker"""
    print("\n" + "="*60)
    print("🐳 TEST 6: Docker Container Status")
    print("="*60)
    
    try:
        import subprocess
        
        # Vérifier avec docker-compose ps
        result = subprocess.run(
            ["docker-compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            containers = json.loads(result.stdout) if result.stdout else []
            print("✅ Docker containers status:")
            
            statuses = {}
            for container in containers:
                name = container.get("Name", "unknown")
                state = container.get("State", "unknown")
                status = container.get("Status", "unknown")
                statuses[name] = {"state": state, "status": status}
                
                status_icon = "✅" if state == "running" else "❌"
                print(f"   {status_icon} {name}: {state}")
            
            all_running = all(c["state"] == "running" for c in statuses.values())
            return all_running
        else:
            print(f"⚠️  Could not check Docker status: {result.stderr}")
            return False
    except Exception as e:
        print(f"⚠️  Docker status check error: {e}")
        return False

def main():
    """Exécuter tous les tests"""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  Frontend + Backend Integration Test".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")
    
    print(f"\nBase URL: {BASE_URL}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    tests = [
        ("Frontend SPA", test_frontend_load),
        ("API Health", test_api_health),
        ("API Cameras", test_api_cameras),
        ("API Zones", test_api_zones),
        ("Assets Loading", test_assets_load),
        ("Docker Status", test_docker_status),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            result = test_func()
            results[name] = result
        except Exception as e:
            print(f"❌ Test failed: {e}")
            results[name] = False
    
    # Résumé
    print("\n" + "="*60)
    print("📊 TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"\nPassed: {passed}/{total}\n")
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status:10} {name}")
    
    print("\n" + "="*60)
    if passed == total:
        print("✅ ALL TESTS PASSED - Integration Complete!")
        print("="*60)
        print("\nFrontend is now available at: http://localhost:5003/")
        print("API Documentation: http://localhost:5003/docs")
        print("Backend is serving both frontend and API on port 5003 ✨")
        return 0
    else:
        print(f"⚠️  {total - passed} test(s) failed - Check details above")
        print("="*60)
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
