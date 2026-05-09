#!/usr/bin/env python
"""Test d'accès aux assets compilés"""
import requests
import re

API_BASE = "http://localhost:5003"

print("\n" + "="*70)
print(" 🎯 ASSET LOADING TEST - Compiled Frontend")
print("="*70 + "\n")

# 1. Récupérer le HTML compilé
try:
    r = requests.get(f"{API_BASE}/", timeout=3)
    if r.status_code != 200:
        print(f"❌ Failed to fetch main page: HTTP {r.status_code}")
        exit(1)
    
    html = r.text
    print(f"✅ Main page loaded ({len(html)} bytes of HTML)\n")
    
    # 2. Extraire les références aux assets
    css_match = re.search(r'href="(/assets/[^"]+\.css)"', html)
    js_match = re.search(r'src="(/assets/[^"]+\.js)"', html)
    
    assets_to_test = []
    
    if css_match:
        css_url = css_match.group(1)
        assets_to_test.append(("CSS", css_url))
        print(f"Found CSS: {css_url}")
    
    if js_match:
        js_url = js_match.group(1)
        assets_to_test.append(("JavaScript", js_url))
        print(f"Found JS:  {js_url}")
    
    if not assets_to_test:
        print("⚠️  No compiled assets found in HTML")
        print("\nHTML Content (first 500 chars):")
        print(html[:500])
    else:
        # 3. Tester l'accès à chaque asset
        print("\n" + "-"*70)
        print("Testing Asset Access...")
        print("-"*70)
        
        all_ok = True
        for asset_type, asset_path in assets_to_test:
            try:
                r = requests.head(f"{API_BASE}{asset_path}", timeout=3)
                if r.status_code == 200:
                    size = r.headers.get('Content-Length', 'unknown')
                    print(f"✅ {asset_type:12} → HTTP {r.status_code} ({size} bytes) - {asset_path}")
                else:
                    print(f"❌ {asset_type:12} → HTTP {r.status_code} - {asset_path}")
                    all_ok = False
            except Exception as e:
                print(f"❌ {asset_type:12} → Error: {str(e)[:50]}")
                all_ok = False
        
        print("\n" + "="*70)
        if all_ok:
            print("✨ All compiled assets are accessible!")
        else:
            print("⚠️  Some assets failed to load")
        print("="*70 + "\n")
        
except Exception as e:
    print(f"❌ Error: {e}")
    exit(1)
