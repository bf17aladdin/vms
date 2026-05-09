#!/usr/bin/env python3
"""
Wrapper d'intégration pour utiliser process_frame_async dans les routers websocket
et les pipelines RTSP
"""

import asyncio
import logging
from typing import Dict, Optional
from sqlalchemy.orm import Session
import numpy as np
from collections import deque
import time

from vms.backend.services.frame_processor import FrameProcessor

logger = logging.getLogger(__name__)


class AsyncFrameProcessingPipeline:
    """
    Pipeline de traitement async pour intégration dans FastAPI WebSocket
    et handlers RTSP stream
    """
    
    def __init__(self, camera_id: str, camera_name: str, max_queue_size: int = 10):
        """
        Initialiser le pipeline async
        
        Args:
            camera_id: ID unique de la caméra
            camera_name: Nom d'affichage de la caméra
            max_queue_size: Taille maximale de la queue pour éviter accumulation mémoire
        """
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.frame_processor = FrameProcessor(camera_id, camera_name)
        self.last_frame_time = None
        self.frames_processed = 0
        self.errors = 0
        self.frames_dropped = 0
        self.max_queue_size = max_queue_size
        self.frame_queue = deque(maxlen=max_queue_size)
        self.processing_lock = asyncio.Lock()
    
    async def process_frame(
        self, 
        frame: np.ndarray, 
        db: Optional[Session] = None
    ) -> Dict:
        """
        Traiter un frame de manière async avec gestion de queue limitée
        
        Args:
            frame: Frame OpenCV BGR (numpy array)
            db: Session SQLAlchemy (optional)
        
        Returns:
            Dict avec résultats de toutes les détections
        """
        # Check queue size to prevent memory accumulation
        if len(self.frame_queue) >= self.max_queue_size:
            self.frames_dropped += 1
            logger.warning(f"Frame queue full for camera {self.camera_id}, dropping frame. Dropped: {self.frames_dropped}")
            return {
                "camera_id": self.camera_id,
                "status": "dropped",
                "reason": "queue_full",
                "frames_dropped": self.frames_dropped,
                "pipeline_metadata": {
                    "queue_size": len(self.frame_queue),
                    "max_queue_size": self.max_queue_size
                }
            }
        
        # Add frame to queue with timestamp
        frame_data = {
            "frame": frame.copy(),  # Copy to avoid reference issues
            "timestamp": time.time(),
            "db": db
        }
        self.frame_queue.append(frame_data)
        
        # Process the frame
        async with self.processing_lock:
            try:
                current_frame_data = self.frame_queue.popleft()
                frame_to_process = current_frame_data["frame"]
                frame_timestamp = current_frame_data["timestamp"]
                db_session = current_frame_data["db"]
                
                self.frames_processed += 1
                result = await self.frame_processor.process_frame_async(frame_to_process, db=db_session)
                
                # Add pipeline metadata
                result["pipeline_metadata"] = {
                    "camera_id": self.camera_id,
                    "camera_name": self.camera_name,
                    "frames_processed": self.frames_processed,
                    "frames_dropped": self.frames_dropped,
                    "queue_size": len(self.frame_queue),
                    "max_queue_size": self.max_queue_size,
                    "processing_time_ms": result.get('latency_ms', 0),
                    "queue_wait_time_ms": (time.time() - frame_timestamp) * 1000
                }
                
                return result
                
            except Exception as e:
                self.errors += 1
                logger.error(f"Error processing frame on camera {self.camera_id}: {e}")
                return {
                    "camera_id": self.camera_id,
                    "error": str(e),
                    "frames_processed": self.frames_processed,
                    "frames_dropped": self.frames_dropped,
                    "pipeline_metadata": {
                        "error_count": self.errors,
                        "queue_size": len(self.frame_queue)
                    }
                }
    
    def get_stats(self) -> Dict:
        """
        Obtenir les statistiques du pipeline
        
        Returns:
            Dict avec statistiques
        """
        return {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "frames_processed": self.frames_processed,
            "errors": self.errors,
            "error_rate": f"{(self.errors / max(self.frames_processed, 1)) * 100:.2f}%"
        }


class MultiCameraAsyncProcessor:
    """
    Gestionnaire pour traiter plusieurs caméras en parallèle
    """
    
    def __init__(self):
        self.pipelines: Dict[str, AsyncFrameProcessingPipeline] = {}
    
    def add_camera(self, camera_id: str, camera_name: str):
        """Ajouter une caméra au processeur"""
        if camera_id not in self.pipelines:
            self.pipelines[camera_id] = AsyncFrameProcessingPipeline(camera_id, camera_name)
            logger.info(f"Added camera {camera_id} ({camera_name}) to async processor")
    
    async def process_frames_parallel(
        self,
        frames: Dict[str, np.ndarray],
        db: Optional[Session] = None
    ) -> Dict[str, Dict]:
        """
        Traiter les frames de plusieurs caméras en parallèle
        
        Args:
            frames: Dict {camera_id: frame_array}
            db: Session SQLAlchemy
        
        Returns:
            Dict {camera_id: detection_results}
        """
        tasks = []
        camera_ids = []
        
        for camera_id, frame in frames.items():
            if camera_id in self.pipelines:
                pipeline = self.pipelines[camera_id]
                tasks.append(pipeline.process_frame(frame, db=db))
                camera_ids.append(camera_id)
        
        if not tasks:
            return {}
        
        # Run all processing tasks concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Map results back to camera IDs
        return {
            camera_id: result if not isinstance(result, Exception) else {"error": str(result)}
            for camera_id, result in zip(camera_ids, results)
        }
    
    def get_all_stats(self) -> Dict:
        """Obtenir les stats de toutes les caméras"""
        return {
            camera_id: pipeline.get_stats()
            for camera_id, pipeline in self.pipelines.items()
        }


# Global instance
_global_processor: Optional[MultiCameraAsyncProcessor] = None


def get_async_processor() -> MultiCameraAsyncProcessor:
    """
    Obtenir l'instance globale du processeur async
    Factory function pour garantir une seule instance
    """
    global _global_processor
    if _global_processor is None:
        _global_processor = MultiCameraAsyncProcessor()
    return _global_processor


def get_pipeline(camera_id: str, camera_name: str) -> AsyncFrameProcessingPipeline:
    """
    Obtenir ou créer un pipeline pour une caméra
    """
    processor = get_async_processor()
    if camera_id not in processor.pipelines:
        processor.add_camera(camera_id, camera_name)
    return processor.pipelines[camera_id]


# Example usage for WebSocket handler
"""
@sio.on('connect')
def handle_connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.on('stream_frame')
async def handle_stream_frame(sid, data):
    # data['camera_id'], data['camera_name'], data['frame'] (base64 encoded)
    
    import base64
    frame_bytes = base64.b64decode(data['frame'])
    frame = np.frombuffer(frame_bytes, dtype=np.uint8).reshape(data['height'], data['width'], 3)
    
    pipeline = get_pipeline(data['camera_id'], data['camera_name'])
    result = await pipeline.process_frame(frame)
    
    await sio.emit('detection_result', result, to=sid)
"""
