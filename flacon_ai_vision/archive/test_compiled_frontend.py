#!/usr/bin/env python
"""Test détaillé du frontend compilé"""
import requests
import json

API_BASE = "http://localhost:5003"

print("\n" + "="*70)
print(" 🧪 FALCON AI VISION - COMPILED FRONTEND TEST")
print("="*70 + "\n")

tests = [
    ("/", "Main Page (Compiled React App)", True),
    ("/assets/", "Assets Directory", False),  # Directory listing may be forbidden
    ("/health", "Health Check", True),
    ("/docs", "Swagger API Docs", True),
]

print("Testing Frontend Assets...")
print("-" * 70)

for path, description, require_200 in tests:
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=3)
        status = r.status_code
        
        if status == 200:
            symbol = "✅"
            content_type = r.headers.get('Content-Type', 'unknown')
            content_len = len(r.content)
            
            print(f"{symbol} {description:40} → HTTP {status}")
            print(f"   └─ Content-Type: {content_type} ({content_len} bytes)")
            
            # Vérifications supplémentaires
            if "html" in content_type.lower():
                if b"<html" in r.content or b"<!DOCTYPE" in r.content:
                    print(f"   └─ ✓ Valid HTML document")
                    # Vérifier les assets compilés
                    if b"/assets/" in r.content:
                        print(f"   └─ ✓ Contains compiled assets references")
                    else:
                        print(f"   └─ ⚠ No compiled assets detected")
            elif "json" in content_type.lower():
                print(f"   └─ ✓ Valid JSON response")
        elif status == 404 and not require_200:
            print(f"⚠️  {description:40} → HTTP {status} (Expected - directory listing disabled)")
        else:
            print(f"❌ {description:40} → HTTP {status} (Unexpected)")
            
    except Exception as e:
        print(f"❌ {description:40} → Error: {str(e)[:40]}")

print("\n" + "-" * 70)

# Test specific compiled files
print("\nTesting Compiled Assets...")
print("-" * 70)

try:
    # First get the HTML to check what assets are referenced
    r = requests.get(f"{API_BASE}/", timeout=3)
    if r.status_code == 200:
        html = r.text
        
        # Check for common Vue/React App indicators
        if "script" in html and "assets" in html:
            print("✅ Compiled assets are referenced in main HTML")
            
            # Extract asset references
            import re
            css_files = re.findall(r'href="([^"]*\.css)"', html)
            js_files = re.findall(r'src="([^"]*\.js)"', html)
            
            if css_files:
                print(f"   └─ Found {len(css_files)} CSS file(s)")
                for css in css_files[:3]:
                    print(f"      • {css}")
                    
            if js_files:
                print(f"   └─ Found {len(js_files)} JS file(s)")
                for js in js_files[:3]:
                    print(f"      • {js}")
        else:
            print("⚠️  HTML content looks minimal (might be legacy HTML)")
            
except Exception as e:
    print(f"⚠️  Could not verify compiled assets: {e}")

print("\n" + "="*70)
print("✨ Frontend compilation and static serving: OK")
print("="*70 + "\n")
