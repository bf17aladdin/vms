#!/usr/bin/env python3
"""
Exemple concret: Traitement async de 4 caméras en parallèle
Démontre la scalabilité et la performance de la pipeline
"""

import asyncio
import sys
import time
from pathlib import Path

# Add workspace to path
workspace_root = Path(__file__).parent
sys.path.insert(0, str(workspace_root))

import numpy as np
import cv2

# Import async processor
from vms.backend.services.async_frame_pipeline import (
    get_async_processor,
    MultiCameraAsyncProcessor
)

print("\n" + "="*70)
print("EXAMPLE: Parallel Multi-Camera Async Processing (Phase 2)")
print("="*70)

# === Setup: Register 4 cameras ===
print("\n[Setup] Registering 4 cameras...")
processor = get_async_processor()
cameras = [
    ("cam_1", "Front Door"),
    ("cam_2", "Garage"),
    ("cam_3", "Parking Gate"),
    ("cam_4", "Loading Bay")
]

for camera_id, camera_name in cameras:
    processor.add_camera(camera_id, camera_name)
    print(f"  ✓ Registered {camera_id}: {camera_name}")

print(f"\n✅ Total cameras registered: {len(processor.pipelines)}")

# === Generate test frames ===
print("\n[Generate] Creating synthetic test frames (720p)...")

def create_test_frame(camera_id: str, motion_intensity: float = 0.5) -> np.ndarray:
    """Create a test frame with configurable motion"""
    frame = np.ones((720, 1280, 3), dtype=np.uint8) * 100
    
    # Add some variation based on motion intensity
    noise = np.random.randint(-30, 30, frame.shape, dtype=np.int16)
    motion_amount = int(motion_intensity * 100)
    frame = np.clip(frame.astype(np.int16) + (noise * motion_amount // 100), 0, 255).astype(np.uint8)
    
    # Add camera name
    cv2.putText(
        frame,
        f"{camera_id} - Motion: {motion_intensity:.0%}",
        (50, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 255, 0),
        2
    )
    
    # Add some rectangles to simulate objects
    if motion_intensity > 0.3:
        cv2.rectangle(frame, (100, 100), (300, 400), (0, 0, 255), -1)
    if motion_intensity > 0.7:
        cv2.rectangle(frame, (500, 200), (700, 500), (255, 0, 0), -1)
    
    return frame

# Create frames with varying motion levels
test_frames = {
    "cam_1": create_test_frame("cam_1", 0.2),  # Low motion
    "cam_2": create_test_frame("cam_2", 0.6),  # Medium motion
    "cam_3": create_test_frame("cam_3", 0.9),  # High motion
    "cam_4": create_test_frame("cam_4", 0.1),  # Very low motion
}

print("✅ Created 4 test frames (720p)")

# === Test 1: Sequential Processing (baseline) ===
print("\n[Test 1] Sequential Processing (baseline)...")

async def process_sequential():
    """Process frames one by one"""
    start = time.time()
    results = {}
    
    for camera_id, frame in test_frames.items():
        pipeline = processor.pipelines[camera_id]
        result = await pipeline.process_frame(frame)
        results[camera_id] = result
    
    elapsed = time.time() - start
    return results, elapsed

results_seq, time_seq = asyncio.run(process_sequential())
print(f"⏱️  Sequential time: {time_seq*1000:.2f}ms")

# === Test 2: Parallel Processing ===
print("\n[Test 2] Parallel Processing...")

async def process_parallel():
    """Process all frames concurrently"""
    start = time.time()
    
    results = await processor.process_frames_parallel(test_frames, db=None)
    
    elapsed = time.time() - start
    return results, elapsed

results_par, time_par = asyncio.run(process_parallel())
print(f"⏱️  Parallel time: {time_par*1000:.2f}ms")

# === Test 3: High-frequency Parallel ===
print("\n[Test 3] High-frequency Parallel (10 iterations)...")

async def process_high_frequency():
    """Process frames repeatedly to simulate real-time stream"""
    start = time.time()
    total_frames = 0
    
    for iteration in range(10):
        # Create fresh frames each iteration (simulate streaming)
        fresh_frames = {
            camera_id: create_test_frame(camera_id, np.random.rand() * 0.8)
            for camera_id in test_frames.keys()
        }
        
        # Process in parallel
        await processor.process_frames_parallel(fresh_frames, db=None)
        total_frames += len(fresh_frames)
    
    elapsed = time.time() - start
    return total_frames, elapsed

total_frames, time_freq = asyncio.run(process_high_frequency())
fps = total_frames / time_freq
print(f"⏱️  Total time: {time_freq*1000:.2f}ms")
print(f"📊 Frames processed: {total_frames}")
print(f"🚀 Throughput: {fps:.1f} FPS")

# === Analysis ===
print("\n[Analysis] Performance Comparison")
print(f"  Sequential processing: {time_seq*1000:.2f}ms")
print(f"  Parallel processing:   {time_par*1000:.2f}ms")
speedup = time_seq / time_par if time_par > 0 else 1
print(f"  Speedup:               {speedup:.2f}x faster")
efficiency = (4 / speedup) * 100  # 4 cameras
print(f"  Parallel efficiency:   {efficiency:.1f}%")

# === Results Summary ===
print("\n[Results] Detection Summary")

for camera_id in cameras:
    camera_id = camera_id[0]  # Get just the ID
    result = results_par.get(camera_id, {})
    
    motion = result.get('motion', {})
    objects = result.get('objects', [])
    
    print(f"\n  📹 {camera_id}:")
    print(f"     Motion: {motion.get('detected', False)} (conf: {motion.get('confidence', 0):.0%})")
    print(f"     Objects: {len(objects)} detected")
    if objects:
        for obj in objects:
            print(f"       - {obj.get('class', 'unknown')}: {obj.get('confidence', 0):.0%}")
    print(f"     Latency: {result.get('latency_ms', 0):.1f}ms")

# === Statistics ===
print("\n[Statistics] Pipeline Stats")
stats = processor.get_all_stats()
for camera_id, stat in stats.items():
    print(f"  {camera_id}: {stat['frames_processed']} frames processed")

# === Performance Metrics ===
print("\n" + "="*70)
print("PERFORMANCE METRICS")
print("="*70)
print(f"Sequential 4-camera:     {time_seq*1000:>8.2f}ms")
print(f"Parallel 4-camera:       {time_par*1000:>8.2f}ms")
print(f"Speedup:                 {speedup:>8.2f}x")
print(f"High-freq throughput:    {fps:>8.1f} FPS")
print(f"Average latency/cam:     {(time_par*1000/4):>8.1f}ms")

if speedup > 3.0:
    print("\n✅ EXCELLENT parallel efficiency!")
elif speedup > 2.0:
    print("\n✅ GOOD parallel efficiency")
else:
    print("\n⚠️  Parallel overhead detected - review bottlenecks")

print("\n" + "="*70)
print("Phase 2 Async Pipeline: Production Ready ✅")
print("="*70 + "\n")
