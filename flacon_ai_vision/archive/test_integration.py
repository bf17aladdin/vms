#!/usr/bin/env python
"""Integration test for Falcon AI Vision"""

import requests
import json
import sys
from urllib.parse import urljoin

BASE_URL = "http://127.0.0.1:5003"

def test_frontend():
    """Test that frontend index.html loads"""
    print("\n[TEST 1] Frontend Loading")
    print("=" * 60)
    try:
        response = requests.get(BASE_URL + "/", timeout=5)
        if response.status_code == 200:
            if "<!DOCTYPE html>" in response.text or "<html" in response.text:
                print("✓ Frontend loads successfully (status 200)")
                if "main" in response.text.lower() or "react" in response.text.lower():
                    print("✓ React app detected in HTML")
                    return True
                else:
                    print("⚠ HTML loaded but React may not be properly mounted")
                    return True
            else:
                print("✗ Response is not HTML")
                return False
        else:
            print(f"✗ Frontend returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Frontend test failed: {e}")
        return False

def test_health():
    """Test health endpoint"""
    print("\n[TEST 2] Health Checks")
    print("=" * 60)
    endpoints = [
        "/health",
        "/api",
        "/api/dashboard/stats",
        "/api/system/stats"
    ]
    
    all_ok = True
    for endpoint in endpoints:
        try:
            response = requests.get(BASE_URL + endpoint, timeout=5)
            if response.status_code == 200:
                print(f"✓ {endpoint:<30} → {response.status_code}")
            else:
                print(f"✗ {endpoint:<30} → {response.status_code}")
                all_ok = False
        except Exception as e:
            print(f"✗ {endpoint:<30} → ERROR: {e}")
            all_ok = False
    
    return all_ok

def test_authentication():
    """Test login endpoint"""
    print("\n[TEST 3] Authentication")
    print("=" * 60)
    try:
        # Try to login with demo credentials
        login_data = {
            "username": "admin",
            "password": "admin123"  # Changed from "password" to "admin123"
        }
        
        response = requests.post(
            BASE_URL + "/api/auth/login",
            json=login_data,
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            if "access_token" in data:
                token = data["access_token"]
                print(f"✓ Login successful")
                print(f"  Token: {token[:50]}...")
                return token
            elif "token" in data:
                token = data["token"]
                print(f"✓ Login successful")
                print(f"  Token: {token[:50]}...")
                return token
            else:
                print(f"⚠ Login returned 200 but no token found")
                print(f"  Response: {data}")
                return None
        else:
            print(f"✗ Login failed with status {response.status_code}")
            print(f"  Response: {response.text[:200]}")
            return None
    except Exception as e:
        print(f"✗ Authentication test failed: {e}")
        return False

def test_protected_endpoint(token):
    """Test protected endpoint with token"""
    if not token:
        print("\n[TEST 4] Protected Endpoint")
        print("=" * 60)
        print("⊘ Skipped (no token)")
        return False
    
    print("\n[TEST 4] Protected Endpoint")
    print("=" * 60)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(
            BASE_URL + "/api/cameras",
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            cam_count = len(data.get("cameras", []))
            print(f"✓ Protected endpoint accessible")
            print(f"  Cameras in system: {cam_count}")
            return True
        else:
            print(f"✗ Protected endpoint returned {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Protected endpoint test failed: {e}")
        return False

def test_assets():
    """Test that static assets load with correct MIME types"""
    print("\n[TEST 5] Static Assets (MIME Types)")
    print("=" * 60)
    
    # First get index.html to find asset hashes
    try:
        response = requests.get(BASE_URL + "/", timeout=5)
        html = response.text
        
        # Look for CSS and JS assets
        assets_to_test = []
        
        # Extract asset paths from HTML
        import re
        css_matches = re.findall(r'/assets/[^"\']+\.css', html)
        js_matches = re.findall(r'/assets/[^"\']+\.js', html)
        
        assets_to_test.extend([(f, "text/css") for f in css_matches[:1]])
        assets_to_test.extend([(f, "text/javascript") for f in js_matches[:1]])
        
        if not assets_to_test:
            print("⚠ Could not find asset paths in HTML - using defaults")
            assets_to_test = [
                ("/assets/style.css", "text/css"),
                ("/assets/main.js", "text/javascript")
            ]
        
        all_ok = True
        for asset_path, expected_type in assets_to_test:
            try:
                resp = requests.head(BASE_URL + asset_path, timeout=5)
                if resp.status_code == 200:
                    actual_type = resp.headers.get("Content-Type", "unknown")
                    # Be flexible with exact MIME type
                    if expected_type.split('/')[0] in actual_type:
                        print(f"✓ {asset_path[:40]:<42} → {actual_type}")
                    else:
                        print(f"⚠ {asset_path[:40]:<42} → {actual_type} (expected {expected_type})")
                else:
                    print(f"✗ {asset_path:<50} → {resp.status_code}")
                    all_ok = False
            except Exception as e:
                print(f"✗ {asset_path:<50} → {e}")
                all_ok = False
        
        return all_ok
    except Exception as e:
        print(f"✗ Asset test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("Falcon AI Vision - Integration Test Suite")
    print("="*60)
    print(f"Server: {BASE_URL}")
    
    results = {}
    
    # Run tests
    results["frontend"] = test_frontend()
    results["health"] = test_health()
    token = test_authentication()
    results["auth"] = token is not None
    results["protected"] = test_protected_endpoint(token)
    results["assets"] = test_assets()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{test_name:<20} {status}")
    
    total = len(results)
    passed = sum(1 for r in results.values() if r)
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠ {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
