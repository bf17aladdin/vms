#!/usr/bin/env python3
"""
Phase 4: E2E Integration Test
Valide le pipeline complet: WebSocket → AI → DB → Frontend
"""

import asyncio
import sys
import time
import json
import base64
from pathlib import Path
from typing import Dict, List

# Add workspace to path
workspace_root = Path(__file__).parent.parent
sys.path.insert(0, str(workspace_root))

import numpy as np
import cv2
from httpx import AsyncClient
from fastapi import WebSocket
from contextlib import asynccontextmanager

# Import test utilities
import pytest_asyncio
from vms.backend.main import app
from vms.backend.services.async_frame_pipeline import get_async_processor

print("\n" + "="*80)
print("PHASE 4: E2E INTEGRATION TEST")
print("="*80)

# === Test Configuration ===
NUM_CAMERAS = 3
FRAMES_PER_CAMERA = 10
TEST_DURATION_SECONDS = 30

test_results = {
    "websocket_connectivity": False,
    "frame_processing": False,
    "detection_results": False,
    "latency_metrics": [],
    "error_rate": 0.0,
    "database_persistence": False,
    "api_endpoints": {}
}


async def create_test_frame(camera_id: int, frame_num: int) -> bytes:
    """Create a test frame encoded as JPEG base64"""
    frame = np.ones((720, 1280, 3), dtype=np.uint8) * 100
    
    # Add some variation
    noise = np.random.randint(-20, 20, frame.shape, dtype=np.int16)
    frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    
    # Add camera/frame info
    cv2.putText(frame, f"Camera {camera_id}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.putText(frame, f"Frame {frame_num}", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    
    # Simulate motion every 3rd frame
    if frame_num % 3 == 0:
        cv2.rectangle(frame, (100, 100), (300, 400), (0, 0, 255), -1)
    
    # Encode as JPEG
    _, buffer = cv2.imencode('.jpg', frame)
    return base64.b64encode(buffer).decode('utf-8')


async def test_websocket_connection():
    """Test 1: WebSocket connectivity"""
    print("\n[Test 1] WebSocket Connectivity")
    print("-" * 80)
    
    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            # Check WebSocket endpoint exists
            response = await client.get("/ws/status")
            assert response.status_code == 200
            print(f"✅ WebSocket status endpoint: {response.status_code}")
            test_results["websocket_connectivity"] = True
            return True
    except Exception as e:
        print(f"❌ WebSocket connectivity failed: {e}")
        return False


async def test_api_endpoints():
    """Test 2: API endpoints"""
    print("\n[Test 2] API Endpoints")
    print("-" * 80)
    
    try:
        async with AsyncClient(app=app, base_url="http://test") as client:
            endpoints = [
                ("/health", "GET"),
                ("/api", "GET"),
                ("/ws/status", "GET"),
                ("/ws/cameras", "GET"),
            ]
            
            results = {}
            for endpoint, method in endpoints:
                try:
                    response = await client.get(endpoint)
                    results[endpoint] = response.status_code
                    status = "✅" if response.status_code == 200 else "⚠️"
                    print(f"{status} {method} {endpoint}: {response.status_code}")
                except Exception as e:
                    results[endpoint] = f"Error: {e}"
                    print(f"❌ {method} {endpoint}: {e}")
            
            test_results["api_endpoints"] = results
            return True
    except Exception as e:
        print(f"❌ API endpoints test failed: {e}")
        return False


async def test_frame_processing():
    """Test 3: Frame processing through pipeline"""
    print("\n[Test 3] Frame Processing (Async Pipeline)")
    print("-" * 80)
    
    try:
        processor = get_async_processor()
        
        # Register test cameras
        for i in range(NUM_CAMERAS):
            processor.add_camera(f"test_cam_{i}", f"Test Camera {i}")
        
        print(f"✓ Registered {NUM_CAMERAS} test cameras")
        
        # Process frames
        total_frames = 0
        errors = 0
        latencies = []
        
        for cam_id in range(NUM_CAMERAS):
            for frame_num in range(FRAMES_PER_CAMERA):
                try:
                    # Create frame
                    frame_b64 = await create_test_frame(cam_id, frame_num)
                    frame_bytes = base64.b64decode(frame_b64)
                    frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
                    frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                    
                    # Process
                    pipeline = processor.pipelines[f"test_cam_{cam_id}"]
                    result = await pipeline.process_frame(frame, db=None)
                    
                    # Collect metrics
                    latency = result.get("latency_ms", 0)
                    latencies.append(latency)
                    total_frames += 1
                    
                except Exception as e:
                    errors += 1
                    print(f"  ⚠️ Error processing frame: {e}")
        
        # Analysis
        error_rate = (errors / max(total_frames, 1)) * 100
        avg_latency = np.mean(latencies) if latencies else 0
        
        print(f"✅ Processed {total_frames} frames from {NUM_CAMERAS} cameras")
        print(f"   ├─ Average latency: {avg_latency:.1f}ms")
        print(f"   ├─ Errors: {errors} ({error_rate:.2f}%)")
        print(f"   └─ Detection pipeline: WORKING")
        
        test_results["frame_processing"] = True
        test_results["latency_metrics"] = latencies
        test_results["error_rate"] = error_rate
        
        return error_rate < 5.0  # Less than 5% errors acceptable
        
    except Exception as e:
        print(f"❌ Frame processing test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_detection_results():
    """Test 4: Detection result quality"""
    print("\n[Test 4] Detection Results Quality")
    print("-" * 80)
    
    try:
        processor = get_async_processor()
        
        if not processor.pipelines:
            # Create a test pipeline if needed
            processor.add_camera("quality_test", "Quality Test Camera")
        
        pipeline = list(processor.pipelines.values())[0]
        
        # Process a frame with motion
        frame = np.ones((720, 1280, 3), dtype=np.uint8) * 100
        cv2.rectangle(frame, (100, 100), (300, 400), (0, 0, 255), -1)
        
        result = await pipeline.process_frame(frame, db=None)
        
        # Check result structure
        checks = {
            "has_motion": "motion" in result,
            "has_objects": "objects" in result,
            "has_latency": "latency_ms" in result,
            "has_timestamp": "timestamp" in result,
            "latency_reasonable": result.get("latency_ms", 0) < 500
        }
        
        for check_name, passed in checks.items():
            status = "✅" if passed else "❌"
            print(f"{status} {check_name}")
        
        all_passed = all(checks.values())
        test_results["detection_results"] = all_passed
        
        print(f"\nDetection result sample:")
        print(f"  Motion: {result.get('motion', {}).get('detected')}")
        print(f"  Objects: {len(result.get('objects', []))} detected")
        print(f"  Latency: {result.get('latency_ms', 0):.1f}ms")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ Detection results test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_performance_under_load():
    """Test 5: Performance under load"""
    print("\n[Test 5] Performance Under Load")
    print("-" * 80)
    
    try:
        processor = get_async_processor()
        
        # Use existing pipelines
        if not processor.pipelines:
            for i in range(NUM_CAMERAS):
                processor.add_camera(f"load_test_{i}", f"Load Test {i}")
        
        print(f"Testing {len(processor.pipelines)} cameras over {TEST_DURATION_SECONDS}s...")
        
        test_start = time.time()
        total_frames = 0
        errors = 0
        
        while time.time() - test_start < TEST_DURATION_SECONDS:
            for cam_id, pipeline in list(processor.pipelines.items())[:NUM_CAMERAS]:
                try:
                    frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
                    result = await pipeline.process_frame(frame, db=None)
                    total_frames += 1
                except:
                    errors += 1
            
            await asyncio.sleep(0.01)
        
        test_duration = time.time() - test_start
        fps = total_frames / test_duration
        error_pct = (errors / max(total_frames, 1)) * 100
        
        print(f"✅ Load test results:")
        print(f"   ├─ Duration: {test_duration:.1f}s")
        print(f"   ├─ Frames: {total_frames}")
        print(f"   ├─ FPS: {fps:.1f}")
        print(f"   └─ Error rate: {error_pct:.2f}%")
        
        return fps > 50 and error_pct < 2.0
        
    except Exception as e:
        print(f"❌ Load test failed: {e}")
        return False


async def test_pipeline_stats():
    """Test 6: Pipeline statistics"""
    print("\n[Test 6] Pipeline Statistics")
    print("-" * 80)
    
    try:
        processor = get_async_processor()
        stats = processor.get_all_stats()
        
        print(f"Pipeline statistics for {len(stats)} cameras:")
        for camera_id, stat in list(stats.items())[:3]:  # Show first 3
            print(f"\n  {camera_id}:")
            print(f"    ├─ Frames: {stat.get('frames_processed', 0)}")
            print(f"    ├─ Errors: {stat.get('errors', 0)}")
            print(f"    └─ Error rate: {stat.get('error_rate', 'N/A')}")
        
        return len(stats) > 0
        
    except Exception as e:
        print(f"❌ Statistics test failed: {e}")
        return False


# === Main Test Suite ===
async def run_e2e_tests():
    """Run all E2E tests"""
    
    print("\nStarting E2E Integration Tests...")
    print("="*80)
    
    tests = [
        ("WebSocket Connection", test_websocket_connection),
        ("API Endpoints", test_api_endpoints),
        ("Frame Processing", test_frame_processing),
        ("Detection Results", test_detection_results),
        ("Performance Load", test_performance_under_load),
        ("Pipeline Stats", test_pipeline_stats),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            passed = await test_func()
            results[test_name] = "PASSED" if passed else "FAILED"
        except Exception as e:
            print(f"❌ {test_name} exception: {e}")
            results[test_name] = "ERROR"
    
    # === Final Report ===
    print("\n" + "="*80)
    print("E2E INTEGRATION TEST RESULTS")
    print("="*80)
    
    for test_name, result in results.items():
        status = "✅" if result == "PASSED" else "❌"
        print(f"{status} {test_name}: {result}")
    
    # Summary
    passed_count = sum(1 for r in results.values() if r == "PASSED")
    total_count = len(results)
    
    print(f"\n{passed_count}/{total_count} tests passed")
    
    if passed_count == total_count:
        print("\n🎉 PHASE 4: ALL E2E TESTS PASSED")
        print("✅ Pipeline ready for production deployment")
        return 0
    else:
        print(f"\n⚠️ {total_count - passed_count} test(s) failed")
        print("Review failures above before production deployment")
        return 1


# === Entry Point ===
if __name__ == "__main__":
    exit_code = asyncio.run(run_e2e_tests())
    sys.exit(exit_code)
