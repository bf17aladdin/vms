#!/usr/bin/env python
"""
Script pour reconstruire le frontend, redémarrer le serveur et tester React
"""
import subprocess
import sys
import time
import urllib.request
import json
import re

def run_cmd(cmd, description, background=False):
    print(f"\n{'='*70}")
    print(f"▶ {description}")
    print(f"{'='*70}")
    print(f"$ {cmd}\n")
    
    if background:
        process = subprocess.Popen(cmd, shell=True)
        print(f"Process started with PID {process.pid}")
        return process
    else:
        result = subprocess.run(cmd, shell=True)
        return result.returncode == 0

# Step 1: Build frontend
if not run_cmd("python build_frontend.py", "Step 1/3: Building React Frontend"):
    print("❌ Build failed!")
    sys.exit(1)

print("✅ Build completed")

# Step 2: Start server
print("\n" + "="*70)
print("▶ Step 2/3: Starting FastAPI Server")
print("="*70)
print("$ python -m uvicorn vms.backend.main:app --reload --host 127.0.0.1 --port 5003\n")

server = subprocess.Popen(
    "python -m uvicorn vms.backend.main:app --reload --host 127.0.0.1 --port 5003",
    shell=True
)

print(f"Server started with PID {server.pid}")
print("Waiting 3 seconds for server to start...")
time.sleep(3)

# Step 3: Test and capture React errors
print("\n" + "="*70)
print("▶ Step 3/3: Testing Frontend and Capturing React Errors")
print("="*70)

try:
    # Fetch the HTML
    print("\nFetching http://127.0.0.1:5003/ ...")
    with urllib.request.urlopen("http://127.0.0.1:5003/", timeout=5) as resp:
        html = resp.read().decode('utf-8')
        
    print(f"✅ Received {len(html)} bytes of HTML")
    
    # Check for React error messages in HTML
    if "Minified React error" in html:
        print("\n⚠️ FOUND: Minified React error in HTML")
        # Extract error code
        match = re.search(r'Minified React error #(\d+)', html)
        if match:
            print(f"Error code: #{match.group(1)}")
    
    # Check assets
    print("\n📦 Checking asset loading...")
    if "/assets/" in html:
        print("✅ Assets referenced in HTML")
        # Try to load one
        match = re.search(r'/assets/[^"]+\.js', html)
        if match:
            asset_url = f"http://127.0.0.1:5003{match.group(0)}"
            print(f"\nTesting asset: {asset_url}")
            with urllib.request.urlopen(asset_url, timeout=5) as resp:
                content_type = resp.getheader('Content-Type')
                size = len(resp.read())
                print(f"✅ Asset loaded: {content_type}, {size} bytes")
    
    # Check WebSocket support
    print("\n🔗 Checking WebSocket endpoints...")
    api_url = "http://127.0.0.1:5003/api"
    with urllib.request.urlopen(api_url) as resp:
        api_info = json.loads(resp.read().decode('utf-8'))
        print(f"✅ API info: {json.dumps(api_info, indent=2)}")
    
    print("\n" + "="*70)
    print("✅ HTML page loaded successfully")
    print("="*70)
    print("\n📋 Summary:")
    print(f"  • HTML Size: {len(html)} bytes")
    print(f"  • React Errors: {'Found ⚠️' if 'Minified React error' in html else 'None 🟢'}")
    print(f"  • Assets: {'Loaded ✅' if '/assets/' in html else 'Missing ❌'}")
    print(f"  • WebSocket: {'/api/ws' in html if '/api/ws' in html else 'Check in browser console'}")
    
    print("\n🔗 NEXT: Open http://127.0.0.1:5003/ in your browser and check:")
    print("  1. Console for React errors (F12 > Console)")
    print("  2. Network tab for failed requests")
    print(f"  3. Element tree - inspect <div id='root'>")
    
except Exception as e:
    print(f"\n❌ Error during testing: {e}")
    print(f"\n🔧 Troubleshooting:")
    print(f"  • Check if server is running: http://127.0.0.1:5003/health")
    print(f"  • Check server logs above")
    print(f"  • Make sure port 5003 is available")

finally:
    print("\n" + "="*70)
    print("Server is running in background. Press Ctrl+C to stop.")
    print("="*70)
    
    try:
        server.wait()
    except KeyboardInterrupt:
        print("\n\nShutting down server...")
        server.terminate()
        server.wait(timeout=5)
        print("✅ Server stopped")
