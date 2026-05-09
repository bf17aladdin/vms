#!/usr/bin/env python3
"""
FastAPI WebSocket Router avec Async FrameProcessor Pipeline
Intégration native FastAPI WebSocket (pas SocketIO)
"""

import asyncio
import base64
import logging
import json
from typing import Dict, Set

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None
    np = None

from fastapi import APIRouter, WebSocketDisconnect, WebSocket, HTTPException
from sqlalchemy.orm import Session

from vms.backend.core.time_utils import utc_now_naive_iso
from vms.backend.core.security import authenticate_websocket
from vms.backend.services.async_frame_pipeline import (
    get_pipeline,
    get_async_processor
)
from vms.backend.routers.runtime_guard import get_manual_inference_guard_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

# Track connected clients
connected_clients: Dict[str, WebSocket] = {}


@router.websocket("/ai/stream/{camera_id}")
async def websocket_ai_stream(websocket: WebSocket, camera_id: str):
    """
    WebSocket endpoint pour streaming AI-powered video
    
    Client sends:
    {
        "action": "start_stream",
        "camera_name": "Front Door",
        "frame_data": "<base64 jpeg>"
    }
    
    Server responds:
    {
        "camera_id": "cam_1",
        "detections": {...},
        "latency_ms": 32.5
    }
    """
    current_user = await authenticate_websocket(websocket)
    if current_user is None:
        return

    await websocket.accept()
    guard = get_manual_inference_guard_status()
    if not bool(guard.get("allowed", True)):
        await websocket.send_json(
            {
                "code": "MANUAL_INFERENCE_BLOCKED",
                "message": guard.get("message"),
                "guard": guard,
            }
        )
        await websocket.close(code=1013)
        return
    client_id = f"{camera_id}_{id(websocket)}"
    connected_clients[client_id] = websocket
    
    logger.info(f"✅ WebSocket client connected: {client_id}")
    
    try:
        pipeline = get_pipeline(camera_id, camera_name=camera_id)
        
        while True:
            # Receive message from client
            try:
                message = await websocket.receive_json()
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                break
            
            action = message.get("action", "frame_data")
            
            # === Handle frame data ===
            if action == "frame_data":
                try:
                    frame_data = message.get("frame_data")
                    if not frame_data:
                        continue
                    
                    # Decode frame
                    frame_bytes = base64.b64decode(frame_data)
                    frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
                    frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                    
                    if frame is None or frame.size == 0:
                        continue
                    
                    # Process async
                    result = await pipeline.process_frame(frame, db=None)
                    
                    # Send detection results back
                    response = {
                        "camera_id": camera_id,
                        "timestamp": result.get("timestamp"),
                        "detections": {
                            "motion": result.get("motion"),
                            "objects": result.get("objects", [])[:10],  # Limit to 10
                            "faces_count": len(result.get("faces", [])),
                            "vehicles_count": len(result.get("vehicles", []))
                        },
                        "latency_ms": result.get("latency_ms", 0),
                        "ai_latency_ms": result.get("ai_latency_ms", 0)
                    }
                    
                    await websocket.send_json(response)
                    
                except Exception as e:
                    logger.error(f"Error processing frame: {e}")
                    await websocket.send_json({
                        "camera_id": camera_id,
                        "error": str(e)
                    })
            
            # === Handle stats request ===
            elif action == "get_stats":
                try:
                    stats = pipeline.get_stats()
                    await websocket.send_json({
                        "camera_id": camera_id,
                        "stats": stats
                    })
                except Exception as e:
                    logger.error(f"Error getting stats: {e}")
    
    except WebSocketDisconnect:
        logger.info(f"❌ WebSocket client disconnected: {client_id}")
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    
    finally:
        if client_id in connected_clients:
            del connected_clients[client_id]


@router.get("/status")
async def websocket_status():
    """Get WebSocket connections status"""
    processor = get_async_processor()
    
    return {
        "connected_clients": len(connected_clients),
        "active_pipelines": len(processor.pipelines),
        "clients": list(connected_clients.keys()),
        "pipelines": processor.get_all_stats(),
        "timestamp": utc_now_naive_iso(),
    }


@router.get("/cameras")
async def get_streaming_cameras():
    """List cameras with active AI pipelines"""
    processor = get_async_processor()
    stats = processor.get_all_stats()
    
    cameras = []
    for camera_id, stat in stats.items():
        cameras.append({
            "id": camera_id,
            "name": stat.get("camera_name", camera_id),
            "frames_processed": stat.get("frames_processed", 0),
            "errors": stat.get("errors", 0),
            "connected": camera_id in [cid.split('_')[0] for cid in connected_clients.keys()]
        })
    
    return {
        "total_cameras": len(cameras),
        "cameras": cameras,
        "timestamp": utc_now_naive_iso(),
    }


@router.post("/broadcast/{event_type}")
async def broadcast_event(event_type: str, payload: dict):
    """
    Broadcast an event to all connected clients
    
    Useful for alerts, notifications, etc.
    """
    try:
        message = {
            "event_type": event_type,
            "payload": payload,
            "timestamp": utc_now_naive_iso(),
        }
        
        disconnected = []
        for client_id, websocket in tuple(connected_clients.items()):
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to {client_id}: {e}")
                disconnected.append(client_id)
        
        # Clean up disconnected clients
        for client_id in disconnected:
            del connected_clients[client_id]
        
        return {
            "status": "broadcasted",
            "clients_notified": len(connected_clients) - len(disconnected),
            "clients_failed": len(disconnected)
        }
    
    except Exception as e:
        logger.error(f"Error broadcasting event: {e}")
        return {"error": str(e)}, 500
