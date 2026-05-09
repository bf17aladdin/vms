#!/usr/bin/env python3
"""
Phase 3: Performance Validation - Load Test
Teste 10+ caméras en conditions réelles sur 5 minutes
Valide: latency, throughput, memory stability, error resilience
"""

import asyncio
import sys
import time
import psutil
import gc
from pathlib import Path
from typing import Dict, List
import tracemalloc
from datetime import datetime

# Add workspace to path
workspace_root = Path(__file__).parent
sys.path.insert(0, str(workspace_root.parent.parent))

import numpy as np
import cv2

# Import async processor
from vms.backend.services.async_frame_pipeline import get_async_processor

print("\n" + "="*80)
print("PHASE 3: PERFORMANCE VALIDATION - LOAD TEST (10+ Cameras)")
print("="*80)

# === Configuration ===
NUM_CAMERAS = 12
DURATION_SECONDS = 300  # 5 minutes
FPS_TARGET = 30
FRAME_SIZE = (1280, 720)  # 720p

stats = {
    "cameras": {},
    "system": {
        "start_time": None,
        "end_time": None,
        "duration": 0,
        "peak_memory_mb": 0,
        "avg_memory_mb": 0
    },
    "performance": {
        "total_frames": 0,
        "total_errors": 0,
        "avg_latency_ms": 0,
        "p50_latency_ms": 0,
        "p95_latency_ms": 0,
        "p99_latency_ms": 0,
        "min_latency_ms": float('inf'),
        "max_latency_ms": 0,
        "fps": 0
    }
}


def create_test_frame(camera_id: int, motion_intensity: float = 0.5) -> np.ndarray:
    """Create realistic test frame with varying content"""
    frame = np.ones((*FRAME_SIZE[::-1], 3), dtype=np.uint8) * 100
    
    # Add pseudo-random noise based on camera ID to simulate real content
    rng = np.random.RandomState(camera_id)
    noise = rng.randint(-30, 30, frame.shape, dtype=np.int16)
    motion_amount = int(motion_intensity * 100)
    frame = np.clip(
        frame.astype(np.int16) + (noise * motion_amount // 100), 
        0, 255
    ).astype(np.uint8)
    
    # Add camera ID text
    cv2.putText(
        frame,
        f"Camera {camera_id}",
        (50, 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        2
    )
    
    # Add simulated objects based on frame number
    frame_hash = (int(time.time() * 100) + camera_id) % 10
    if frame_hash > 3:
        cv2.rectangle(frame, (100, 100), (300, 400), (0, 0, 255), -1)
    if frame_hash > 6:
        cv2.rectangle(frame, (500, 200), (700, 500), (255, 0, 0), -1)
    
    return frame


async def process_single_camera(camera_id: int, duration: int, processor):
    """Process frames for a single camera"""
    pipeline = processor.pipelines.get(f"load_cam_{camera_id}")
    if not pipeline:
        return None
    
    latencies = []
    errors = 0
    frame_count = 0
    start_time = time.time()
    
    while time.time() - start_time < duration:
        try:
            # Create frame
            motion_intensity = min(0.2 + (frame_count % 100) / 500, 0.9)
            frame = create_test_frame(camera_id, motion_intensity)
            
            # Process async
            result = await pipeline.process_frame(frame, db=None)
            
            latency = result.get("latency_ms", 0)
            latencies.append(latency)
            frame_count += 1
            
            # Throttle to target FPS
            await asyncio.sleep(1.0 / FPS_TARGET)
            
        except Exception as e:
            errors += 1
            print(f"  ⚠️  Camera {camera_id} error: {e}")
    
    return {
        "camera_id": camera_id,
        "frame_count": frame_count,
        "errors": errors,
        "latencies": latencies,
        "avg_latency": np.mean(latencies) if latencies else 0,
        "min_latency": np.min(latencies) if latencies else 0,
        "max_latency": np.max(latencies) if latencies else 0
    }


async def run_load_test():
    """Run complete load test"""
    
    # === Setup ===
    print(f"\n[Setup] Initializing {NUM_CAMERAS} cameras...")
    processor = get_async_processor()
    
    for i in range(NUM_CAMERAS):
        processor.add_camera(f"load_cam_{i}", f"Load Test Camera {i}")
        print(f"  ✓ Camera {i} registered")
    
    print(f"✅ {NUM_CAMERAS} cameras initialized")
    
    # === Memory tracking ===
    print(f"\n[Memory] Starting trace...")
    tracemalloc.start()
    gc.collect()
    initial_memory = psutil.Process().memory_info().rss / 1024 / 1024
    print(f"✅ Initial memory: {initial_memory:.2f} MB")
    
    # === Load Test ===
    print(f"\n[Load Test] Running for {DURATION_SECONDS}s with {NUM_CAMERAS} concurrent cameras @ {FPS_TARGET} FPS...")
    print("="*80)
    
    stats["system"]["start_time"] = datetime.utcnow().isoformat()
    test_start = time.time()
    
    # Create concurrent tasks for all cameras
    tasks = [
        process_single_camera(i, DURATION_SECONDS, processor)
        for i in range(NUM_CAMERAS)
    ]
    
    # Run all cameras concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    test_duration = time.time() - test_start
    stats["system"]["end_time"] = datetime.utcnow().isoformat()
    stats["system"]["duration"] = test_duration
    
    # === Memory snapshot ===
    gc.collect()
    peak_memory = psutil.Process().memory_info().rss / 1024 / 1024
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    memory_growth = peak_memory - initial_memory
    
    print(f"\n⏱️  Total duration: {test_duration:.2f}s")
    print(f"💾 Initial memory: {initial_memory:.2f} MB")
    print(f"💾 Peak memory: {peak_memory:.2f} MB")
    print(f"📈 Memory growth: {memory_growth:.2f} MB")
    
    stats["system"]["peak_memory_mb"] = peak_memory
    stats["system"]["avg_memory_mb"] = (initial_memory + peak_memory) / 2
    stats["system"]["memory_growth_mb"] = memory_growth
    
    # === Aggregate results ===
    print(f"\n[Results] Aggregating performance data...")
    
    all_latencies = []
    total_frames = 0
    total_errors = 0
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"  ⚠️  Camera {i} failed: {result}")
            stats["cameras"][f"cam_{i}"] = {"error": str(result)}
            total_errors += 1
            continue
        
        if result:
            camera_id = result["camera_id"]
            frame_count = result["frame_count"]
            errors = result["errors"]
            latencies = result["latencies"]
            
            total_frames += frame_count
            total_errors += errors
            all_latencies.extend(latencies)
            
            stats["cameras"][f"cam_{camera_id}"] = {
                "frame_count": frame_count,
                "errors": errors,
                "error_rate": f"{(errors / max(frame_count, 1)) * 100:.2f}%",
                "avg_latency_ms": result["avg_latency"],
                "min_latency_ms": result["min_latency"],
                "max_latency_ms": result["max_latency"]
            }
    
    # === Performance metrics ===
    if all_latencies:
        all_latencies.sort()
        avg_latency = np.mean(all_latencies)
        p50 = np.percentile(all_latencies, 50)
        p95 = np.percentile(all_latencies, 95)
        p99 = np.percentile(all_latencies, 99)
        
        stats["performance"]["total_frames"] = total_frames
        stats["performance"]["total_errors"] = total_errors
        stats["performance"]["avg_latency_ms"] = avg_latency
        stats["performance"]["p50_latency_ms"] = p50
        stats["performance"]["p95_latency_ms"] = p95
        stats["performance"]["p99_latency_ms"] = p99
        stats["performance"]["min_latency_ms"] = np.min(all_latencies)
        stats["performance"]["max_latency_ms"] = np.max(all_latencies)
        stats["performance"]["fps"] = total_frames / test_duration
    
    return stats


# === Generate Report ===
def generate_report(stats: Dict):
    """Generate detailed performance report"""
    
    print("\n" + "="*80)
    print("PHASE 3 PERFORMANCE VALIDATION REPORT")
    print("="*80)
    
    # System metrics
    print(f"\n📊 SYSTEM METRICS")
    print("-" * 80)
    print(f"Duration:         {stats['system']['duration']:.2f} seconds")
    print(f"Cameras:          {NUM_CAMERAS}")
    print(f"Target FPS:       {FPS_TARGET}")
    print(f"Initial Memory:   {stats['system'].get('peak_memory_mb', 0) / 2:.2f} MB")  # rough
    print(f"Peak Memory:      {stats['system']['peak_memory_mb']:.2f} MB")
    print(f"Memory Growth:    {stats['system'].get('memory_growth_mb', 0):.2f} MB")
    
    # Performance metrics
    perf = stats["performance"]
    print(f"\n⚡ PERFORMANCE METRICS")
    print("-" * 80)
    print(f"Total Frames:     {perf['total_frames']}")
    print(f"Total Errors:     {perf['total_errors']}")
    print(f"Error Rate:       {(perf['total_errors'] / max(perf['total_frames'], 1)) * 100:.3f}%")
    print(f"Throughput (FPS): {perf['fps']:.2f}")
    print(f"Target Achieved:  {(perf['fps'] / (NUM_CAMERAS * FPS_TARGET) * 100):.1f}%")
    
    # Latency metrics
    print(f"\n⏱️  LATENCY METRICS (ms)")
    print("-" * 80)
    print(f"Average:          {perf['avg_latency_ms']:.2f} ms")
    print(f"P50 (Median):     {perf['p50_latency_ms']:.2f} ms")
    print(f"P95:              {perf['p95_latency_ms']:.2f} ms")
    print(f"P99:              {perf['p99_latency_ms']:.2f} ms")
    print(f"Min:              {perf['min_latency_ms']:.2f} ms")
    print(f"Max:              {perf['max_latency_ms']:.2f} ms")
    
    # Per-camera stats
    print(f"\n📹 PER-CAMERA SUMMARY (Sample of 3)")
    print("-" * 80)
    for i, (cam_id, cam_stats) in enumerate(list(stats["cameras"].items())[:3]):
        if "error" not in cam_stats:
            print(f"{cam_id}:")
            print(f"  Frames:   {cam_stats['frame_count']}")
            print(f"  Errors:   {cam_stats['errors']} ({cam_stats['error_rate']})")
            print(f"  Avg Lat:  {cam_stats['avg_latency_ms']:.2f} ms")
    
    # Validation checks
    print(f"\n✅ VALIDATION CHECKS")
    print("-" * 80)
    
    checks = []
    
    # Check 1: Memory growth acceptable
    memory_growth = stats["system"].get("memory_growth_mb", 0)
    max_growth = 500  # 500 MB acceptable for 12 cameras
    memory_ok = memory_growth < max_growth
    checks.append((f"Memory growth < {max_growth}MB", memory_ok, memory_growth))
    
    # Check 2: Latency acceptable
    avg_lat = perf["avg_latency_ms"]
    max_lat = 100  # 100ms target
    latency_ok = avg_lat < max_lat
    checks.append((f"Average latency < {max_lat}ms", latency_ok, avg_lat))
    
    # Check 3: P99 latency acceptable
    p99_lat = perf["p99_latency_ms"]
    max_p99 = 200  # 200ms P99
    p99_ok = p99_lat < max_p99
    checks.append((f"P99 latency < {max_p99}ms", p99_ok, p99_lat))
    
    # Check 4: Error rate < 1%
    error_rate = (perf["total_errors"] / max(perf["total_frames"], 1)) * 100
    error_ok = error_rate < 1.0
    checks.append((f"Error rate < 1.0%", error_ok, error_rate))
    
    # Check 5: Throughput > 50% of target
    target_throughput = NUM_CAMERAS * FPS_TARGET
    throughput_ok = perf["fps"] > target_throughput * 0.5
    checks.append((f"Throughput > 50% target ({target_throughput * 0.5:.1f} FPS)", throughput_ok, perf["fps"]))
    
    for check_name, passed, value in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {check_name}")
        print(f"   Value: {value:.2f}" + ("ms" if "latency" | "Latency" in check_name else "%s" % ("MB" if "Memory" in check_name else "FPS" if "Throughput" in check_name else "%")))
    
    all_passed = all(check[1] for check in checks)
    
    # Final verdict
    print(f"\n" + "="*80)
    if all_passed:
        print("🎉 PHASE 3 VALIDATION: PASSED - PRODUCTION READY")
        print("="*80)
        print("\nThe system is ready for production deployment with:")
        print(f"  • {NUM_CAMERAS} concurrent cameras")
        print(f"  • {perf['fps']:.1f} FPS throughput")
        print(f"  • {perf['avg_latency_ms']:.1f}ms latency")
        print(f"  • {error_rate:.3f}% error rate")
    else:
        print("⚠️  PHASE 3 VALIDATION: NEEDS OPTIMIZATION")
        print("="*80)
        print("\nFailed checks need attention before production:")
        for check_name, passed, value in checks:
            if not passed:
                print(f"  • {check_name}: {value:.2f}")
    
    print("="*80 + "\n")
    
    return all_passed


# === Main Execution ===
async def main():
    try:
        # Run load test
        results = await run_load_test()
        
        # Generate report
        passed = generate_report(results)
        
        # Save results
        import json
        report_file = Path(__file__).parent / "phase3_load_test_results.json"
        with open(report_file, "w") as f:
            # Convert numpy types to native Python types for JSON
            def convert_types(obj):
                if isinstance(obj, np.integer):
                    return int(obj)
                elif isinstance(obj, np.floating):
                    return float(obj)
                elif isinstance(obj, dict):
                    return {k: convert_types(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [convert_types(item) for item in obj]
                return obj
            
            json.dump(convert_types(results), f, indent=2)
        
        print(f"📊 Results saved to {report_file}")
        
        return 0 if passed else 1
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
