#!/usr/bin/env python3
"""
Force clear cache headers + restart server
"""
import shutil
import os
import sys

# Step 1: Clean node_modules and package-lock
frontend_path = r"c:\Users\boufm\Desktop\eye_of_falcon\eye-of-falcon\vms\frontend"
print("🧹 Step 1: Cleaning dependencies...")

try:
    node_modules = os.path.join(frontend_path, "node_modules")
    if os.path.exists(node_modules):
        shutil.rmtree(node_modules)
        print(f"   ✅ Deleted {node_modules}")
except Exception as e:
    print(f"   ⚠️  Could not delete node_modules: {e}")

# Step 2: Reinstall
print("\n📦 Step 2: Reinstalling dependencies...")
os.chdir(frontend_path)
result = os.system("npm install --legacy-peer-deps")
if result != 0:
    print("❌ npm install failed!")
    sys.exit(1)

# Step 3: Clean dist
print("\n🗑️  Step 3: Cleaning dist folder...")
try:
    dist_path = os.path.join(frontend_path, "dist")
    if os.path.exists(dist_path):
        shutil.rmtree(dist_path)
        print(f"   ✅ Deleted {dist_path}")
except Exception as e:
    print(f"   ⚠️  Could not delete dist: {e}")

# Step 4: Rebuild
print("\n🏗️  Step 4: Rebuilding frontend...")
result = os.system("npm run build")
if result != 0:
    print("❌ npm run build failed!")
    sys.exit(1)

print("\n" + "="*60)
print("✅ FRONTEND CLEANED AND REBUILT SUCCESSFULLY!")
print("="*60)
print("\nNext steps:")
print("1. Close the browser completely")
print("2. Start the backend: python -m vms.backend.main")
print("3. Open http://localhost:5003 in a fresh browser window")
print("4. Force hard refresh: Ctrl + Shift + R")
print("5. Errors should be gone!")
