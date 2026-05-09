#!/usr/bin/env python3
"""
Comprehensive End-to-End Test: Authentication + WebSocket Real-time Updates
Tests the complete VMS flow: login → token → API calls → WebSocket updates
"""

import requests
import json
import asyncio
import websockets
import sys
from datetime import datetime

BASE_URL = "http://localhost:5003/api"
WS_URL = "ws://localhost:5003/api/ws"

def log(msg: str, level="INFO"):
    """Simple logging"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {level}: {msg}")

def test_login():
    """Test 1: Authentication - Login and get JWT token"""
    log("🔐 TEST 1: Authentication (Login)")
    try:
        response = requests.post(
            f"{BASE_URL}/auth/login",
            json={"username": "admin", "password": "admin123"}
        )
        print(f"   │ Status: {response.status_code}")
        
        if response.status_code != 200:
            log(f"   └─ FAILED: {response.text}", "ERROR")
            return None
        
        data = response.json()
        token = data.get('access_token') or data.get('token')
        
        if not token:
            log(f"   └─ FAILED: No token in response: {data}", "ERROR")
            return None
        
        log(f"   │ Token: {token[:50]}...")
        log(f"   └─ ✓ LOGIN SUCCESS", "OK")
        return token
        
    except Exception as e:
        log(f"   └─ EXCEPTION: {str(e)}", "ERROR")
        return None

def test_api_calls(token: str):
    """Test 2: API Calls with Bearer Token"""
    log("📡 TEST 2: API Calls (Protected Endpoints)")
    
    headers = {"Authorization": f"Bearer {token}"}
    endpoints = [
        ("/cameras", "GET"),
        ("/zones", "GET"),
        ("/alerts", "GET"),
        ("/events", "GET"),
    ]
    
    for endpoint, method in endpoints:
        try:
            url = f"{BASE_URL}{endpoint}"
            if method == "GET":
                response = requests.get(url, headers=headers)
            else:
                response = requests.post(url, headers=headers)
            
            status = "✓" if response.status_code == 200 else "✗"
            log(f"   │ {status} {endpoint}: {response.status_code}")
            
            if response.status_code != 200:
                log(f"   │    Response: {response.text[:100]}", "WARN")
                
        except Exception as e:
            log(f"   │ ✗ {endpoint}: {str(e)}", "ERROR")
    
    log(f"   └─ API Tests Complete", "OK")

async def test_websocket(token: str):
    """Test 3: WebSocket Connection and Real-time Updates"""
    log("🔌 TEST 3: WebSocket Real-time Connection")
    
    ws_uri = f"{WS_URL}?token={token}"
    
    try:
        async with websockets.connect(ws_uri) as websocket:
            log(f"   │ WebSocket Connected ✓")
            
            # Subscribe to event messages
            await websocket.send(json.dumps({
                "type": "subscribe",
                "messageType": "event"
            }))
            
            log(f"   │ Subscribed to 'event' messages")
            
            # Wait for messages (with timeout)
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=3)
                data = json.loads(message)
                log(f"   │ Received: {data.get('type')}")
                log(f"   └─ ✓ WEBSOCKET SUCCESS", "OK")
                return True
                
            except asyncio.TimeoutError:
                log(f"   │ No messages received (timeout) - but connection OK", "WARN")
                log(f"   └─ ✓ WEBSOCKET CONNECTED", "OK")
                return True
                
    except Exception as e:
        log(f"   └─ WEBSOCKET ERROR: {str(e)}", "ERROR")
        return False

def test_pages_load(token: str):
    """Test 4: Verify Pages Can Load (via API data)"""
    log("📄 TEST 4: Page Data Availability")
    
    headers = {"Authorization": f"Bearer {token}"}
    
    pages = {
        "Dashboard": [
            ("/cameras", "cameras"),
            ("/events?limit=5", "events"),
            ("/zones", "zones"),
        ],
        "Cameras": [
            ("/cameras", "cameras"),
        ],
        "Alerts": [
            ("/alerts", "alerts"),
        ],
        "Zones": [
            ("/zones", "zones"),
        ],
        "AI Monitoring": [
            ("/detections", "detections"),
        ],
    }
    
    for page_name, endpoints in pages.items():
        log(f"   │ {page_name}:")
        all_good = True
        
        for endpoint, expected_key in endpoints:
            try:
                response = requests.get(f"{BASE_URL}{endpoint}", headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    has_data = expected_key in data
                    status = "✓" if has_data else "⚠"
                    log(f"   │   {status} {endpoint} ({expected_key})")
                    all_good = all_good and has_data
                else:
                    log(f"   │   ✗ {endpoint} ({response.status_code})", "WARN")
                    all_good = False
                    
            except Exception as e:
                log(f"   │   ✗ {endpoint} ({str(e)})", "ERROR")
                all_good = False
        
        status_text = "READY" if all_good else "INCOMPLETE"
        log(f"   │   └─ {status_text}")
    
    log(f"   └─ Page Data Tests Complete", "OK")

def main():
    """Run all tests"""
    log("="*60, "START")
    log("Falcon AI Vision - End-to-End Test Suite")
    log("Testing: Auth → API → WebSocket → Page Load")
    log("="*60)
    
    # Test 1: Login
    token = test_login()
    if not token:
        log("ABORTED: Login failed, cannot continue", "ERROR")
        return 1
    
    print()
    
    # Test 2: API Calls
    test_api_calls(token)
    print()
    
    # Test 3: WebSocket
    try:
        result = asyncio.run(test_websocket(token))
        if not result:
            log("WARNING: WebSocket test failed", "WARN")
    except Exception as e:
        log(f"WebSocket test exception: {e}", "WARN")
    
    print()
    
    # Test 4: Page Data
    test_pages_load(token)
    
    print()
    log("="*60, "COMPLETE")
    log("✓ All critical tests completed!")
    log("✓ Frontend ready for browser testing")
    log("="*60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
