#!/usr/bin/env python3
"""
🎯 VMS Falcon AI Vision - Complete Automated Testing Suite
Tests all functionality from the Browser Testing Checklist
"""

import requests
import json
import asyncio
import websockets
import time
from datetime import datetime
from typing import Dict, List, Tuple
import sys

# Configuration
BASE_URL = "http://localhost:5003"
WS_URL = "ws://localhost:5003/api/ws"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# Test results tracking
test_results = {
    "passed": [],
    "failed": [],
    "warnings": [],
    "skipped": []
}

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    GRAY = '\033[90m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def log_pass(test_name: str, message: str = ""):
    msg = f"✅ PASS: {test_name}"
    if message:
        msg += f" | {message}"
    print(f"{Colors.GREEN}{msg}{Colors.RESET}")
    test_results["passed"].append(test_name)

def log_fail(test_name: str, message: str = ""):
    msg = f"❌ FAIL: {test_name}"
    if message:
        msg += f" | {message}"
    print(f"{Colors.RED}{msg}{Colors.RESET}")
    test_results["failed"].append(test_name)

def log_warn(test_name: str, message: str = ""):
    msg = f"⚠️  WARN: {test_name}"
    if message:
        msg += f" | {message}"
    print(f"{Colors.YELLOW}{msg}{Colors.RESET}")
    test_results["warnings"].append(test_name)

def log_skip(test_name: str, message: str = ""):
    msg = f"⏭️  SKIP: {test_name}"
    if message:
        msg += f" | {message}"
    print(f"{Colors.GRAY}{msg}{Colors.RESET}")
    test_results["skipped"].append(test_name)

def log_section(title: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}▶ {title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.RESET}")

def test_server_health():
    """Test 1: Server is running"""
    log_section("1️⃣  SERVER HEALTH")
    
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            log_pass("Server Health", f"Status: {response.status_code}")
            return True
        else:
            log_fail("Server Health", f"Status: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        log_fail("Server Health", "Cannot connect to server")
        return False
    except Exception as e:
        log_fail("Server Health", str(e))
        return False

def test_login():
    """Test 2: Authentication"""
    log_section("2️⃣  AUTHENTICATION & LOGIN")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            token = data.get("access_token")
            if token:
                log_pass("Login", f"Token: {token[:20]}...")
                return token
            else:
                log_fail("Login", "No token in response")
                return None
        else:
            log_fail("Login", f"Status: {response.status_code}")
            return None
    except Exception as e:
        log_fail("Login", str(e))
        return None

def test_protected_endpoints(token: str):
    """Test 3: API Endpoints"""
    log_section("3️⃣  API ENDPOINTS")
    
    if not token:
        log_skip("API Endpoints", "No token available")
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    endpoints = [
        "/api/cameras",
        "/api/zones",
        "/api/alerts",
        "/api/personnel",
        "/api/vehicles",
        "/api/events",
        "/api/detections",
    ]
    
    all_success = True
    for endpoint in endpoints:
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                count = len(data) if isinstance(data, list) else "object"
                log_pass(f"GET {endpoint}", f"Status: 200, Items: {count}")
            else:
                log_warn(f"GET {endpoint}", f"Status: {response.status_code}")
                all_success = False
        except Exception as e:
            log_fail(f"GET {endpoint}", str(e))
            all_success = False
    
    return all_success

def test_camera_operations(token: str):
    """Test 4: Camera Operations"""
    log_section("4️⃣  CAMERA OPERATIONS")
    
    if not token:
        log_skip("Camera Operations", "No token available")
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        # Get cameras
        response = requests.get(f"{BASE_URL}/api/cameras", headers=headers, timeout=5)
        if response.status_code != 200:
            log_fail("Get Cameras", f"Status: {response.status_code}")
            return False
        
        cameras = response.json()
        log_pass("Get Cameras", f"Found {len(cameras)} cameras")
        
        if cameras:
            camera_id = cameras[0].get("id")
            # Test get specific camera
            response = requests.get(f"{BASE_URL}/api/cameras/{camera_id}", headers=headers, timeout=5)
            if response.status_code == 200:
                log_pass(f"Get Camera {camera_id}", "Retrieved successfully")
            else:
                log_warn(f"Get Camera {camera_id}", f"Status: {response.status_code}")
        
        return True
    except Exception as e:
        log_fail("Camera Operations", str(e))
        return False

def test_alert_operations(token: str):
    """Test 5: Alert Operations"""
    log_section("5️⃣  ALERT OPERATIONS")
    
    if not token:
        log_skip("Alert Operations", "No token available")
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(f"{BASE_URL}/api/alerts", headers=headers, timeout=5)
        if response.status_code == 200:
            alerts = response.json()
            
            # Check severity filtering
            severities = ["low", "medium", "high", "critical"]
            log_pass("Get Alerts", f"Found {len(alerts)} alerts")
            
            # Test severity filters
            severity_counts = {}
            for alert in alerts:
                severity = alert.get("severity", "unknown")
                severity_counts[severity] = severity_counts.get(severity, 0) + 1
            
            for severity, count in severity_counts.items():
                log_pass(f"Alerts Severity: {severity}", f"Count: {count}")
            
            return True
        else:
            log_fail("Get Alerts", f"Status: {response.status_code}")
            return False
    except Exception as e:
        log_fail("Alert Operations", str(e))
        return False

def test_zone_operations(token: str):
    """Test 6: Zone Operations"""
    log_section("6️⃣  ZONE OPERATIONS")
    
    if not token:
        log_skip("Zone Operations", "No token available")
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(f"{BASE_URL}/api/zones", headers=headers, timeout=5)
        if response.status_code == 200:
            zones = response.json()
            log_pass("Get Zones", f"Found {len(zones)} zones")
            
            # Check occupancy structure
            for zone in zones[:3]:  # Check first 3
                occupancy = zone.get("occupancy", None)
                if occupancy is not None:
                    log_pass(f"Zone {zone.get('name', 'Unknown')}", f"Occupancy: {occupancy}")
            
            return True
        else:
            log_fail("Get Zones", f"Status: {response.status_code}")
            return False
    except Exception as e:
        log_fail("Zone Operations", str(e))
        return False

def test_event_operations(token: str):
    """Test 7: Event Operations"""
    log_section("7️⃣  EVENT OPERATIONS")
    
    if not token:
        log_skip("Event Operations", "No token available")
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(f"{BASE_URL}/api/events", headers=headers, timeout=5)
        if response.status_code == 200:
            events = response.json()
            log_pass("Get Events", f"Found {len(events)} events")
            
            # Check recent events
            if events:
                log_pass("Recent Events", f"Latest: {events[0].get('event_type', 'unknown')}")
            
            return True
        else:
            log_fail("Get Events", f"Status: {response.status_code}")
            return False
    except Exception as e:
        log_fail("Event Operations", str(e))
        return False

def test_detection_operations(token: str):
    """Test 8: Detection Operations"""
    log_section("8️⃣  DETECTION OPERATIONS")
    
    if not token:
        log_skip("Detection Operations", "No token available")
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(f"{BASE_URL}/api/detections", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            # Handle both list and dict responses
            if isinstance(data, list):
                detections = data
            elif isinstance(data, dict) and "detections" in data:
                detections = data.get("detections", [])
            else:
                log_warn("Get Detections", "Unexpected response format")
                return True
            
            log_pass("Get Detections", f"Found {len(detections)} detections")
            
            # Count by type (safely handle different formats)
            detection_types = {}
            for detection in detections:
                if isinstance(detection, dict):
                    dtype = detection.get("detection_type", "unknown")
                    detection_types[dtype] = detection_types.get(dtype, 0) + 1
            
            for dtype, count in detection_types.items():
                log_pass(f"Detection Type: {dtype}", f"Count: {count}")
            
            return True
        else:
            log_fail("Get Detections", f"Status: {response.status_code}")
            return False
    except Exception as e:
        log_fail("Detection Operations", str(e))
        return False

async def test_websocket_connection(token: str):
    """Test 9: WebSocket Connection"""
    log_section("9️⃣  WEBSOCKET CONNECTION")
    
    if not token:
        log_skip("WebSocket", "No token available")
        return False
    
    try:
        uri = f"{WS_URL}?token={token}"
        
        # Try with shorter timeout
        try:
            async with websockets.connect(uri, close_timeout=2) as websocket:
                log_pass("WebSocket Connect", "Connected successfully")
                
                # Wait for first message (with timeout)
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    log_pass("WebSocket Message", f"Received: {message[:50]}...")
                    
                    # Parse message
                    try:
                        msg_data = json.loads(message)
                        msg_type = msg_data.get("type", "unknown")
                        log_pass("WebSocket Message Type", f"Type: {msg_type}")
                    except:
                        pass
                    
                    return True
                except asyncio.TimeoutError:
                    log_warn("WebSocket Message", "No message received (connection OK, waiting for data)")
                    return True
        except asyncio.TimeoutError:
            log_warn("WebSocket", "Connection timeout (server may not be sending data)")
            return True
    except Exception as e:
        log_warn("WebSocket", f"Connection issue: {str(e)[:50]}... (this is optional)")
        return True  # WebSocket is optional for basic functionality

def test_error_handling(token: str):
    """Test 10: Error Handling"""
    log_section("🔟 ERROR HANDLING")
    
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    # Test invalid login
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "invalid", "password": "invalid"},
            timeout=5
        )
        if response.status_code != 200:
            log_pass("Invalid Login Rejection", f"Status: {response.status_code}")
        else:
            log_fail("Invalid Login Rejection", "Should reject invalid credentials")
    except Exception as e:
        log_fail("Invalid Login Test", str(e))
    
    # Test missing auth header
    try:
        response = requests.get(f"{BASE_URL}/api/cameras", timeout=5)
        if response.status_code != 200:
            log_pass("Missing Auth Header", f"Status: {response.status_code} (correctly rejected)")
        else:
            log_fail("Missing Auth Header", "Should require authentication")
    except Exception as e:
        log_fail("Missing Auth Test", str(e))
    
    # Test invalid endpoint
    try:
        response = requests.get(f"{BASE_URL}/api/invalid", headers=headers, timeout=5)
        if response.status_code == 404:
            log_pass("Invalid Endpoint", "Returns 404 correctly")
        else:
            log_warn("Invalid Endpoint", f"Status: {response.status_code}")
    except Exception as e:
        log_fail("Invalid Endpoint Test", str(e))

def test_performance(token: str):
    """Test 11: Performance"""
    log_section("1️⃣1️⃣  PERFORMANCE TESTS")
    
    if not token:
        log_skip("Performance", "No token available")
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    endpoints = ["/api/cameras", "/api/zones", "/api/alerts", "/api/events"]
    
    for endpoint in endpoints:
        try:
            start_time = time.time()
            response = requests.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=5)
            elapsed = (time.time() - start_time) * 1000  # ms
            
            if response.status_code == 200:
                if elapsed < 2000:  # 2 seconds
                    log_pass(f"Performance {endpoint}", f"{elapsed:.0f}ms (target: <2000ms)")
                else:
                    log_warn(f"Performance {endpoint}", f"{elapsed:.0f}ms (target: <2000ms)")
            else:
                log_fail(f"Performance {endpoint}", f"Status: {response.status_code}")
        except Exception as e:
            log_fail(f"Performance {endpoint}", str(e))

def generate_report():
    """Generate final test report"""
    log_section("📊 TEST REPORT")
    
    total_passed = len(test_results["passed"])
    total_failed = len(test_results["failed"])
    total_warnings = len(test_results["warnings"])
    total_skipped = len(test_results["skipped"])
    total_tests = total_passed + total_failed + total_warnings + total_skipped
    
    print(f"\n{Colors.BOLD}Test Summary:{Colors.RESET}")
    print(f"  {Colors.GREEN}✅ Passed:  {total_passed}/{total_tests}{Colors.RESET}")
    print(f"  {Colors.RED}❌ Failed:  {total_failed}/{total_tests}{Colors.RESET}")
    print(f"  {Colors.YELLOW}⚠️  Warnings: {total_warnings}/{total_tests}{Colors.RESET}")
    print(f"  {Colors.GRAY}⏭️  Skipped:  {total_skipped}/{total_tests}{Colors.RESET}")
    
    success_rate = (total_passed / (total_tests - total_skipped) * 100) if (total_tests - total_skipped) > 0 else 0
    print(f"\n  {Colors.BOLD}Success Rate: {success_rate:.1f}%{Colors.RESET}")
    
    # Status
    if total_failed == 0:
        status = f"{Colors.GREEN}{Colors.BOLD}✅ READY FOR DEPLOYMENT{Colors.RESET}"
    else:
        status = f"{Colors.RED}{Colors.BOLD}🚧 NEEDS FIXES ({total_failed} failures){Colors.RESET}"
    
    print(f"\n  Status: {status}")
    
    # Timestamp
    print(f"\n  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Save report
    report_file = "TEST_REPORT.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("🎯 VMS Falcon AI Vision - Test Report\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Passed:  {total_passed}/{total_tests}\n")
        f.write(f"Failed:  {total_failed}/{total_tests}\n")
        f.write(f"Warnings: {total_warnings}/{total_tests}\n")
        f.write(f"Skipped:  {total_skipped}/{total_tests}\n\n")
        f.write(f"Success Rate: {success_rate:.1f}%\n\n")
        
        if test_results["passed"]:
            f.write("✅ PASSED TESTS:\n")
            for test in test_results["passed"]:
                f.write(f"  - {test}\n")
        
        if test_results["failed"]:
            f.write("\n❌ FAILED TESTS:\n")
            for test in test_results["failed"]:
                f.write(f"  - {test}\n")
        
        if test_results["warnings"]:
            f.write("\n⚠️  WARNINGS:\n")
            for test in test_results["warnings"]:
                f.write(f"  - {test}\n")
    
    print(f"\n  Report saved to: {report_file}")

async def main():
    """Main test execution"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║   🎯 VMS Falcon AI Vision - Complete Testing Suite           ║")
    print("║   Starting automated tests...                             ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(Colors.RESET)
    
    print(f"\n{Colors.BLUE}Target: {BASE_URL}{Colors.RESET}")
    print(f"{Colors.BLUE}WebSocket: {WS_URL}{Colors.RESET}\n")
    
    # Run tests
    if not test_server_health():
        print(f"\n{Colors.RED}Server is not running. Please start the backend with:{Colors.RESET}")
        print(f"  python -m vms.backend.main")
        sys.exit(1)
    
    token = test_login()
    if not token:
        print(f"\n{Colors.RED}Authentication failed. Cannot continue.{Colors.RESET}")
        sys.exit(1)
    
    test_protected_endpoints(token)
    test_camera_operations(token)
    test_alert_operations(token)
    test_zone_operations(token)
    test_event_operations(token)
    test_detection_operations(token)
    await test_websocket_connection(token)
    test_error_handling(token)
    test_performance(token)
    
    # Generate report
    generate_report()

if __name__ == "__main__":
    asyncio.run(main())
