#!/usr/bin/env python3
"""
Test rapide pour capturer les erreurs React
"""
import urllib.request
import time
import subprocess
import json

# Assuming server is already running, test it
try:
    print("Testing http://127.0.0.1:5003/ ...")
    
    req = urllib.request.Request("http://127.0.0.1:5003/", headers={'User-Agent': 'test'})
    with urllib.request.urlopen(req, timeout=5) as resp:
        html = resp.read().decode('utf-8', errors='replace')
        
    print(f"✅ Got {len(html)} bytes")
    
    # Check for React errors
    if "Minified React error" in html:
        import re
        match = re.search(r'(Minified React error[^<]*)', html[:2000])
        if match:
            print(f"\n⚠️ FOUND ERROR: {match.group(1)[:200]}")
    else:
        print("✅ No obvious React errors in initial HTML")
    
    # Check assets are present
    if "/assets/" in html:
        print("✅ Assets references found")
    
    # Check for root div
    if '<div id="root">' in html or '<div id="root"/>' in html:
        print("✅ React root div found")
    else:
        print("⚠️ React root div not found!")
        
    # Try to get API info
    print("\nTesting /api endpoint...")
    with urllib.request.urlopen("http://127.0.0.1:5003/api") as resp:
        api = json.loads(resp.read().decode('utf-8'))
        print(f"✅ API responds: {api.get('name')}")
        
    print("\n" + "="*70)
    print("✅ Basic tests passed. Open browser and check console for details.")
    print("="*70)
    
except urllib.error.URLError as e:
    print(f"❌ Connection failed: {e}")
    print("Make sure server is running: python -m uvicorn vms.backend.main:app --host 127.0.0.1 --port 5003")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
