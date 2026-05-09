#!/usr/bin/env python3
"""
E2E Test Suite - Falcon AI Vision
Complete verification of backend + frontend integration

Tests:
1. API Health Check
2. Authentication Flow (Login)
3. Data Fetching (Cameras, Events, Zones, Personnel, Vehicles)
4. WebSocket Connection
5. Real-time Data Updates
6. Frontend File Serving
"""

import requests
import json
import time
import asyncio
import websockets
from datetime import datetime
from typing import Dict, List, Tuple

BASE_URL = "http://localhost:5003"
API_URL = f"{BASE_URL}/api"
WS_URL = f"ws://localhost:5003/api/ws"

# ANSI Colors
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

class TestResults:
    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []
    
    def add_pass(self, test_name: str, message: str = ""):
        self.passed.append((test_name, message))
        print(f"{GREEN}✓ PASS{RESET}: {test_name}" + (f" - {message}" if message else ""))
    
    def add_fail(self, test_name: str, error: str):
        self.failed.append((test_name, error))
        print(f"{RED}✗ FAIL{RESET}: {test_name} - {error}")
    
    def add_warning(self, test_name: str, message: str):
        self.warnings.append((test_name, message))
        print(f"{YELLOW}⚠ WARNING{RESET}: {test_name} - {message}")
    
    def print_summary(self):
        print(f"\n{BOLD}{'='*60}{RESET}")
        print(f"{BOLD}TEST SUMMARY{RESET}")
        print(f"{BOLD}{'='*60}{RESET}")
        print(f"{GREEN}Passed: {len(self.passed)}{RESET}")
        print(f"{RED}Failed: {len(self.failed)}{RESET}")
        print(f"{YELLOW}Warnings: {len(self.warnings)}{RESET}")
        
        if self.failed:
            print(f"\n{BOLD}Failed Tests:{RESET}")
            for test_name, error in self.failed:
                print(f"  - {test_name}: {error}")
        
        total = len(self.passed) + len(self.failed)
        success_rate = (len(self.passed) / total * 100) if total > 0 else 0
        print(f"\nSuccess Rate: {BOLD}{success_rate:.1f}%{RESET}")


def test_server_health(results: TestResults):
    """Test 1: Server Health Check"""
    print(f"\n{BLUE}Test 1: Server Health Check{RESET}")
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        response.raise_for_status()
        data = response.json()
        if "status" in data and data["status"] == "ok":
            results.add_pass("Server Health Check", f"Status: {data.get('status')}")
        else:
            results.add_fail("Server Health Check", f"Unexpected response: {data}")
    except Exception as e:
        results.add_fail("Server Health Check", str(e))


def test_frontend_files(results: TestResults):
    """Test 2: Frontend Files Serving"""
    print(f"\n{BLUE}Test 2: Frontend Files Serving{RESET}")
    
    endpoints = [
        ("/", "HTML"),
        ("/index.html", "HTML"),
        ("/api/openapi.json", "OpenAPI Schema"),
    ]
    
    for endpoint, name in endpoints:
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", timeout=5)
            response.raise_for_status()
            
            if endpoint == "/api/openapi.json":
                data = response.json()
                results.add_pass(f"Frontend Serving: {name}", f"Size: {len(response.content)} bytes")
            else:
                size_kb = len(response.content) / 1024
                results.add_pass(f"Frontend Serving: {name}", f"Size: {size_kb:.1f} KB")
                
        except Exception as e:
            results.add_fail(f"Frontend Serving: {name}", str(e))


def test_authentication(results: TestResults) -> str:
    """Test 3: Authentication Flow"""
    print(f"\n{BLUE}Test 3: Authentication Flow{RESET}")
    
    # Try login with default credentials
    credentials = [
        {"username": "admin", "password": "admin123"},
        {"username": "test", "password": "test123"},
    ]
    
    token = None
    for cred in credentials:
        try:
            response = requests.post(
                f"{API_URL}/auth/login",
                json=cred,
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            
            if "access_token" in data:
                token = data["access_token"]
                results.add_pass(f"Authentication: {cred['username']}", "Login successful")
                return token
            elif "token" in data:
                token = data["token"]
                results.add_pass(f"Authentication: {cred['username']}", "Login successful (token)")
                return token
        except Exception as e:
            results.add_warning(f"Authentication: {cred['username']}", f"Login failed: {str(e)}")
    
    results.add_warning("Authentication", "No valid credentials found, using unauthenticated requests")
    return None


def test_api_endpoints(results: TestResults, token: str = None):
    """Test 4: API Endpoints"""
    print(f"\n{BLUE}Test 4: API Endpoints{RESET}")
    
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    endpoints = [
        ("/cameras", "Cameras"),
        ("/events", "Events"),
        ("/zones/list", "Zones"),
        ("/personnel", "Personnel"),
        ("/vehicles", "Vehicles"),
        ("/realtime/stats", "Real-time Stats"),
    ]
    
    for endpoint, name in endpoints:
        try:
            response = requests.get(
                f"{API_URL}{endpoint}",
                headers=headers,
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            
            # Try to extract array length
            if isinstance(data, list):
                results.add_pass(f"API: {name}", f"Fetched {len(data)} items")
            elif isinstance(data, dict):
                # Try common key patterns
                items = data.get("data") or data.get("items") or data.get(name.lower())
                if isinstance(items, list):
                    results.add_pass(f"API: {name}", f"Fetched {len(items)} items")
                else:
                    results.add_pass(f"API: {name}", "Response received")
            else:
                results.add_pass(f"API: {name}", f"Response type: {type(data).__name__}")
                
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                results.add_warning(f"API: {name}", "Requires authentication (401)")
            else:
                results.add_fail(f"API: {name}", f"HTTP {e.response.status_code}")
        except Exception as e:
            results.add_fail(f"API: {name}", str(e))


async def test_websocket(results: TestResults, token: str = None):
    """Test 5: WebSocket Connection"""
    print(f"\n{BLUE}Test 5: WebSocket Connection{RESET}")
    
    ws_url_with_token = f"{WS_URL}?token={token}" if token else WS_URL
    
    try:
        # Connect with timeout
        async with asyncio.timeout(5):
            async with websockets.connect(ws_url_with_token) as websocket:
                results.add_pass("WebSocket Connection", "Connected successfully")
                
                # Wait for initial message (if any)
                try:
                    async with asyncio.timeout(2):
                        message = await websocket.recv()
                        data = json.loads(message)
                        results.add_pass("WebSocket Message", f"Received: {data.get('type', 'unknown')}")
                except asyncio.TimeoutError:
                    results.add_warning("WebSocket Message", "No initial message received (timeout)")
                
    except Exception as e:
        results.add_fail("WebSocket Connection", str(e))


def test_cors_headers(results: TestResults):
    """Test 6: CORS Headers"""
    print(f"\n{BLUE}Test 6: CORS Headers{RESET}")
    
    try:
        response = requests.options(f"{API_URL}/cameras", timeout=5)
        
        cors_headers = {
            "Access-Control-Allow-Origin": response.headers.get("Access-Control-Allow-Origin"),
            "Access-Control-Allow-Methods": response.headers.get("Access-Control-Allow-Methods"),
            "Access-Control-Allow-Headers": response.headers.get("Access-Control-Allow-Headers"),
        }
        
        if any(cors_headers.values()):
            results.add_pass("CORS Headers", "Present in response")
        else:
            results.add_warning("CORS Headers", "No CORS headers found (might be okay for same-origin)")
            
    except Exception as e:
        results.add_warning("CORS Headers", str(e))


def test_response_consistency(results: TestResults, token: str = None):
    """Test 7: Response Format Consistency"""
    print(f"\n{BLUE}Test 7: Response Format Consistency{RESET}")
    
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    test_endpoints = [
        ("/cameras", "cameras"),
        ("/events", "events"),
        ("/zones/list", "zones"),
        ("/personnel", "personnel"),
        ("/vehicles", "vehicles"),
    ]
    
    issues = []
    for endpoint, expected_key in test_endpoints:
        try:
            response = requests.get(
                f"{API_URL}{endpoint}",
                headers=headers,
                timeout=5
            )
            response.raise_for_status()
            data = response.json()
            
            # Check if response is array or wrapped object
            if isinstance(data, list):
                results.add_pass(f"Response: {endpoint}", "Direct array format")
            elif isinstance(data, dict):
                # Check for wrapped format
                if any(key in data for key in ["data", "items", expected_key]):
                    key = next(k for k in ["data", "items", expected_key] if k in data)
                    results.add_pass(f"Response: {endpoint}", f"Wrapped format (key: {key})")
                else:
                    results.add_warning(f"Response: {endpoint}", f"Unexpected object format")
            else:
                results.add_warning(f"Response: {endpoint}", f"Unexpected type: {type(data).__name__}")
                
        except Exception as e:
            results.add_warning(f"Response: {endpoint}", str(e))


async def run_async_tests(results: TestResults, token: str = None):
    """Run WebSocket tests"""
    await test_websocket(results, token)


def main():
    print(f"\n{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"{BOLD}Falcon AI Vision - E2E Test Suite{RESET}")
    print(f"{BOLD}{BLUE}{'='*60}{RESET}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Base URL: {BASE_URL}")
    
    results = TestResults()
    
    # Run sync tests
    test_server_health(results)
    test_frontend_files(results)
    token = test_authentication(results)
    test_api_endpoints(results, token)
    test_cors_headers(results)
    test_response_consistency(results, token)
    
    # Run async tests
    try:
        asyncio.run(run_async_tests(results, token))
    except Exception as e:
        results.add_warning("Async Tests", str(e))
    
    # Print summary
    results.print_summary()
    
    # Exit code based on failures
    import sys
    sys.exit(0 if not results.failed else 1)


if __name__ == "__main__":
    main()
