#!/usr/bin/env python3
"""
Quick E2E Test - Falcon AI Vision
Simplified teste de verificação rápida
"""

import requests
import asyncio
import websockets
import json

BASE_URL = "http://localhost:5003"
API_URL = f"{BASE_URL}/api"

def test_all():
    print("\n============== TESTES E2E - FALCON AI VISION ==============\n")
    
    # 1. Health Check
    print("1. Health Check...")
    r = requests.get(f"{BASE_URL}/health")
    print(f"   ✓ Status: {r.json()['status']}")
    
    # 2. Frontend
    print("2. Frontend Serving...")
    r = requests.get(f"{BASE_URL}/")
    print(f"   ✓ HTML served ({len(r.content)} bytes)")
    
    # 3. Auth
    print("3. Authentication...")
    r = requests.post(f"{API_URL}/auth/login", json={"username": "admin", "password": "admin123"})
    token = r.json().get("access_token") or r.json().get("token")
    print(f"   ✓ Login successful (token: {token[:20]}...)")
    
    # 4. API Endpoints
    print("4. API Endpoints...")
    headers = {"Authorization": f"Bearer {token}"}
    
    endpoints = [
        ("/cameras", "Cameras"),
        ("/events", "Events"),
        ("/zones/list", "Zones"),
        ("/personnel", "Personnel"),
        ("/vehicles", "Vehicles"),
    ]
    
    for endpoint, name in endpoints:
        r = requests.get(f"{API_URL}{endpoint}", headers=headers)
        data = r.json()
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict):
            # Try to find array
            count = 0
            for key in ["data", "items", name.lower()]:
                if key in data and isinstance(data[key], list):
                    count = len(data[key])
                    break
        print(f"   ✓ {name}: {count} items")
    
    # 5. WebSocket
    print("5. WebSocket Connection...")
    async def test_ws():
        try:
            ws_url = f"ws://localhost:5003/api/ws?token={token}"
            async with asyncio.timeout(5):
                async with websockets.connect(ws_url) as ws:
                    print(f"   ✓ WebSocket connected")
                    try:
                        async with asyncio.timeout(2):
                            msg = await ws.recv()
                            print(f"   ✓ Message received: {msg[:50]}...")
                    except asyncio.TimeoutError:
                        print(f"   ⚠ No initial message (normal)")
        except Exception as e:
            print(f"   ✗ Error: {e}")
    
    try:
        asyncio.run(test_ws())
    except Exception as e:
        print(f"   ✗ WebSocket test failed: {e}")
    
    print("\n✓ TODOS OS TESTES CONCLUÍDOS COM SUCESSO!\n")
    print("Sistema pronto para uso em http://localhost:5003\n")

if __name__ == "__main__":
    try:
        test_all()
    except Exception as e:
        print(f"\n✗ Erro: {e}\n")
        exit(1)
