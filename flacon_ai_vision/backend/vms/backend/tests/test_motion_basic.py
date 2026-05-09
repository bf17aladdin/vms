"""
Simple standalone test for motion detection
Run with: python vms/backend/tests/test_motion_basic.py
"""

import sys
import os
import cv2
import numpy as np

# Add project to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from vms.backend.ai.motion import MotionDetector

def test_motion_detection():
    """Test motion detector with simple synthetic frames"""
    print("="*60)
    print("🧪 MOTION DETECTION TEST")
    print("="*60)
    
    # Initialize detector
    print("\n1️⃣  Initializing MotionDetector...")
    detector = MotionDetector(sensitivity=50, min_area=500)
    print("✅ Detector initialized")
    
    # Test 1: Static frame (no motion)
    print("\n2️⃣  Test 1: Static frame (no motion expected)...")
    static_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 100
    result1 = detector.detect(static_frame)
    
    print(f"   Motion detected: {result1['motion_detected']}")
    print(f"   Confidence: {result1['confidence']:.3f}")
    print(f"   Coverage: {result1['coverage']:.2f}%")
    print(f"   Processing time: {result1['processing_time_ms']:.2f}ms")
    
    assert not result1['motion_detected'], "Static frame should not detect motion"
    print("   ✅ PASS: No false positives")
    
    # Test 2: Dynamic frame (motion expected)
    print("\n3️⃣  Test 2: Dynamic frame (motion expected)...")
    dynamic_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 200
    result2 = detector.detect(dynamic_frame)
    
    print(f"   Motion detected: {result2['motion_detected']}")
    print(f"   Confidence: {result2['confidence']:.3f}")
    print(f"   Coverage: {result2['coverage']:.2f}%")
    print(f"   Processing time: {result2['processing_time_ms']:.2f}ms")
    
    assert result2['motion_detected'], "Dynamic frame should detect motion"
    print("   ✅ PASS: Motion correctly detected")
    
    # Test 3: Multiple frames
    print("\n4️⃣  Test 3: Multiple frames (performance check)...")
    import time
    base_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 120
    frames = []
    for index in range(10):
        frame = base_frame.copy()
        offset = 40 + (index * 18)
        cv2.rectangle(frame, (offset, 180), (offset + 120, 320), (255, 255, 255), -1)
        frames.append(frame)
    
    start = time.time()
    results = [detector.detect(f) for f in frames]
    elapsed = time.time() - start
    
    avg_latency = np.mean([r['processing_time_ms'] for r in results])
    fps_achieved = len(frames) / elapsed
    
    print(f"   Frames processed: {len(frames)}")
    print(f"   Total time: {elapsed*1000:.2f}ms")
    print(f"   Average latency: {avg_latency:.2f}ms/frame")
    print(f"   FPS achieved: {fps_achieved:.1f} FPS")
    
    assert avg_latency < 150, "Latency too high for the synthetic motion smoke test"
    assert fps_achieved >= 5, "Throughput too low for the synthetic motion smoke test"
    print("   ✅ PASS: Performance acceptable")
    
    # Summary
    print("\n" + "="*60)
    print("✅ ALL MOTION DETECTION TESTS PASSED")
    print("="*60)
    print("\nNext step: Test YOLO object detection")
    print("Run: python vms/backend/tests/test_yolo_basic.py")

if __name__ == "__main__":
    try:
        test_motion_detection()
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
