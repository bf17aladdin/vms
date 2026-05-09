#!/usr/bin/env python3
"""Phase 3: Fast Performance Test (10 seconds, 4 cameras)"""

import asyncio
import sys
import time
import psutil
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

import numpy as np
import cv2

async def fast_validation():
    print('\n' + '='*70)
    print('PHASE 3: FAST VALIDATION (10s, 4 cameras)')
    print('='*70)
    
    try:
        from vms.backend.services.async_frame_pipeline import get_async_processor
        
        NUM_CAMERAS = 4
        DURATION = 10
        
        print(f'\n✓ Importing processor...')
        processor = get_async_processor()
        
        print(f'✓ Registering {NUM_CAMERAS} cameras...')
        for i in range(NUM_CAMERAS):
            processor.add_camera(f'test_cam_{i}', f'Cam {i}')
        
        start_mem = psutil.Process().memory_info().rss / 1024 / 1024
        print(f'✓ Initial Memory: {start_mem:.1f} MB')
        
        print(f'\n✓ Processing frames for {DURATION}s...')
        test_start = time.time()
        total_frames = 0
        errors = 0
        
        while time.time() - test_start < DURATION:
            for cam_id in range(NUM_CAMERAS):
                try:
                    frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
                    pipeline = processor.pipelines[f'test_cam_{cam_id}']
                    result = await pipeline.process_frame(frame, db=None)
                    total_frames += 1
                except Exception as e:
                    errors += 1
            
            # Small sleep
            await asyncio.sleep(0.001)
        
        total_time = time.time() - test_start
        peak_mem = psutil.Process().memory_info().rss / 1024 / 1024
        
        print(f'\n' + '='*70)
        print('VALIDATION RESULTS')
        print('='*70)
        print(f'Duration:       {total_time:.1f}s')
        print(f'Frames:         {total_frames}')
        print(f'FPS:            {total_frames/total_time:.1f}')
        print(f'Errors:         {errors}')
        print(f'Memory Start:   {start_mem:.1f} MB')
        print(f'Memory Peak:    {peak_mem:.1f} MB')
        print(f'Memory Growth:  {peak_mem - start_mem:.1f} MB')
        
        # Quick checks
        passed = (
            (total_frames / total_time) > 30 and
            (peak_mem - start_mem) < 200 and
            errors < 5
        )
        
        if passed:
            print('\n✅ PASSED - System is performant')
            print('   Ready for Phase 4 integration')
        else:
            print('\n⚠️ REVIEW NEEDED')
        
        print('='*70 + '\n')
        return 0 if passed else 1
        
    except Exception as e:
        print(f'\n❌ Error: {e}')
        import traceback
        traceback.print_exc()
        return 1

asyncio.run(fast_validation())
