"""
Prometheus Monitoring Module for Falcon AI Vision
Provides metrics collection and exposure for monitoring systems
"""

from prometheus_client import Counter, Histogram, Gauge, generate_latest
from fastapi import FastAPI, Request
import time
import logging
from typing import Callable

logger = logging.getLogger("falcon_ai_vision")

# Metrics Definitions

# Request metrics
REQUEST_COUNT = Counter(
    'app_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

REQUEST_DURATION = Histogram(
    'app_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# WebSocket metrics
WEBSOCKET_CONNECTIONS = Gauge(
    'app_websocket_connections_active',
    'Active WebSocket connections'
)

WEBSOCKET_FRAMES = Counter(
    'app_websocket_frames_total',
    'Total WebSocket frames processed',
    ['camera_id', 'type']
)

# AI Model metrics
AI_INFERENCE_DURATION = Histogram(
    'app_ai_inference_duration_seconds',
    'AI model inference duration',
    ['model_type'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
)

AI_DETECTIONS = Counter(
    'app_ai_detections_total',
    'Total detections by AI models',
    ['model_type', 'detection_class']
)

# Database metrics
DB_QUERY_DURATION = Histogram(
    'app_db_query_duration_seconds',
    'Database query duration',
    ['query_type'],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0)
)

DB_CONNECTIONS = Gauge(
    'app_db_connections_active',
    'Active database connections'
)

# Memory and system metrics
MEMORY_USAGE = Gauge(
    'app_memory_bytes',
    'Memory usage in bytes'
)

QUEUE_SIZE = Gauge(
    'app_queue_size',
    'Frame processing queue size',
    ['queue_name']
)

# Error metrics
ERRORS_TOTAL = Counter(
    'app_errors_total',
    'Total application errors',
    ['error_type', 'endpoint']
)


def setup_monitoring(app: FastAPI, enabled: bool = True) -> FastAPI:
    """
    Setup Prometheus monitoring for FastAPI application
    
    Args:
        app: FastAPI application instance
        enabled: Whether monitoring is enabled
        
    Returns:
        FastAPI app with monitoring configured
    """
    
    if not enabled:
        logger.info("⚠️  Monitoring is disabled")
        return app
    
    @app.middleware("http")
    async def add_metrics(request: Request, call_next: Callable):
        """Middleware to collect HTTP metrics"""
        
        start_time = time.time()
        method = request.method
        
        # Skip metrics endpoint to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)
        
        # Get endpoint path (avoid query params)
        endpoint = request.url.path
        
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as e:
            # Record error and re-raise
            ERRORS_TOTAL.labels(
                error_type=type(e).__name__,
                endpoint=endpoint
            ).inc()
            raise
        finally:
            # Record metrics
            duration = time.time() - start_time
            REQUEST_COUNT.labels(
                method=method,
                endpoint=endpoint,
                status=status if 'status' in locals() else 500
            ).inc()
            REQUEST_DURATION.labels(
                method=method,
                endpoint=endpoint
            ).observe(duration)
        
        return response
    
    @app.get("/metrics", tags=["monitoring"])
    async def get_metrics():
        """Prometheus metrics endpoint"""
        return generate_latest()
    
    logger.info("✅ Prometheus monitoring configured")
    logger.info("   Metrics available at: GET /metrics")
    
    return app


def record_ai_inference(model_type: str, duration: float, detections_count: int = 0):
    """Record AI inference metrics"""
    AI_INFERENCE_DURATION.labels(model_type=model_type).observe(duration)
    if detections_count > 0:
        AI_DETECTIONS.labels(
            model_type=model_type,
            detection_class="generic"
        ).inc(detections_count)


def record_db_query(query_type: str, duration: float):
    """Record database query metrics"""
    DB_QUERY_DURATION.labels(query_type=query_type).observe(duration)


def record_error(error_type: str, endpoint: str):
    """Record application errors"""
    ERRORS_TOTAL.labels(error_type=error_type, endpoint=endpoint).inc()


def update_active_connections(count: int):
    """Update gauge for active connections"""
    WEBSOCKET_CONNECTIONS.set(count)


def update_queue_size(queue_name: str, size: int):
    """Update gauge for queue sizes"""
    QUEUE_SIZE.labels(queue_name=queue_name).set(size)


def update_memory_usage(bytes_used: int):
    """Update gauge for memory usage"""
    MEMORY_USAGE.set(bytes_used)


# Example usage in routes:
# from vms.backend.core.monitoring import record_ai_inference, record_error
#
# @app.post("/api/detect")
# async def detect(frame_data: str):
#     start = time.time()
#     try:
#         result = await model.infer(frame_data)
#         duration = time.time() - start
#         record_ai_inference("YOLO", duration, len(result.detections))
#         return result
#     except Exception as e:
#         record_error(type(e).__name__, "/api/detect")
#         raise
