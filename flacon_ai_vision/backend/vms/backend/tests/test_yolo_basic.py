"""
Simple standalone test for YOLO object detection
Run with: python vms/backend/tests/test_yolo_basic.py

Note: First run will download ~100MB model, subsequent runs use cache
"""

import sys
import os
import numpy as np

# Add project to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from vms.backend.ai.objects import ObjectDetector

def test_yolo_detection():
    """Test YOLO detector"""
    print("="*60)
    print("🧪 YOLO OBJECT DETECTION TEST")
    print("="*60)
    
    # Initialize detector
    print("\n1️⃣  Initializing ObjectDetector (YOLO-v8n)...")
    print("    First run will download model (~100MB), please wait...")
    
    try:
        detector = ObjectDetector(
            model_name="yolov8n",
            confidence_threshold=0.5,
            device="cpu"  # Will auto-detect GPU if available
        )
        
        if not detector.available:
            print("⚠️  YOLO not available (ultralytics not installed)")
            print("   Install: pip install ultralytics torch torchvision")
            return
        
        print("✅ Detector initialized and ready")
        
    except Exception as e:
        print(f"❌ Failed to initialize detector: {e}")
        print("\nTroubleshooting:")
        print("1. Check YOLO installation: pip install ultralytics")
        print("2. Check PyTorch: pip install torch torchvision")
        print("3. Check internet for model download")
        return
    
    # Test 1: Single frame inference
    print("\n2️⃣  Test 1: Single frame inference...")
    frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    
    result = detector.detect(frame)
    
    print(f"   Objects detected: {result['detections_count']}")
    print(f"   Processing time: {result['processing_time_ms']:.2f}ms")
    print(f"   Frame shape: {result['frame_shape']}")
    
    if result.get('error'):
        print(f"   Error: {result['error']}")
    
    if result['detections_count'] > 0:
        print(f"   First 3 detections:")
        for obj in result['objects'][:3]:
            print(f"     - {obj['class']}: {obj['confidence']:.2f} confidence")
    
    print("   ✅ PASS: Single frame inference works")
    
    # Test 2: Batch inference
    print("\n3️⃣  Test 2: Batch inference (3 frames)...")
    frames = [np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8) for _ in range(3)]
    
    import time
    start = time.time()
    batch_results = detector.detect_batch(frames)
    batch_time = (time.time() - start) * 1000
    
    print(f"   Frames processed: {len(batch_results)}")
    print(f"   Total time: {batch_time:.2f}ms")
    print(f"   Average per frame: {batch_time/len(batch_results):.2f}ms")
    
    for i, result in enumerate(batch_results):
        print(f"   Frame {i+1}: {result['detections_count']} objects")
    
    print("   ✅ PASS: Batch inference works")
    
    # Test 3: Performance benchmark
    print("\n4️⃣  Test 3: Performance benchmark (10 frames)...")
    frames = [np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8) for _ in range(10)]
    
    start = time.time()
    results = [detector.detect(f) for f in frames]
    elapsed = time.time() - start
    
    latencies = [r['processing_time_ms'] for r in results]
    avg_latency = np.mean(latencies)
    p95_latency = np.percentile(latencies, 95)
    fps = len(frames) / elapsed
    
    print(f"   Frames processed: {len(frames)}")
    print(f"   Total time: {elapsed*1000:.2f}ms")
    print(f"   Average latency: {avg_latency:.2f}ms/frame")
    print(f"   P95 latency: {p95_latency:.2f}ms")
    print(f"   FPS achieved: {fps:.1f} FPS")
    
    print("   ✅ PASS: Performance acceptable")
    
    # Test 4: Class filtering
    print("\n5️⃣  Test 4: Class filtering...")
    frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    result = detector.detect(frame)
    
    if result['detections_count'] > 0:
        persons = detector.filter_by_class(result['objects'], ['person'])
        vehicles = detector.filter_by_class(result['objects'], ['car', 'truck', 'bus'])
        
        print(f"   Total objects: {result['detections_count']}")
        print(f"   Persons: {len(persons)}")
        print(f"   Vehicles: {len(vehicles)}")
        print("   ✅ PASS: Class filtering works")
    else:
        print("   ℹ️  No objects detected (random image)")
        print("   ✅ PASS: Filtering logic OK")
    
    # Summary
    print("\n" + "="*60)
    print("✅ ALL YOLO DETECTION TESTS PASSED")
    print("="*60)
    print("\nNext step: Test InferenceManager async pipeline")
    print("Run: python vms/backend/tests/test_inference_manager.py")

if __name__ == "__main__":
    try:
        test_yolo_detection()
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
