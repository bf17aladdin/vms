# vms/backend/routers/realtime_router.py - WebSocket Real-time Events (Sprint 5)

from fastapi import APIRouter, WebSocket, Depends, HTTPException, WebSocketDisconnect
from typing import List
import logging
import json

from ..core.realtime_manager import get_realtime_manager
from ..core.security import authenticate_websocket, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/realtime", tags=["Real-time"])

@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket endpoint pour événements temps réel
    Clients connectés reçoivent: détections personnel/véhicule, anomalies, alertes
    
    **Sprint 5**: Real-time WebSocket events
    
    Usage:
        ws = new WebSocket('ws://localhost:5001/api/realtime/ws/events')
        ws.onmessage = (event) => console.log(JSON.parse(event.data))
    """
    current_user = await authenticate_websocket(websocket)
    if current_user is None:
        return

    await websocket.accept()
    manager = get_realtime_manager()
    
    try:
        # Enregistrer la connexion
        await manager.connect(websocket)
        logger.info(f"✓ WebSocket client connected (total: {len(manager.active_connections)})")
        
        # Envoyer les 50 derniers événements au nouveau client
        recent_events = manager.event_history[-50:] if manager.event_history else []
        for event in recent_events:
            replayed_event = dict(event)
            replayed_event["replayed"] = True
            await websocket.send_json(replayed_event)
        
        # Maintenir la connexion ouverte
        while True:
            data = await websocket.receive_text()
            # Clients peuvent envoyer des messages (keep-alive ou commandes futures)
            logger.debug(f"WebSocket message received: {data[:100]}")
    
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
        logger.info(f"✓ WebSocket client disconnected (total: {len(manager.active_connections)})")
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect(websocket)
        raise

@router.get("/health", summary="Check realtime manager health")
async def realtime_health(current_user: dict = Depends(get_current_user)):
    """Vérifier l'état du gestionnaire temps réel"""
    try:
        manager = get_realtime_manager()
        return {
            "status": "healthy",
            "active_connections": len(manager.active_connections),
            "event_history_size": len(manager.event_history),
            "max_history": 1000
        }
    except Exception as e:
        logger.error(f"Error checking health: {e}")
        raise HTTPException(status_code=500, detail="Realtime manager not available")

@router.get("/events", summary="Get recent events history")
async def get_event_history(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Récupère les N derniers événements"""
    try:
        manager = get_realtime_manager()
        events = manager.event_history[-limit:] if manager.event_history else []
        return {
            "status": "success",
            "total": len(manager.event_history),
            "returned": len(events),
            "events": events
        }
    except Exception as e:
        logger.error(f"Error fetching events: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch events")

@router.get("/stats", summary="Get realtime statistics")
async def get_realtime_stats(current_user: dict = Depends(get_current_user)):
    """Statistiques temps réel"""
    try:
        manager = get_realtime_manager()
        
        # Compter events par type
        event_types = {}
        for event in manager.event_history:
            event_type = event.get('type', 'unknown')
            event_types[event_type] = event_types.get(event_type, 0) + 1
        
        return {
            "status": "success",
            "active_connections": len(manager.active_connections),
            "total_events_buffered": len(manager.event_history),
            "events_by_type": event_types
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stats")

@router.post("/test-broadcast", summary="[DEBUG] Test broadcast to all clients")
async def test_broadcast(
    message: str = "Test notification",
    current_user: dict = Depends(get_current_user)
):
    """[DEBUG] Envoie un message de test à tous les clients connectés"""
    try:
        manager = get_realtime_manager()
        
        # Créer événement test
        test_event = {
            "type": "system_alert",
            "message": message,
            "source": "admin_test",
            "timestamp": str(json.dumps({'debug': True}))
        }
        
        # Broadcast
        await manager.broadcast_alert(
            title="Test Alert",
            message=message,
            severity="info"
        )
        
        return {
            "status": "success",
            "broadcast_to": len(manager.active_connections),
            "message": message
        }
    except Exception as e:
        logger.error(f"Error broadcasting test: {e}")
        raise HTTPException(status_code=500, detail="Failed to broadcast")

@router.post("/clear-history", summary="Clear event history")
async def clear_history(current_user: dict = Depends(get_current_user)):
    """Efface l'historique des événements"""
    try:
        manager = get_realtime_manager()
        old_size = len(manager.event_history)
        manager.event_history = []
        
        logger.info(f"Event history cleared: {old_size} events removed")
        return {
            "status": "success",
            "message": f"Cleared {old_size} events"
        }
    except Exception as e:
        logger.error(f"Error clearing history: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear history")
