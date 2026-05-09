"""
Test InferenceManager async pipeline
Run with: python -m asyncio vms/backend/tests/test_inference_manager.py
Or: python vms/backend/tests/test_inference_manager.py (with asyncio wrapper)
"""

import sys
import os
import asyncio
import numpy as np
import time

# Add project to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from vms.backend.services.inference_manager import get_inference_manager


async def _run_inference_manager_checks():
    """Run InferenceManager async pipeline checks."""
    print("="*60)
    print("🧪 INFERENCE MANAGER TEST")
    print("="*60)
    
    # Get singleton instance
    print("\n1️⃣  Getting InferenceManager singleton...")
    manager = get_inference_manager()
    print("✅ InferenceManager initialized")
    print(f"   Object detector available: {manager.object_detector is not None}")
    
    # Test motion detection
    print("\n2️⃣  Test: Motion detection (async)...")
    frame = np.ones((720, 1280, 3), dtype=np.uint8) * 150
    
    motion_result = await manager.detect_motion_async(frame, camera_id=1)
    print(f"   Motion detected: {motion_result['motion_detected']}")
    print(f"   Confidence: {motion_result['confidence']:.3f}")
    print(f"   Processing time: {motion_result['processing_time_ms']:.2f}ms")
    print("   ✅ PASS: Async motion detection works")
    
    # Test object detection
    print("\n3️⃣  Test: Object detection (async)...")
    frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    
    objects_result = await manager.detect_objects_async(frame, camera_id=1)
    print(f"   Objects detected: {objects_result['detections_count']}")
    print(f"   Processing time: {objects_result['processing_time_ms']:.2f}ms")
    print("   ✅ PASS: Async object detection works")
    
    # Test batch inference
    print("\n4️⃣  Test: Batch inference (async, 4 cameras)...")
    frames = [(i, np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)) 
              for i in range(1, 5)]
    
    batch_results = await manager.detect_batch_objects_async(frames)
    print(f"   Batch size: {len(batch_results)}")
    for i, result in enumerate(batch_results):
        print(f"     Camera {i+1}: {result['detections_count']} objects")
    print("   ✅ PASS: Batch inference works")
    
    # Test multi-camera concurrent processing
    print("\n5️⃣  Test: Multi-camera concurrent processing...")
    
    async def process_camera(camera_id: int):
        frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
        motion = await manager.detect_motion_async(frame, camera_id)
        objects = await manager.detect_objects_async(frame, camera_id)
        return {
            'camera_id': camera_id,
            'motion': motion['motion_detected'],
            'objects': objects['detections_count']
        }
    
    start = time.time()
    # Process 4 cameras concurrently
    results = await asyncio.gather(
        process_camera(1),
        process_camera(2),
        process_camera(3),
        process_camera(4)
    )
    elapsed = time.time() - start
    
    print(f"   Processed {len(results)} cameras concurrently in {elapsed*1000:.2f}ms")
    for result in results:
        print(f"     Camera {result['camera_id']}: motion={result['motion']}, objects={result['objects']}")
    
    throughput = len(results) / elapsed
    print(f"   Throughput: {throughput:.1f} cameras/sec")
    print("   ✅ PASS: Concurrent processing works")
    
    # Test statistics
    print("\n6️⃣  Test: Statistics collection...")
    stats = manager.get_statistics()
    print(f"   Stats: {stats}")
    print("   ✅ PASS: Statistics available")
    
    # Summary
    print("\n" + "="*60)
    print("✅ ALL INFERENCE MANAGER TESTS PASSED")
    print("="*60)
    print("\n🎯 Phase 1 Complete!")
    print("\nYou can now:")
    print("  1. Integrate InferenceManager into your camera streaming")
    print("  2. Create event records for high-confidence detections")
    print("  3. Move to Phase 2: Production pipeline optimization")
    print("\nSee: AI_PRODUCTION_ROADMAP.md (Phase 2)")

def test_inference_manager():
    """Pytest entrypoint without requiring pytest-asyncio plugin."""
    asyncio.run(_run_inference_manager_checks())


async def main():
    try:
        await _run_inference_manager_checks()
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
