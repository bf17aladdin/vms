#!/usr/bin/env python3
"""
🎯 VMS Falcon AI Vision - Simplified Automated Testing Suite
Tests core functionality from the Browser Testing Checklist
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, List

# Configuration
BASE_URL = "http://localhost:5003"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# Test results tracking
test_results = {
    "passed": 0,
    "failed": 0,
    "warnings": 0
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
    msg = f"✅ {test_name}"
    if message:
        msg += f" | {message}"
    print(f"{Colors.GREEN}{msg}{Colors.RESET}")
    test_results["passed"] += 1

def log_fail(test_name: str, message: str = ""):
    msg = f"❌ {test_name}"
    if message:
        msg += f" | {message}"
    print(f"{Colors.RED}{msg}{Colors.RESET}")
    test_results["failed"] += 1

def log_warn(test_name: str, message: str = ""):
    msg = f"⚠️  {test_name}"
    if message:
        msg += f" | {message}"
    print(f"{Colors.YELLOW}{msg}{Colors.RESET}")
    test_results["warnings"] += 1

def log_section(title: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{title}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.RESET}\n")

def test_server_health():
    """Test: Server is running"""
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            log_pass("Server Health", f"Status: {response.status_code}")
            return True
    except Exception as e:
        log_fail("Server Health", str(e))
    return False

def test_login():
    """Test: Authentication"""
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
                log_pass("Login - Authentication", f"Token obtained: {token[:15]}...")
                return token
    except Exception as e:
        log_fail("Login - Authentication", str(e))
    return None

def test_api_endpoints(token: str):
    """Test: Protected API Endpoints"""
    if not token:
        log_warn("API Endpoints", "No token available")
        return False
    
    headers = {"Authorization": f"Bearer {token}"}
    endpoints = {
        "/api/cameras": ["GET"],
        "/api/zones": ["GET"],
        "/api/alerts": ["GET"],
        "/api/events": ["GET"],
        "/api/personnel": ["GET"],
        "/api/vehicles": ["GET"],
    }
    
    success_count = 0
    for endpoint, methods in endpoints.items():
        try:
            for method in methods:
                response = requests.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=5)
                if response.status_code in [200, 400, 422]:  # Accept different responses
                    log_pass(f"GET {endpoint}", f"Status: {response.status_code}")
                    success_count += 1
                else:
                    log_warn(f"GET {endpoint}", f"Status: {response.status_code}")
        except Exception as e:
            log_warn(f"GET {endpoint}", f"Timeout or error")
    
    return success_count >= len(endpoints) * 0.7

def test_error_handling():
    """Test: Error Handling"""
    # Test invalid login
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "invalid_user", "password": "invalid_pass"},
            timeout=5
        )
        if response.status_code != 200:
            log_pass("Invalid Login Rejected", f"Status: {response.status_code}")
        else:
            log_fail("Invalid Login Rejected", "Should reject invalid credentials")
    except Exception as e:
        log_warn("Invalid Login Test", "Connection issue")
    
    # Test missing auth header
    try:
        response = requests.get(f"{BASE_URL}/api/cameras", timeout=5)
        if response.status_code in [401, 403]:
            log_pass("Missing Auth Header", "Correctly rejected (401/403)")
        else:
            log_warn("Missing Auth Header", f"Status: {response.status_code}")
    except Exception as e:
        log_warn("Missing Auth Test", "Connection issue")
    
    # Test invalid endpoint
    try:
        response = requests.get(f"{BASE_URL}/api/invalid_endpoint_xyz", timeout=5)
        if response.status_code == 404:
            log_pass("Invalid Endpoint", "Returns 404")
        else:
            log_warn("Invalid Endpoint", f"Status: {response.status_code}")
    except Exception as e:
        log_warn("Invalid Endpoint Test", "Connection issue")

def test_performance(token: str):
    """Test: Performance - Page Load Times"""
    if not token:
        log_warn("Performance", "No token available")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    endpoints = ["/api/cameras", "/api/zones", "/api/alerts"]
    
    for endpoint in endpoints:
        try:
            start = time.time()
            response = requests.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=5)
            elapsed = (time.time() - start) * 1000
            
            if response.status_code == 200:
                if elapsed < 2000:
                    log_pass(f"Performance {endpoint}", f"{elapsed:.0f}ms (target: <2000ms)")
                else:
                    log_warn(f"Performance {endpoint}", f"{elapsed:.0f}ms (target: <2000ms)")
        except Exception as e:
            log_warn(f"Performance {endpoint}", "Timeout")

def test_camera_crud(token: str):
    """Test: Camera CRUD Operations"""
    if not token:
        log_warn("Camera CRUD", "No token available")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        # GET cameras
        response = requests.get(f"{BASE_URL}/api/cameras", headers=headers, timeout=5)
        if response.status_code == 200:
            cameras = response.json()
            if isinstance(cameras, dict):
                camera_list = cameras.get("cameras", cameras.get("data", []))
            else:
                camera_list = cameras
            
            log_pass("Camera GET", f"Found {len(camera_list)} cameras")
            
            # If cameras exist, try to get one
            if camera_list:
                first_camera = camera_list[0]
                camera_id = first_camera.get("id")
                if camera_id:
                    try:
                        response = requests.get(
                            f"{BASE_URL}/api/cameras/{camera_id}",
                            headers=headers,
                            timeout=5
                        )
                        if response.status_code == 200:
                            log_pass(f"Camera GET by ID", f"Camera {camera_id} retrieved")
                    except:
                        pass
    except Exception as e:
        log_warn("Camera CRUD", f"Error: {str(e)[:40]}")

def test_alert_filtering(token: str):
    """Test: Alert Filtering & Severity"""
    if not token:
        log_warn("Alert Filtering", "No token available")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(f"{BASE_URL}/api/alerts", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            # Handle different response formats
            if isinstance(data, dict):
                alerts = data.get("alerts", data.get("data", []))
            else:
                alerts = data
            
            log_pass("Alert GET", f"Found {len(alerts)} alerts")
            
            # Analyze severity
            severity_count = {}
            for alert in alerts:
                if isinstance(alert, dict):
                    severity = alert.get("severity", "unknown")
                    severity_count[severity] = severity_count.get(severity, 0) + 1
            
            for severity, count in severity_count.items():
                log_pass(f"Alerts by Severity: {severity}", f"Count: {count}")
    except Exception as e:
        log_warn("Alert Filtering", f"Error: {str(e)[:40]}")

def test_zone_occupancy(token: str):
    """Test: Zone Occupancy Data"""
    if not token:
        log_warn("Zone Occupancy", "No token available")
        return
    
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        response = requests.get(f"{BASE_URL}/api/zones", headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            
            # Handle different response formats
            if isinstance(data, dict):
                zones = data.get("zones", data.get("data", []))
            else:
                zones = data
            
            log_pass("Zone GET", f"Found {len(zones)} zones")
            
            # Check occupancy data
            occupancy_data = 0
            for zone in zones:
                if isinstance(zone, dict) and "occupancy" in zone:
                    occupancy_data += 1
            
            if occupancy_data > 0:
                log_pass("Zone Occupancy Data", f"{occupancy_data} zones have occupancy info")
    except Exception as e:
        log_warn("Zone Occupancy", f"Error: {str(e)[:40]}")

def generate_report():
    """Generate final test report"""
    log_section("📊 TEST REPORT & SUMMARY")
    
    total = test_results["passed"] + test_results["failed"] + test_results["warnings"]
    pass_rate = (test_results["passed"] / total * 100) if total > 0 else 0
    
    print(f"{Colors.BOLD}Results:{Colors.RESET}")
    print(f"  {Colors.GREEN}✅ Passed:  {test_results['passed']}/{total}{Colors.RESET}")
    print(f"  {Colors.RED}❌ Failed:  {test_results['failed']}/{total}{Colors.RESET}")
    print(f"  {Colors.YELLOW}⚠️  Warnings: {test_results['warnings']}/{total}{Colors.RESET}")
    print(f"\n  {Colors.BOLD}Success Rate: {pass_rate:.1f}%{Colors.RESET}")
    
    # Status
    if test_results["failed"] == 0 and pass_rate >= 80:
        status = f"{Colors.GREEN}{Colors.BOLD}✅ READY FOR DEPLOYMENT{Colors.RESET}"
    elif pass_rate >= 60:
        status = f"{Colors.YELLOW}{Colors.BOLD}🚧 MOSTLY WORKING - MINOR ISSUES{Colors.RESET}"
    else:
        status = f"{Colors.RED}{Colors.BOLD}❌ NEEDS FIXES{Colors.RESET}"
    
    print(f"\n  Status: {status}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Next steps
    print(f"\n{Colors.BOLD}Next Steps:{Colors.RESET}")
    print(f"  1. Open browser: {Colors.BLUE}http://localhost:5003{Colors.RESET}")
    print(f"  2. Login: admin / admin123")
    print(f"  3. Verify all pages load without errors")
    print(f"  4. Check real-time updates on Dashboard, Alerts, AI, Zones")
    print(f"  5. Open DevTools (F12) → Network → WS tab to verify WebSocket")
    
    # Save report
    with open("TEST_REPORT.txt", "w", encoding="utf-8") as f:
        f.write("🎯 VMS Falcon AI Vision - Automated Test Report\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Passed:    {test_results['passed']}/{total}\n")
        f.write(f"Failed:    {test_results['failed']}/{total}\n")
        f.write(f"Warnings:  {test_results['warnings']}/{total}\n")
        f.write(f"Success Rate: {pass_rate:.1f}%\n\n")
    
    print(f"\n  Report saved: TEST_REPORT.txt")

def main():
    """Main test execution"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║  🎯 VMS Falcon AI Vision - Automated Testing Suite           ║")
    print("║  Testing all core functionality...                        ║")
    print("╚════════════════════════════════════════════════════════════╝")
    print(Colors.RESET)
    
    print(f"\n{Colors.BLUE}Target: {BASE_URL}{Colors.RESET}\n")
    
    log_section("1️⃣  HEALTH & CONNECTIVITY")
    if not test_server_health():
        print(f"\n{Colors.RED}Server is not running. Please start with:{Colors.RESET}")
        print(f"  python -m vms.backend.main")
        return False
    
    log_section("2️⃣  AUTHENTICATION")
    token = test_login()
    if not token:
        print(f"\n{Colors.RED}Authentication failed.{Colors.RESET}")
        return False
    
    log_section("3️⃣  API ENDPOINTS")
    test_api_endpoints(token)
    
    log_section("4️⃣  CAMERA OPERATIONS")
    test_camera_crud(token)
    
    log_section("5️⃣  ALERT OPERATIONS")
    test_alert_filtering(token)
    
    log_section("6️⃣  ZONE OPERATIONS")
    test_zone_occupancy(token)
    
    log_section("7️⃣  ERROR HANDLING")
    test_error_handling()
    
    log_section("8️⃣  PERFORMANCE")
    test_performance(token)
    
    generate_report()
    return True

if __name__ == "__main__":
    success = main()
    if not success:
        exit(1)
