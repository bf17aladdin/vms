# vms/backend/services/camera_capture_service.py - Capture caméra en temps réel

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None

import threading
import logging
from datetime import datetime
from typing import Dict, Optional, Callable
import numpy as np
from queue import Queue
import time

logger = logging.getLogger(__name__)

from .frame_processor import get_frame_processor
from vms.backend.core.config import settings


class CameraCapture:
    """Service de capture en temps réel pour une caméra"""
    
    def __init__(self, camera_id: int, camera_name: str, source = 0):
        """
        Initialiser la capture caméra
        
        Args:
            camera_id: ID de la caméra
            camera_name: Nom de la caméra
            source: URL RTSP ou numéro de webcam (0 pour webcam par défaut)
        """
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.source = source
        
        self.capture = None
        self.is_running = False
        self.thread = None
        
        # File d'attente des frames
        self.frame_queue = Queue(maxsize=5)
        
        # Processeur de frames
        self.frame_processor = get_frame_processor(camera_id, camera_name)
        
        # Statistiques
        self.frames_captured = 0
        self.frames_processed = 0
        self.frames_dropped = 0
        self.fps = 0
        self.last_frame = None
        self.last_frame_time = None
        
        # Callbacks
        self.on_frame_processed: Optional[Callable] = None
    
    def start(self) -> bool:
        """
        Démarrer la capture
        
        Returns:
            True si succès, False sinon
        """
        try:
            # Normalize local webcam sources expressed as strings ("0", "1", "device://0")
            capture_source = self._resolve_capture_source(self.source)

            # Ouvrir la caméra
            self.capture = cv2.VideoCapture(capture_source)
            
            if not self.capture.isOpened():
                logger.error(f"Failed to open camera {self.camera_name} (source: {self.source})")
                return False
            
            # Configurer les propriétés
            self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            target_fps = max(1, int(getattr(settings, "FPS_TARGET", 30)))
            self.capture.set(cv2.CAP_PROP_FPS, target_fps)
            self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Single frame buffer
            
            # Démarrer le thread de capture
            self.is_running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()
            
            logger.info(f"Camera {self.camera_name} capture started")
            return True
        
        except Exception as e:
            logger.error(f"Error starting camera {self.camera_name}: {e}")
            return False

    @staticmethod
    def _resolve_capture_source(source):
        normalized = str(source or "").strip()
        if not normalized:
            return source
        if normalized.isdigit():
            return int(normalized)
        if normalized.lower().startswith("device://"):
            idx = normalized.split("://", 1)[1].strip()
            if idx.isdigit():
                return int(idx)
        return source
    
    def stop(self):
        """Arrêter la capture"""
        self.is_running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        if self.capture:
            self.capture.release()
        
        logger.info(f"Camera {self.camera_name} capture stopped")
    
    def _capture_loop(self):
        """Boucle de capture des frames"""
        frame_time_start = None
        frame_time_count = 0
        
        while self.is_running:
            try:
                # Capturer frame
                ret, frame = self.capture.read()
                
                if not ret or frame is None:
                    logger.warning(f"Failed to read frame from {self.camera_name}")
                    time.sleep(0.1)
                    continue
                
                self.frames_captured += 1
                
                # Ajouter à la file d'attente (ignorer si pleine)
                try:
                    self.frame_queue.put_nowait((frame, datetime.utcnow()))
                    self.last_frame = frame.copy()
                    self.last_frame_time = datetime.utcnow()
                except:
                    self.frames_dropped += 1
                
                # Calculer FPS
                if frame_time_start is None:
                    frame_time_start = datetime.utcnow()
                
                frame_time_count += 1
                elapsed = (datetime.utcnow() - frame_time_start).total_seconds()
                
                if elapsed >= 1.0:
                    self.fps = frame_time_count / elapsed
                    frame_time_start = datetime.utcnow()
                    frame_time_count = 0
                
                # Yield pour permettre au processeur de traiter
                time.sleep(0.001)
            
            except Exception as e:
                logger.error(f"Capture loop error: {e}")
                time.sleep(0.1)
    
    def get_next_frame(self) -> Optional[tuple]:
        """
        Récupérer le prochain frame à traiter
        
        Returns:
            (frame, timestamp) ou None
        """
        try:
            frame, timestamp = self.frame_queue.get(timeout=1)
            return frame, timestamp
        except:
            return None
    
    def process_next_frame(self) -> Optional[Dict]:
        """
        Traiter le prochain frame disponible
        
        Returns:
            Résultats de détection ou None
        """
        frame_data = self.get_next_frame()
        if frame_data is None:
            return None
        
        frame, timestamp = frame_data
        
        try:
            # Traiter le frame
            results = self.frame_processor.process_frame(frame)
            self.frames_processed += 1
            
            # Exécuter callback si fourni
            if self.on_frame_processed:
                self.on_frame_processed(results)
            
            return results
        
        except Exception as e:
            logger.error(f"Frame processing error: {e}")
            return None
    
    def get_statistics(self) -> Dict:
        """Récupérer les statistiques de capture"""
        stats = {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "is_running": self.is_running,
            "frames_captured": self.frames_captured,
            "frames_processed": self.frames_processed,
            "frames_dropped": self.frames_dropped,
            "fps": round(self.fps, 1),
            "last_activity": self.last_frame_time.isoformat() if self.last_frame_time else None
        }
        
        # Ajouter stats du processeur
        processor_stats = self.frame_processor.get_statistics()
        stats["processor"] = processor_stats
        
        return stats
    
    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Récupérer le dernier frame capturé"""
        return self.last_frame.copy() if self.last_frame is not None else None


# Registry global pour les captures
_camera_captures: Dict[int, CameraCapture] = {}


def get_camera_capture(camera_id: int, camera_name: str, source = 0) -> CameraCapture:
    """Obtenir ou créer une capture caméra"""
    if camera_id not in _camera_captures:
        _camera_captures[camera_id] = CameraCapture(camera_id, camera_name, source)
    return _camera_captures[camera_id]


def start_camera(camera_id: int, camera_name: str, source = 0) -> bool:
    """Démarrer une caméra"""
    capture = get_camera_capture(camera_id, camera_name, source)
    return capture.start()


def stop_camera(camera_id: int):
    """Arrêter une caméra"""
    if camera_id in _camera_captures:
        _camera_captures[camera_id].stop()
        del _camera_captures[camera_id]


def stop_all_cameras():
    """Arrêter toutes les caméras"""
    for camera_id in list(_camera_captures.keys()):
        stop_camera(camera_id)
