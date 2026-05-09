#!/usr/bin/env python3
"""
FastAPI WebSocket Router avec Async FrameProcessor Pipeline
Intègre Phase 2: Async Inference Pipeline Integration
"""

import asyncio
import base64
import logging
import json
from typing import Dict, Set
from datetime import datetime

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None
    np = None

from fastapi import APIRouter, WebSocketDisconnect, WebSocket, HTTPException, Query
from sqlalchemy.orm import Session
import socketio

from vms.backend.services.async_frame_pipeline import (
    get_pipeline,
    get_async_processor,
    AsyncFrameProcessingPipeline
)
from vms.backend.routers.runtime_guard import get_manual_inference_guard_status
from vms.backend.core.config import settings

logger = logging.getLogger(__name__)

# SocketIO server for async WebSocket communication
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=settings.ALLOWED_ORIGINS,
    logger=False,
    engineio_logger=False
)

router = APIRouter(prefix="/ws", tags=["websocket"])

# Track connected clients
connected_clients: Set[str] = set()
client_pipelines: Dict[str, AsyncFrameProcessingPipeline] = {}


class WebSocketFrameStreamHandler:
    """
    Gère le streaming de frames via WebSocket avec traitement IA async
    """
    
    def __init__(self, camera_id: str, camera_name: str):
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.pipeline = get_pipeline(camera_id, camera_name)
        self.frame_count = 0
        self.error_count = 0
        self.last_broadcast = 0
        self.broadcast_interval = 0.03  # ~30 FPS
    
    async def process_and_broadcast(self, frame_data: bytes, emit_callback):
        """
        Traiter un frame et broadcaster les résultats
        
        Args:
            frame_data: Frame encodé (base64 ou binaire)
            emit_callback: Callback pour envoyer résultats
        """
        try:
            # Décoder frame
            frame_array = np.frombuffer(base64.b64decode(frame_data), dtype=np.uint8)
            frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
            
            if frame is None or frame.size == 0:
                self.error_count += 1
                return {"error": "Invalid frame"}
            
            # Traiter async avec la pipeline complète
            results = await self.pipeline.process_frame(frame, db=None)
            
            self.frame_count += 1
            
            # Formater résultats pour le client
            response = {
                "camera_id": self.camera_id,
                "frame_count": self.frame_count,
                "timestamp": results.get("timestamp"),
                "latency_ms": results.get("latency_ms", 0),
                "ai_latency_ms": results.get("ai_latency_ms", 0),
                
                # Détections
                "motion": {
                    "detected": results.get("motion", {}).get("detected", False),
                    "confidence": results.get("motion", {}).get("confidence", 0.0)
                },
                "objects": [
                    {
                        "class": obj.get("class"),
                        "confidence": obj.get("confidence"),
                        "bbox": obj.get("bbox")
                    }
                    for obj in results.get("objects", [])[:10]  # Limit to 10
                ],
                "faces_count": len(results.get("faces", [])),
                "vehicles_count": len(results.get("vehicles", [])),
                "alerts": results.get("alerts", [])
            }
            
            # Broadcaster
            await emit_callback("detection_result", response)
            
            return response
            
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error processing frame for {self.camera_id}: {e}")
            return {"error": str(e), "camera_id": self.camera_id}
    
    def get_stats(self) -> Dict:
        """Obtenir les stats du handler"""
        return {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "frames_processed": self.frame_count,
            "errors": self.error_count,
            "error_rate": f"{(self.error_count / max(self.frame_count, 1)) * 100:.2f}%"
        }


# === SocketIO Event Handlers ===

@sio.on('connect')
async def handle_connect(sid: str, environ):
    """Client connected"""
    logger.info(f"Client connected: {sid}")
    connected_clients.add(sid)
    await sio.emit('connection', {"status": "connected", "client_id": sid}, to=sid)


@sio.on('disconnect')
async def handle_disconnect(sid: str):
    """Client disconnected"""
    logger.info(f"Client disconnected: {sid}")
    connected_clients.discard(sid)
    
    # Cleanup pipeline
    if sid in client_pipelines:
        del client_pipelines[sid]


@sio.on('start_stream')
async def handle_start_stream(sid: str, data: Dict):
    """
    Client demande de démarrer le streaming pour une caméra
    
    Expected data:
    {
        "camera_id": "cam_1",
        "camera_name": "Front Door"
    }
    """
    try:
        guard = get_manual_inference_guard_status()
        if not bool(guard.get("allowed", True)):
            await sio.emit(
                'error',
                {
                    "code": "MANUAL_INFERENCE_BLOCKED",
                    "message": guard.get("message"),
                    "guard": guard,
                },
                to=sid,
            )
            return

        camera_id = data.get("camera_id", f"client_{sid}")
        camera_name = data.get("camera_name", camera_id)
        
        # Créer handler pour cette session
        handler = WebSocketFrameStreamHandler(camera_id, camera_name)
        client_pipelines[sid] = handler
        
        logger.info(f"Stream started: {camera_id} from {sid}")
        await sio.emit('stream_started', {
            "camera_id": camera_id,
            "status": "ready"
        }, to=sid)
        
    except Exception as e:
        logger.error(f"Error starting stream: {e}")
        await sio.emit('error', {"message": str(e)}, to=sid)


@sio.on('frame_data')
async def handle_frame_data(sid: str, data: Dict):
    """
    Reçoit frame encodée du client et retourne résultats IA
    
    Expected data:
    {
        "frame": "<base64 encoded frame>",
        "width": 1280,
        "height": 720
    }
    """
    try:
        if sid not in client_pipelines:
            await sio.emit('error', {"message": "Stream not started"}, to=sid)
            return
        
        handler = client_pipelines[sid]
        frame_data = data.get("frame")
        
        if not frame_data:
            return
        
        # Traiter frame async et broadcaster résultats
        async def emit_results(event_name, payload):
            await sio.emit(event_name, payload, to=sid)
        
        result = await handler.process_and_broadcast(frame_data, emit_results)
        
    except Exception as e:
        logger.error(f"Error processing frame: {e}")
        await sio.emit('error', {"message": str(e)}, to=sid)


@sio.on('get_stats')
async def handle_get_stats(sid: str):
    """Client demande les statistiques"""
    try:
        if sid in client_pipelines:
            stats = client_pipelines[sid].get_stats()
            await sio.emit('stats', stats, to=sid)
        else:
            await sio.emit('stats', {"error": "No stream active"}, to=sid)
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        await sio.emit('error', {"message": str(e)}, to=sid)


@sio.on('stop_stream')
async def handle_stop_stream(sid: str):
    """Client demande d'arrêter le streaming"""
    try:
        if sid in client_pipelines:
            stats = client_pipelines[sid].get_stats()
            del client_pipelines[sid]
            
            await sio.emit('stream_stopped', {
                "status": "stopped",
                "final_stats": stats
            }, to=sid)
            
            logger.info(f"Stream stopped for {sid}: {stats}")
    except Exception as e:
        logger.error(f"Error stopping stream: {e}")
        await sio.emit('error', {"message": str(e)}, to=sid)


# === FastAPI Endpoints ===

@router.get("/status")
async def websocket_status():
    """Obtenir le statut du WebSocket"""
    processor = get_async_processor()
    
    return {
        "connected_clients": len(connected_clients),
        "active_streams": len(client_pipelines),
        "pipelines": processor.get_all_stats(),
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/cameras")
async def get_camera_streams():
    """Lister les caméras actuellement traitées"""
    processor = get_async_processor()
    stats = processor.get_all_stats()
    
    return {
        "total_cameras": len(stats),
        "cameras": stats,
        "timestamp": datetime.utcnow().isoformat()
    }


@router.post("/broadcast-detection")
async def broadcast_detection(detection_data: Dict):
    """Broadcaster un événement de détection à tous les clients"""
    try:
        await sio.emit('broadcast_detection', detection_data)
        return {"status": "broadcasted", "clients": len(connected_clients)}
    except Exception as e:
        logger.error(f"Error broadcasting: {e}")
        return {"error": str(e)}, 500


# === Integration with FastAPI ===

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

def setup_websocket_routes(app: FastAPI):
    """
    Configure WebSocket routes in FastAPI app
    
    Usage:
        app = FastAPI()
        setup_websocket_routes(app)
    """
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include router
    app.include_router(router)
    
    # Mount SocketIO
    app.mount("/socket.io", socketio.ASGIApp(sio, async_mode='asgi'))
    
    logger.info("✅ WebSocket routes configured")


# === Example Client Usage ===
"""
// JavaScript client example
const socket = io('http://localhost:8000');

// Connect
socket.on('connect', () => {
    console.log('Connected to server');
    
    // Start stream for camera
    socket.emit('start_stream', {
        'camera_id': 'cam_1',
        'camera_name': 'Front Door'
    });
});

// Receive detection results
socket.on('detection_result', (data) => {
    console.log('Detection:', data);
    // data contains: motion, objects, faces_count, latency_ms, etc.
});

// Send frame for processing
async function sendFrame() {
    const canvas = document.getElementById('video');
    const ctx = canvas.getContext('2d');
    const imageData = canvas.toDataURL('image/jpeg');
    
    socket.emit('frame_data', {
        'frame': imageData.split(',')[1],  // base64 only
        'width': 1280,
        'height': 720
    });
}

// Get statistics
socket.emit('get_stats', {});
socket.on('stats', (stats) => {
    console.log('Pipeline stats:', stats);
});

// Stop stream
socket.emit('stop_stream', {});
"""
