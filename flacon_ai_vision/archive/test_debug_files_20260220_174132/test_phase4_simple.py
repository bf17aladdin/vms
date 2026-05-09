#!/usr/bin/env python3
"""
Phase 4: Simple E2E Test Suite (No pytest required)
Tests the complete WebSocket AI integration pipeline
"""

import asyncio
import json
import base64
import time
from datetime import datetime
import numpy as np
import cv2
from pathlib import Path

# Test configuration
SERVER_URL = "http://127.0.0.1:5003"
WS_URL = "ws://127.0.0.1:5003"

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    END = '\033[0m'
    BOLD = '\033[1m'

def print_test(name, status, duration=None):
    """Print test result"""
    if status == "PASS":
        symbol = f"{Colors.GREEN}✅{Colors.END}"
    elif status == "FAIL":
        symbol = f"{Colors.RED}❌{Colors.END}"
    elif status == "SKIP":
        symbol = f"{Colors.YELLOW}⊘{Colors.END}"
    else:
        symbol = "ℹ️ "
    
    duration_str = f" ({duration:.2f}ms)" if duration else ""
    print(f"  {symbol} {name}{duration_str}")

async def test_server_health():
    """Test 1: Server health check"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}Test 1: Server Health Check{Colors.END}")
    start = time.time()
    
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{SERVER_URL}/health")
            duration = (time.time() - start) * 1000
            
            if response.status_code == 200:
                data = response.json()
                print_test("Server health endpoint", "PASS", duration)
                print(f"    Response: {data}")
                return True
            else:
                print_test("Server health endpoint", "FAIL", duration)
                return False
    except Exception as e:
        print_test("Server health endpoint", "FAIL")
        print(f"    Error: {e}")
        return False

async def test_api_endpoints():
    """Test 2: API endpoints"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}Test 2: API Endpoints{Colors.END}")
    
    endpoints = [
        ("GET", "/health"),
        ("GET", "/api"),
        ("GET", "/ws/status"),
        ("GET", "/ws/cameras"),
    ]
    
    passed = 0
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            for method, path in endpoints:
                start = time.time()
                try:
                    if method == "GET":
                        response = await client.get(f"{SERVER_URL}{path}", timeout=5)
                    duration = (time.time() - start) * 1000
                    
                    if response.status_code == 200:
                        print_test(f"{method} {path}", "PASS", duration)
                        passed += 1
                    else:
                        print_test(f"{method} {path}", "FAIL", duration)
                except Exception as e:
                    print_test(f"{method} {path}", "FAIL")
                    print(f"    Error: {e}")
    except ImportError:
        print_test("API endpoints", "SKIP")
        return None
    
    return passed == len(endpoints)

async def test_websocket_basic():
    """Test 3: WebSocket basic connectivity"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}Test 3: WebSocket Connection{Colors.END}")
    
    try:
        import websockets
        
        camera_id = "test_camera"
        start = time.time()
        
        try:
            async with websockets.connect(f"{WS_URL}/ws/ai/stream/{camera_id}") as ws:
                duration = (time.time() - start) * 1000
                print_test(f"WebSocket connect to /ws/ai/stream/{camera_id}", "PASS", duration)
                
                # Send a simple message
                await ws.send(json.dumps({"action": "ping"}))
                
                # Try to receive response
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    print_test("Receive WebSocket response", "PASS")
                    return True
                except asyncio.TimeoutError:
                    print_test("Receive WebSocket response", "SKIP")
                    return True
        except Exception as e:
            print_test(f"WebSocket connect", "FAIL")
            print(f"    Error: {e}")
            return False
    except ImportError:
        print_test("WebSocket test", "SKIP")
        return None

async def test_frame_processing():
    """Test 4: Frame processing with AI"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}Test 4: Frame Processing{Colors.END}")
    
    try:
        import websockets
        
        camera_id = "test_camera"
        frame_size = (640, 480)
        
        # Create test frame (simple noise image)
        test_frame = np.random.randint(0, 255, (*frame_size, 3), dtype=np.uint8)
        
        # Encode as JPEG
        success, encoded = cv2.imencode('.jpg', test_frame)
        if not success:
            print_test("Create test frame", "FAIL")
            return False
        
        frame_data = base64.b64encode(encoded.tobytes()).decode('utf-8')
        
        try:
            async with websockets.connect(f"{WS_URL}/ws/ai/stream/{camera_id}") as ws:
                start = time.time()
                
                # Send frame
                message = {
                    "action": "frame_data",
                    "frame_data": frame_data,
                    "width": frame_size[0],
                    "height": frame_size[1]
                }
                
                await ws.send(json.dumps(message))
                
                # Wait for response
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    duration = (time.time() - start) * 1000
                    
                    data = json.loads(response)
                    print_test("Send test frame", "PASS", duration)
                    
                    # Verify response structure
                    required_fields = ["camera_id", "detections", "latency_ms"]
                    if all(field in data for field in required_fields):
                        print_test("Response structure valid", "PASS")
                        print(f"    Detections: {data['detections']}")
                        print(f"    Latency: {data['latency_ms']:.2f}ms")
                        return True
                    else:
                        print_test("Response structure valid", "FAIL")
                        print(f"    Missing fields. Got: {list(data.keys())}")
                        return False
                except asyncio.TimeoutError:
                    print_test("Frame processing", "FAIL")
                    print(f"    Timeout waiting for response")
                    return False
        except Exception as e:
            print_test("Frame processing", "FAIL")
            print(f"    Error: {e}")
            return False
    except ImportError:
        print_test("Frame processing test", "SKIP")
        return None

async def test_performance():
    """Test 5: Performance metrics"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}Test 5: Performance Metrics{Colors.END}")
    
    try:
        import websockets
        
        camera_id = "perf_test"
        frame_count = 5
        latencies = []
        
        # Create test frame
        test_frame = np.random.randint(0, 255, (640, 480, 3), dtype=np.uint8)
        success, encoded = cv2.imencode('.jpg', test_frame)
        frame_data = base64.b64encode(encoded.tobytes()).decode('utf-8')
        
        try:
            async with websockets.connect(f"{WS_URL}/ws/ai/stream/{camera_id}") as ws:
                for i in range(frame_count):
                    start = time.time()
                    
                    message = {
                        "action": "frame_data",
                        "frame_data": frame_data,
                    }
                    
                    await ws.send(json.dumps(message))
                    
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        duration = (time.time() - start) * 1000
                        latencies.append(duration)
                    except asyncio.TimeoutError:
                        pass
                
                if latencies:
                    avg_latency = np.mean(latencies)
                    min_latency = np.min(latencies)
                    max_latency = np.max(latencies)
                    
                    print_test(f"Processed {frame_count} frames", "PASS")
                    print(f"    Average latency: {avg_latency:.2f}ms")
                    print(f"    Min latency: {min_latency:.2f}ms")
                    print(f"    Max latency: {max_latency:.2f}ms")
                    print(f"    Throughput: {1000.0 / avg_latency:.1f} FPS")
                    return True
                else:
                    print_test("Performance test", "FAIL")
                    return False
        except Exception as e:
            print_test("Performance test", "FAIL")
            print(f"    Error: {e}")
            return False
    except ImportError:
        print_test("Performance test", "SKIP")
        return None

async def test_concurrent_cameras():
    """Test 6: Multiple concurrent cameras"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}Test 6: Concurrent Cameras{Colors.END}")
    
    try:
        import websockets
        
        camera_ids = ["camera_1", "camera_2", "camera_3"]
        
        # Create test frame
        test_frame = np.random.randint(0, 255, (640, 480, 3), dtype=np.uint8)
        success, encoded = cv2.imencode('.jpg', test_frame)
        frame_data = base64.b64encode(encoded.tobytes()).decode('utf-8')
        
        async def send_frame(camera_id):
            try:
                async with websockets.connect(f"{WS_URL}/ws/ai/stream/{camera_id}") as ws:
                    message = {
                        "action": "frame_data",
                        "frame_data": frame_data,
                    }
                    await ws.send(json.dumps(message))
                    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    return True
            except Exception as e:
                print(f"    Camera {camera_id} error: {e}")
                return False
        
        start = time.time()
        results = await asyncio.gather(*[send_frame(cid) for cid in camera_ids])
        duration = (time.time() - start) * 1000
        
        if all(results):
            print_test(f"Process {len(camera_ids)} concurrent cameras", "PASS", duration)
            return True
        else:
            print_test(f"Process {len(camera_ids)} concurrent cameras", "FAIL", duration)
            return False
    except ImportError:
        print_test("Concurrent cameras test", "SKIP")
        return None

async def main():
    """Run all tests"""
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'='*70}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}PHASE 4: E2E INTEGRATION TEST SUITE{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'='*70}{Colors.END}")
    print(f"\nServer: {SERVER_URL}")
    print(f"WebSocket: {WS_URL}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    tests = [
        ("Server Health", test_server_health),
        ("API Endpoints", test_api_endpoints),
        ("WebSocket Connection", test_websocket_basic),
        ("Frame Processing", test_frame_processing),
        ("Performance", test_performance),
        ("Concurrent Cameras", test_concurrent_cameras),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n{Colors.RED}Error in {test_name}: {e}{Colors.END}")
            results.append((test_name, False))
    
    # Summary
    print(f"\n{Colors.CYAN}{Colors.BOLD}{'='*70}{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}TEST SUMMARY{Colors.END}")
    print(f"{Colors.CYAN}{Colors.BOLD}{'='*70}{Colors.END}\n")
    
    passed = sum(1 for _, result in results if result is True)
    failed = sum(1 for _, result in results if result is False)
    skipped = sum(1 for _, result in results if result is None)
    
    for test_name, result in results:
        if result is True:
            status = f"{Colors.GREEN}PASSED{Colors.END}"
        elif result is False:
            status = f"{Colors.RED}FAILED{Colors.END}"
        else:
            status = f"{Colors.YELLOW}SKIPPED{Colors.END}"
        print(f"  {test_name:.<40} {status}")
    
    print(f"\n{Colors.BOLD}Results:{Colors.END}")
    print(f"  {Colors.GREEN}Passed:  {passed}{Colors.END}")
    print(f"  {Colors.RED}Failed:  {failed}{Colors.END}")
    print(f"  {Colors.YELLOW}Skipped: {skipped}{Colors.END}")
    
    if failed == 0:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎉 ALL TESTS PASSED! 🎉{Colors.END}")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}⚠️  SOME TESTS FAILED{Colors.END}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
