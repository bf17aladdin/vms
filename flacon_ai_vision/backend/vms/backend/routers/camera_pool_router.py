# vms/backend/routers/camera_pool_router.py - Multi-camera Management (Sprint 2)

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
import logging

from ..services.camera_pool import get_camera_pool
from ..core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cameras/pool", tags=["Camera Pool"])

class RegisterCameraRequest(BaseModel):
    camera_id: int
    name: str
    rtsp_url: str
    max_fps: int = 10
    resolution: str = "720p"  # 1080p, 720p, 480p, etc.

@router.post("/register", summary="Register camera for concurrent processing")
async def register_camera(
    data: RegisterCameraRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Enregistre une caméra pour traitement multi-caméra concurrent
    Utilise ThreadPoolExecutor avec max 4 workers
    
    **Sprint 2**: Multi-camera concurrent processing
    """
    try:
        pool = get_camera_pool()
        
        task = pool.register_camera(camera_id=data.camera_id)
        task.is_active = True
        
        return {
            "status": "success",
            "message": f"Camera {data.camera_id} registered",
            "camera": {
                "id": data.camera_id,
                "name": data.name,
                "rtsp_url": data.rtsp_url,
                "max_fps": data.max_fps,
                "resolution": data.resolution
            }
        }
    except Exception as e:
        logger.error(f"Error registering camera: {e}")
        raise HTTPException(status_code=500, detail="Failed to register camera")

@router.delete("/unregister/{camera_id}", summary="Unregister camera from pool")
async def unregister_camera(
    camera_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Désenregistre une caméra du pool"""
    try:
        pool = get_camera_pool()
        pool.unregister_camera(camera_id)
        
        return {
            "status": "success",
            "message": f"Camera {camera_id} unregistered"
        }
    except Exception as e:
        logger.error(f"Error unregistering camera: {e}")
        raise HTTPException(status_code=500, detail="Failed to unregister camera")

@router.get("/status", summary="Get camera pool status")
async def get_pool_status(current_user: dict = Depends(get_current_user)):
    """Récupère l'état du pool de caméras"""
    try:
        pool = get_camera_pool()
        snapshot = pool.get_pool_status()
        cameras = {
            f"camera_{camera_id}": stats
            for camera_id, stats in snapshot.get("cameras", {}).items()
        }
        
        return {
            "status": "success",
            "pool_config": {
                "max_workers": pool.max_workers,
                "active_workers": snapshot.get("active_cameras", 0),
            },
            "cameras": cameras,
            "total_cameras": snapshot.get("total_cameras", 0),
        }
    except Exception as e:
        logger.error(f"Error fetching pool status: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch status")

@router.get("/cameras", summary="List all registered cameras")
async def list_cameras(current_user: dict = Depends(get_current_user)):
    """Liste toutes les caméras enregistrées"""
    try:
        pool = get_camera_pool()
        
        cameras_list = []
        for camera_id, task in pool.tasks.items():
            cameras_list.append({
                "id": camera_id,
                "name": f"Camera {camera_id}",
                "rtsp_url": None,
                "max_fps": pool.max_fps,
                "is_active": task.is_active,
                "fps": round(task.fps, 2),
                "error_count": task.error_count,
                "frame_count": task.frame_count,
            })
        
        return {
            "status": "success",
            "total": len(cameras_list),
            "cameras": cameras_list
        }
    except Exception as e:
        logger.error(f"Error listing cameras: {e}")
        raise HTTPException(status_code=500, detail="Failed to list cameras")

@router.get("/{camera_id}/stats", summary="Get specific camera statistics")
async def get_camera_stats(
    camera_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Récupère les stats d'une caméra spécifique"""
    try:
        pool = get_camera_pool()
        
        if camera_id not in pool.tasks:
            raise HTTPException(status_code=404, detail="Camera not found")
        
        task = pool.tasks[camera_id]
        
        return {
            "status": "success",
            "camera": {
                "id": camera_id,
                "name": f"Camera {camera_id}",
                "rtsp_url": None,
                "max_fps": pool.max_fps,
                "stats": {
                    "is_active": task.is_active,
                    "fps": round(task.fps, 2),
                    "frame_count": task.frame_count,
                    "error_count": task.error_count,
                }
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching camera stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stats")

@router.post("/{camera_id}/start", summary="Start processing for a camera")
async def start_camera(
    camera_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Démarre le traitement pour une caméra"""
    try:
        pool = get_camera_pool()
        
        if camera_id not in pool.tasks:
            raise HTTPException(status_code=404, detail="Camera not found")
        
        pool.tasks[camera_id].is_active = True
        
        logger.info(f"Camera {camera_id} started")
        
        return {
            "status": "success",
            "message": f"Camera {camera_id} started"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting camera: {e}")
        raise HTTPException(status_code=500, detail="Failed to start camera")

@router.post("/{camera_id}/stop", summary="Stop processing for a camera")
async def stop_camera(
    camera_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Arrête le traitement pour une caméra"""
    try:
        pool = get_camera_pool()
        
        if camera_id not in pool.tasks:
            raise HTTPException(status_code=404, detail="Camera not found")
        
        pool.tasks[camera_id].is_active = False
        
        logger.info(f"Camera {camera_id} stopped")
        
        return {
            "status": "success",
            "message": f"Camera {camera_id} stopped"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping camera: {e}")
        raise HTTPException(status_code=500, detail="Failed to stop camera")

@router.get("/performance/metrics", summary="Get pool performance metrics")
async def get_performance_metrics(current_user: dict = Depends(get_current_user)):
    """Métriques de performance du pool"""
    try:
        pool = get_camera_pool()
        
        total_fps = 0
        active_count = 0
        total_errors = 0
        
        for task in pool.tasks.values():
            if task.is_active:
                active_count += 1
                total_fps += task.fps
            total_errors += task.error_count
        
        return {
            "status": "success",
            "metrics": {
                "total_cameras": len(pool.tasks),
                "active_cameras": active_count,
                "total_fps": round(total_fps, 2),
                "max_workers": pool.max_workers,
                "total_errors": total_errors
            }
        }
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")
