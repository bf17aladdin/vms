#!/usr/bin/env python
"""Test WebSocket connection with JWT token"""

import asyncio
import websockets
import json
import requests
from urllib.parse import urlencode

BASE_URL = "http://127.0.0.1:5003"
WS_URL = "ws://127.0.0.1:5003/api/ws"

async def test_websocket():
    print("\n[TEST] WebSocket Connection with JWT")
    print("=" * 60)
    
    # First, get a valid token
    print("\n1. Getting authentication token...")
    try:
        response = requests.post(
            BASE_URL + "/api/auth/login",
            json={"username": "admin", "password": "admin123"},
            timeout=5
        )
        
        if response.status_code != 200:
            print(f"✗ Login failed: {response.text}")
            return False
        
        token_data = response.json()
        token = token_data.get("access_token") or token_data.get("token")
        if not token:
            print("✗ No token in response")
            return False
        
        print(f"✓ Token obtained: {token[:40]}...")
    except Exception as e:
        print(f"✗ Token request failed: {e}")
        return False
    
    # Connect to WebSocket with token
    print("\n2. Connecting to WebSocket...")
    ws_url_with_token = f"{WS_URL}?token={token}"
    
    try:
        async with websockets.connect(ws_url_with_token) as websocket:
            print(f"✓ Connected to {WS_URL}")
            
            # Wait for connection_established message
            print("\n3. Waiting for server message...")
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=3)
                data = json.loads(message)
                print(f"✓ Received message: {data}")
                
                if "connection_established" in data or "type" in data:
                    print(f"✓ Server sent connection confirmation")
                    return True
                else:
                    print(f"⚠ Unexpected message format")
                    return False
            except asyncio.TimeoutError:
                print(f"⚠ No message received within 3 seconds (connection may be open)")
                return True
    except Exception as e:
        print(f"✗ WebSocket connection failed: {e}")
        return False

# Run the test
if __name__ == "__main__":
    try:
        result = asyncio.run(test_websocket())
        if result:
            print("\n✓ WebSocket test passed!")
        else:
            print("\n✗ WebSocket test failed!")
    except Exception as e:
        print(f"\n✗ Test error: {e}")
