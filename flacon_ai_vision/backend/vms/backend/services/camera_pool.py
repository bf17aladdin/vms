# vms/backend/services/camera_pool.py - Multi-camera concurrent management (Sprint 2)

import asyncio
import threading
from typing import Dict, List, Optional
from datetime import datetime
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

@dataclass
class CameraTask:
    """Représente une tâche de traitement de caméra"""
    camera_id: int
    frame_count: int = 0
    last_frame_time: datetime = field(default_factory=datetime.now)
    fps: float = 0.0
    is_active: bool = True
    error_count: int = 0

class CameraPool:
    """
    Gère le traitement concurrent de multiples caméras
    avec équilibrage de charge et gestion des ressources.
    
    **Sprint 2 Deliverable**: Multi-camera concurrent processing
    """
    
    def __init__(self, max_workers: int = 4, max_fps_per_camera: int = 10):
        """
        Initialize camera pool
        
        Args:
            max_workers: Nombre max de threads parallèles (pour 3-4 caméras: 4)
            max_fps_per_camera: FPS max par caméra (pour 2m/3m: 10 FPS suffisant)
        """
        self.max_workers = max_workers
        self.max_fps = max_fps_per_camera
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tasks: Dict[int, CameraTask] = {}
        self.active_streams: Dict[int, any] = {}  # {camera_id: stream_obj}
        self.frame_buffer: Dict[int, any] = {}  # {camera_id: latest_frame}
        self.lock = threading.Lock()
    
    def register_camera(self, camera_id: int) -> CameraTask:
        """Enregistrer une caméra dans le pool"""
        with self.lock:
            if camera_id not in self.tasks:
                self.tasks[camera_id] = CameraTask(camera_id=camera_id)
                logger.info(f"✓ Camera {camera_id} registered to pool")
            return self.tasks[camera_id]
    
    def unregister_camera(self, camera_id: int):
        """Retirer une caméra du pool"""
        with self.lock:
            if camera_id in self.tasks:
                self.tasks[camera_id].is_active = False
                if camera_id in self.active_streams:
                    self.active_streams[camera_id].stop()
                    del self.active_streams[camera_id]
                del self.tasks[camera_id]
                logger.info(f"✓ Camera {camera_id} unregistered from pool")
    
    async def process_frame_batch(self, camera_frames: Dict[int, any]) -> Dict[int, dict]:
        """
        Traiter les frames de multiple caméras en parallèle
        
        Args:
            camera_frames: {camera_id: frame_obj}
        
        Returns:
            {camera_id: {'detections': [...], 'fps': 10.5, ...}}
        """
        loop = asyncio.get_event_loop()
        tasks = []
        
        for camera_id, frame in camera_frames.items():
            if camera_id in self.tasks and self.tasks[camera_id].is_active:
                task = loop.run_in_executor(
                    self.executor,
                    self._process_single_camera,
                    camera_id,
                    frame
                )
                tasks.append(task)
        
        # Attendre tous les résultats (avec timeout)
        try:
            results = await asyncio.gather(*tasks, timeout=5.0)
            return {r['camera_id']: r for r in results}
        except asyncio.TimeoutError:
            logger.warning("⚠️ Camera processing timeout - some frames dropped")
            return {}
    
    def _process_single_camera(self, camera_id: int, frame: any) -> dict:
        """Traiter une seule caméra (thread-safe)"""
        try:
            # Simulé: en produit, appeler frame_processor.process_frame()
            task = self.tasks.get(camera_id)
            if not task:
                return {'camera_id': camera_id, 'error': 'Camera not found'}
            
            # Mettre à jour stats
            task.frame_count += 1
            now = datetime.now()
            elapsed = (now - task.last_frame_time).total_seconds()
            if elapsed > 0:
                task.fps = 1.0 / elapsed
            task.last_frame_time = now
            
            # Stocker le dernier frame
            with self.lock:
                self.frame_buffer[camera_id] = frame
            
            return {
                'camera_id': camera_id,
                'frame_count': task.frame_count,
                'fps': round(task.fps, 2),
                'status': 'ok'
            }
        except Exception as e:
            logger.error(f"❌ Error processing camera {camera_id}: {e}")
            if camera_id in self.tasks:
                self.tasks[camera_id].error_count += 1
            return {'camera_id': camera_id, 'error': str(e)}
    
    def get_pool_status(self) -> dict:
        """Retourner le statut du pool"""
        with self.lock:
            cameras_status = {
                cid: {
                    'frame_count': task.frame_count,
                    'fps': round(task.fps, 2),
                    'error_count': task.error_count,
                    'is_active': task.is_active
                }
                for cid, task in self.tasks.items()
            }
        
        return {
            'active_cameras': len([t for t in self.tasks.values() if t.is_active]),
            'total_cameras': len(self.tasks),
            'max_workers': self.max_workers,
            'cameras': cameras_status
        }
    
    def get_latest_frame(self, camera_id: int) -> Optional[any]:
        """Récupérer le dernier frame d'une caméra"""
        with self.lock:
            return self.frame_buffer.get(camera_id)
    
    def shutdown(self):
        """Arrêter le pool"""
        for camera_id in list(self.tasks.keys()):
            self.unregister_camera(camera_id)
        self.executor.shutdown(wait=True)
        logger.info("✓ Camera pool shutdown complete")

# Instance globale du pool
_pool: Optional[CameraPool] = None

def get_camera_pool() -> CameraPool:
    """Get or create global camera pool"""
    global _pool
    if _pool is None:
        _pool = CameraPool(max_workers=4)
    return _pool
