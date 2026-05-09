# 📋 Roadmap: Phase 3-5 Production Path

## Phase 3: Performance Validation & Optimization (2-3 hours)

### Objectives
- [ ] Load test with 10+ concurrent cameras
- [ ] Memory profiling over extended run
- [ ] GPU optimization (if CUDA available)
- [ ] Identify and fix bottlenecks

### Implementation Tasks

#### Task 3.1: Load Testing Setup
```python
# Create vms/backend/tests/test_load_performance.py
- Simulate 10+ concurrent camera streams
- Measure aggregate FPS and latency
- Track memory growth over time
- Create performance baseline
```

Performance targets for Phase 3:
- [ ] 10 cameras @ 30 FPS = 300 FPS total
- [ ] Memory stable (< 1GB for 10 cameras)
- [ ] P99 latency < 200ms
- [ ] No memory leaks over 1-hour runtime

#### Task 3.2: GPU Optimization
```bash
# Check GPU availability
python -c "import torch; print(torch.cuda.is_available())"

# If available:
- [ ] Enable GPU in InferenceManager
- [ ] Measure inference speedup
- [ ] Benchmark 4K vs 720p resolution
```

#### Task 3.3: Profiling & Analysis
```python
# Use cProfile for bottleneck identification
import cProfile
profiler = cProfile.Profile()
profiler.enable()
# ... async processing ...
profiler.disable()
profiler.print_stats(sort='cumulative')
```

### Acceptance Criteria
- ✅ 10+ cameras running stably
- ✅ Memory < 1.2GB peak
- ✅ No reported memory leaks
- ✅ Performance report generated

---

## Phase 4: End-to-End Integration Testing (2-3 hours)

### Objectives
- [ ] Integrate into main FastAPI WebSocket router
- [ ] Test with real RTSP streams
- [ ] Verify event persistence
- [ ] E2E testing with frontend

### Implementation Tasks

#### Task 4.1: WebSocket Router Integration
```python
# Modify vms/backend/routers/cameras.py
from vms.backend.services.async_frame_pipeline import get_pipeline

@sio.on('stream_frame')
async def handle_stream_frame(sid: str, data: dict):
    """
    Receive frame from client, process with AI, send results back
    """
    camera_id = data['camera_id']
    frame_bytes = base64.b64decode(data['frame_data'])
    frame = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
    
    pipeline = get_pipeline(camera_id, camera_name="Live Stream")
    results = await pipeline.process_frame(frame, db=db_session)
    
    # Send detection results back to client
    await sio.emit('detections', {
        'camera_id': camera_id,
        'motion': results['motion'],
        'objects': results['objects'],
        'faces': results['faces'],
        'timestamp': results['timestamp'],
        'latency_ms': results['latency_ms']
    }, to=sid)
```

#### Task 4.2: RTSP Stream Integration
```python
# Create vms/backend/services/rtsp_processor.py
import asyncio
from vms.backend.services.async_frame_pipeline import get_pipeline

async def process_rtsp_stream(camera_id: str, rtsp_url: str):
    """
    Connect to RTSP stream and process frames continuously
    """
    pipeline = get_pipeline(camera_id, camera_name=f"RTSP {camera_id}")
    cap = cv2.VideoCapture(rtsp_url)
    
    frame_count = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        results = await pipeline.process_frame(frame, db=db_session)
        
        # Log high-value detections
        if results['motion']['detected']:
            logger.info(f"[{camera_id}] Motion detected: {results['motion']['confidence']:.0%}")
        
        if results['objects']:
            logger.info(f"[{camera_id}] Objects: {[o['class'] for o in results['objects']]}")
        
        # Every 30 frames, log statistics
        if frame_count % 30 == 0:
            logger.debug(f"[{camera_id}] Processed {frame_count} frames, latency: {results['latency_ms']:.1f}ms")
    
    cap.release()
```

#### Task 4.3: Event Persistence
```python
# Modify vms/backend/services/event_service.py
async def create_ai_detection_event(
    db: Session,
    camera_id: str,
    detection_type: str,  # "motion", "person", "car", etc.
    confidence: float,
    metadata: dict
):
    """
    Persist AI detection events to database
    """
    event = Event(
        camera_id=camera_id,
        type=f"ai_{detection_type}",
        severity="info" if confidence < 0.8 else "warning",
        data={
            "detection_type": detection_type,
            "confidence": confidence,
            "metadata": metadata,
            "source": "ai_inference_manager"
        },
        created_at=datetime.utcnow()
    )
    db.add(event)
    db.commit()
```

#### Task 4.4: Frontend Integration
```javascript
// frontend/src/pages/Camera.jsx
const handleDetections = (data) => {
    setDetections({
        motion: data.motion,
        objects: data.objects,
        faces: data.faces,
        latency: data.latency_ms
    });
    
    // Draw bboxes on canvas
    drawDetections(canvasRef, data);
};

socket.on('detections', handleDetections);
```

### Test Scenarios
- [ ] 1 camera with RTSP stream for 5 minutes
- [ ] 4 cameras with mixed RTSP + WebSocket
- [ ] Event logging to database
- [ ] Frontend real-time updates
- [ ] Error recovery (connection drops, bad frames)

### Acceptance Criteria
- ✅ RTSP streams decode and process correctly
- ✅ Events logged to database with timestamps
- ✅ Frontend displays detections in real-time
- ✅ No connection drops or hangs
- ✅ Graceful recovery from errors

---

## Phase 5: Production Deployment & Docker (2-3 hours)

### Objectives
- [ ] Dockerize application
- [ ] Environment configuration
- [ ] Health checks & monitoring
- [ ] Production deployment script

### Implementation Tasks

#### Task 5.1: Docker Setup
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libsm6 libxext6 libxrender-dev \
    libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download YOLO model to avoid first-run delay
RUN python -c "from ultralytics import YOLO; YOLO('yolov8s.pt')"

# Copy application code
COPY vms/ /app/vms/
COPY startup.py .

# Expose port
EXPOSE 8000

# Start application
CMD ["uvicorn", "vms.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Task 5.2: Environment Configuration
```bash
# .env.production
# Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=vms_user
DB_PASS=${DB_PASSWORD}  # From secrets
DB_NAME=falcon_ai_vision

# AI/ML
ENABLE_GPU=true
YOLO_MODEL_SIZE=s  # nano/small/medium/large
MOTION_SENSITIVITY=0.3
OBJECT_CONFIDENCE_THRESHOLD=0.5

# Performance
MAX_CONCURRENT_CAMERAS=20
FRAME_SKIP_INTERVAL=5
BATCH_PROCESSING_SIZE=4

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/vms/app.log
```

#### Task 5.3: Health Check Endpoints
```python
# vms/backend/routers/health.py
@app.get("/health")
async def health_check():
    """System health check endpoint"""
    try:
        # Check database
        db = SessionLocal()
        db.execute("SELECT 1")
        db.close()
        
        # Check AI models
        mgr = get_inference_manager()
        
        return {
            "status": "healthy",
            "database": "connected",
            "ai_manager": "ready",
            "version": "2.0.0",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }, 503

@app.get("/metrics")
async def metrics():
    """Performance metrics endpoint"""
    processor = get_async_processor()
    stats = processor.get_all_stats()
    
    return {
        "cameras": {
            "active": len(stats),
            "stats": stats
        },
        "performance": {
            "fps": calculate_aggregate_fps(),
            "avg_latency_ms": calculate_avg_latency(),
            "memory_usage_mb": get_memory_usage()
        }
    }
```

#### Task 5.4: Deployment Script
```bash
#!/bin/bash
# deploy.sh

set -e

echo "🚀 Falcon AI Vision - Production Deployment"
echo "========================================"

# Build Docker image
echo "📦 Building Docker image..."
docker build -t falcon-ai-vision:prod .

# Stop existing container
echo "🛑 Stopping previous container..."
docker stop falcon-ai-vision || true

# Start new container
echo "🚀 Starting new container..."
docker run -d \
    --name falcon-ai-vision \
    --restart unless-stopped \
    -p 8000:8000 \
    -e DB_PASSWORD=${DB_PASSWORD} \
    -e LOG_LEVEL=INFO \
    -v /data/vms:/app/data \
    falcon-ai-vision:prod

# Wait for startup
echo "⏳ Waiting for service to start..."
sleep 5

# Check health
echo "🏥 Checking health..."
curl http://localhost:8000/health || {
    echo "❌ Health check failed!"
    docker logs falcon-ai-vision
    exit 1
}

echo "✅ Deployment successful!"
```

### Production Checklist
- [ ] Docker image builds without errors
- [ ] All env variables configured
- [ ] Health checks pass
- [ ] Metrics endpoint working
- [ ] Logs configured and rotating
- [ ] Database backed up
- [ ] SSL/TLS configured (if external access)
- [ ] Rate limiting enabled
- [ ] CORS configured for frontend
- [ ] Monitoring tools integrated (Prometheus/Grafana)

### Acceptance Criteria
- ✅ Docker image builds & runs
- ✅ Health check passes
- ✅ Production deployment script works
- ✅ Service handles graceful shutdown
- ✅ Logs are structured && queryable
- ✅ Metrics are exportable

---

## Timeline & Effort Estimate

| Phase | Duration | Complexity | Status |
|-------|----------|-----------|--------|
| Phase 1: AI Implementation | ✅ 2h | Medium | **COMPLETE** |
| Phase 2: Async Pipeline | ✅ 1h | Medium | **COMPLETE** |
| Phase 3: Performance | 2-3h | High | 🔄 NEXT |
| Phase 4: E2E Integration | 2-3h | High | Planned |
| Phase 5: Production | 2-3h | Medium | Planned |
| **Total** | **~12h** | - | - |

---

## Success Metrics

### Phase 3
- [ ] 10 cameras stably running
- [ ] Memory stable over 1 hour
- [ ] P99 latency < 200ms

### Phase 4
- [ ] RTSP stream processing
- [ ] WebSocket real-time updates
- [ ] Events persisted correctly
- [ ] Frontend displays detections

### Phase 5
- [ ] Docker deployment successful
- [ ] Automated health checks passing
- [ ] Metrics available
- [ ] Ready for cloud deployment

---

## Critical Success Factors

1. **Performance**: Must maintain <30fps at 30FPS per camera
2. **Stability**: No crashes or hangs over extended runtime
3. **Scalability**: Should handle 20+ cameras
4. **Monitoring**: All metrics visible and actionable
5. **Resilience**: Graceful error handling and recovery

---

## Next Immediate Actions

### ☝️ To proceed with Phase 3:
1. Run extended load test (10 cameras, 1 hour)
2. Identify any memory leaks
3. Profile for bottlenecks
4. Optimize based on findings

**Estimated time to Phase 3 completion**: 2-3 hours

---

Last Updated: Phase 2 Complete
Next Phase: Phase 3 - Performance Validation
Status: Ready to Begin
