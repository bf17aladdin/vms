#!/usr/bin/env python
"""Test rapide des endpoints Falcon AI Vision"""
import requests
import json

API_BASE = "http://localhost:5003"
endpoints = [
    "/health",
    "/",
    "/admin",
    "/user",
    "/docs",
]

print("\n" + "="*60)
print(" 🧪 FALCON AI VISION - QUICK TEST")
print("="*60 + "\n")

results = []
for path in endpoints:
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=3)
        status = "✅" if r.status_code == 200 else "⚠️"
        results.append(f"{status} {path:20} → HTTP {r.status_code}")
    except Exception as e:
        results.append(f"❌ {path:20} → Error: {str(e)[:30]}")

for result in results:
    print(result)

print("\n" + "="*60)
passed = sum(1 for r in results if "✅" in r)
print(f"✨ Results: {passed}/{len(results)} endpoints working")
print("="*60 + "\n")
