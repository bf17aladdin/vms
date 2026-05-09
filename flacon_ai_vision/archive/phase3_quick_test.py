#!/usr/bin/env python3
"""Phase 3 Quick Performance Test (60 seconds, 8 cameras)"""

import asyncio
import sys
import time
import psutil
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import numpy as np
import cv2
from vms.backend.services.async_frame_pipeline import get_async_processor

async def quick_load_test():
    print('\n' + '='*70)
    print('PHASE 3: QUICK PERFORMANCE TEST (60s, 8 cameras)')
    print('='*70)
    
    NUM_CAMERAS = 8
    DURATION = 60
    
    # Setup
    print(f'\n[Setup] Testing {NUM_CAMERAS} cameras for {DURATION}s...')
    processor = get_async_processor()
    for i in range(NUM_CAMERAS):
        processor.add_camera(f'test_cam_{i}', f'Camera {i}')
    
    start_mem = psutil.Process().memory_info().rss / 1024 / 1024
    print(f'✓ Initial memory: {start_mem:.1f} MB')
    
    # Test
    print(f'\n[Processing] Running concurrent frame processing...')
    test_start = time.time()
    total_frames = 0
    all_latencies = []
    errors = 0
    
    for t in range(DURATION):
        for cam_id in range(NUM_CAMERAS):
            try:
                frame = np.ones((720, 1280, 3), dtype=np.uint8) * 100
                cv2.putText(frame, f'Cam {cam_id}', (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)
                
                # Create random motion
                if t % 3 == 0:
                    cv2.rectangle(frame, (100 + cam_id*20, 100), (300 + cam_id*20, 400), (0, 0, 255), -1)
                
                pipeline = processor.pipelines[f'test_cam_{cam_id}']
                result = await pipeline.process_frame(frame, db=None)
                
                all_latencies.append(result.get('latency_ms', 0))
                total_frames += 1
            except Exception as e:
                errors += 1
        
        if (t + 1) % 10 == 0:
            elapsed = time.time() - test_start
            fps = total_frames / elapsed
            print(f'  {t+1:2d}s: {total_frames:4d} frames, {fps:5.1f} FPS, {errors} errors')
    
    # Results
    total_time = time.time() - test_start
    peak_mem = psutil.Process().memory_info().rss / 1024 / 1024
    
    print(f'\n' + '='*70)
    print('RESULTS')
    print('='*70)
    print(f'Duration:         {total_time:.1f}s')
    print(f'Total Frames:     {total_frames}')
    print(f'Throughput:       {total_frames/total_time:.1f} FPS')
    print(f'Errors:           {errors} ({(errors/max(total_frames, 1)*100):.2f}%)')
    print(f'\nLatency (ms):')
    print(f'  Average:        {np.mean(all_latencies):.1f}')
    print(f'  Median (P50):   {np.percentile(all_latencies, 50):.1f}')
    print(f'  P95:            {np.percentile(all_latencies, 95):.1f}')
    print(f'  P99:            {np.percentile(all_latencies, 99):.1f}')
    print(f'  Max:            {np.max(all_latencies):.1f}')
    print(f'\nMemory (MB):')
    print(f'  Start:          {start_mem:.1f}')
    print(f'  Peak:           {peak_mem:.1f}')
    print(f'  Growth:         {peak_mem - start_mem:.1f}')
    
    # Validation
    print(f'\n' + '='*70)
    print('PRODUCTION READINESS CHECK')
    print('='*70)
    
    checks = [
        ("Throughput > 100 FPS", (total_frames/total_time) > 100),
        ("Avg Latency < 100ms", np.mean(all_latencies) < 100),
        ("P99 Latency < 200ms", np.percentile(all_latencies, 99) < 200),
        ("Error Rate < 1%", (errors/max(total_frames, 1)*100) < 1),
        ("Memory Growth < 300MB", (peak_mem - start_mem) < 300),
    ]
    
    for check_name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"{status} {check_name}")
    
    all_passed = all(check[1] for check in checks)
    
    print(f'\n' + '='*70)
    if all_passed:
        print("🎉 PHASE 3 PASSED - PRODUCTION READY!")
    else:
        print("⚠️ PHASE 3 NEEDS REVIEW - Some checks failed")
    print('='*70 + '\n')
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    exit_code = asyncio.run(quick_load_test())
    sys.exit(exit_code)
