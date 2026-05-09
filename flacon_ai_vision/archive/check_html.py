#!/usr/bin/env python
"""Check HTML structure and React mounting"""

import requests

BASE_URL = "http://127.0.0.1:5003"

response = requests.get(BASE_URL + "/")
html = response.text

print("=" * 60)
print("HTML Analysis")
print("=" * 60)

# Check for key elements
checks = [
    ("<!DOCTYPE html>", "HTML doctype"),
    ("<html", "HTML tag"),
    ('<div id="root">', "React root div"),
    ('id="root"', "Root id attribute"),
    ("<script", "Script tags"),
    ('index-', "Vite asset hashes"),
    ('js"', "JavaScript files"),
    ('css"', "CSS files"),
]

print("\n[Checks]")
for check, description in checks:
    found = check.lower() in html.lower()
    status = "✓" if found else "✗"
    print(f"{status} {description:<30} {'Found' if found else 'Missing'}")

# Show script tags
print("\n[Script Tags Found]")
import re
scripts = re.findall(r'<script[^>]*src="[^"]*"[^>]*>', html)
for i, script in enumerate(scripts[:5], 1):
    print(f"  {i}. {script[:80]}...")

# Show root div
print("\n[Root Container]")
root_match = re.search(r'<div[^>]*id="root"[^>]*>', html)
if root_match:
    print(f"  Found: {root_match.group(0)}")
else:
    print("  Not found")

print("\n[HTML Size]")
print(f"  Total size: {len(html):,} bytes")
print(f"  First 500 chars:\n  {html[:500]}")
