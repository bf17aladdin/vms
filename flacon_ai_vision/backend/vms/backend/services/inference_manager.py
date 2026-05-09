"""
Gestionnaire d'inférence pour multi-caméras en temps réel
- Scheduling intelligent des détections
- Batching GPU
- Caching de modèles
- Fallback CPU si nécessaire
"""

import asyncio
import logging
import os
import time
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from datetime import datetime
import threading

logger = logging.getLogger("falcon_ai_vision.inference")

from vms.backend.ai.motion import MotionDetector
from vms.backend.ai.objects import ObjectDetector
from vms.backend.core.config import settings


class InferenceManager:
    """
    Gestionnaire centralisé d'inférence
    - Une instance par système (singleton pattern)
    - Partagé entre tous les flux caméras
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # Détecteurs partagés (singleton)
        self.motion_detectors: Dict[int, MotionDetector] = {}
        self.object_detector: Optional[ObjectDetector] = None
        
        # Concurrency limits and timeouts
        self._max_concurrent_jobs = max(1, int(getattr(settings, "MAX_GPU_JOBS", 2)))
        self._object_timeout_sec = max(0.1, float(getattr(settings, "AI_OBJECT_TIMEOUT_SEC", 4.0)))
        self._motion_timeout_sec = max(0.1, float(getattr(settings, "AI_MOTION_TIMEOUT_SEC", 4.0)))
        self._object_retry = max(0, int(getattr(settings, "AI_OBJECT_RETRY", 1)))
        self._motion_retry = max(0, int(getattr(settings, "AI_MOTION_RETRY", 1)))
        self._semaphore_lock = threading.Lock()
        self._loop_semaphores: Dict[int, asyncio.Semaphore] = {}

        # Thread pool pour inférences asynchrones
        self.executor = ThreadPoolExecutor(
            max_workers=max(2, int(self._max_concurrent_jobs)),
            thread_name_prefix="inference_"
        )

        # Queues d'inférence par caméra (priorité FIFO + timeout)
        self.inference_queues: Dict[int, asyncio.Queue] = {}
        
        # Statistiques
        self.stats = {
            'frames_processed': 0,
            'detections_total': 0,
            'avg_latency_ms': 0.0,
            'fps_actual': 0.0
        }
        
        self._init_detector_models()
    
    def _init_detector_models(self):
        """Initialiser les modeles au demarrage."""
        try:
            configured_device = os.getenv("AI_DEVICE", "").strip() or None

            # Object detection (YOLO)
            logger.info("Initializing object detector (YOLO)...")
            self.object_detector = ObjectDetector(
                model_name="yolov8n",  # nano for fast inference
                confidence_threshold=0.5,
                device=configured_device,  # None => auto detect in ObjectDetector
            )
            logger.info("Object detector initialized on device: %s", self.object_detector.device)
        except Exception as e:
            logger.error(f"Failed to init object detector: {e}")
            self.object_detector = None

    def _get_loop_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_event_loop()
        key = id(loop)
        with self._semaphore_lock:
            sem = self._loop_semaphores.get(key)
            if sem is None:
                sem = asyncio.Semaphore(self._max_concurrent_jobs)
                self._loop_semaphores[key] = sem
        return sem

    async def _run_with_limits(
        self,
        func,
        args: Tuple,
        *,
        timeout_sec: float,
        retries: int,
        job_name: str,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        attempts = max(1, int(retries) + 1)
        loop = asyncio.get_event_loop()
        last_error: Optional[str] = None

        for attempt in range(1, attempts + 1):
            semaphore = self._get_loop_semaphore()
            await semaphore.acquire()
            future = loop.run_in_executor(self.executor, func, *args)
            future.add_done_callback(lambda _f, sem=semaphore: sem.release())
            try:
                result = await asyncio.wait_for(future, timeout=timeout_sec)
                return result, None
            except asyncio.TimeoutError:
                last_error = f"{job_name}_timeout"
                logger.warning("%s inference timeout (attempt %s/%s)", job_name, attempt, attempts)
            except Exception as exc:
                last_error = f"{job_name}_error:{exc}"
                logger.warning("%s inference error (attempt %s/%s): %s", job_name, attempt, attempts, exc)

        return None, last_error

    @staticmethod
    def _empty_motion_result(error: Optional[str] = None) -> Dict:
        return {
            "motion_detected": False,
            "confidence": 0.0,
            "regions": [],
            "coverage": 0.0,
            "processing_time_ms": 0.0,
            "error": error,
        }

    @staticmethod
    def _empty_objects_result(frame: Optional[np.ndarray], error: Optional[str] = None) -> Dict:
        shape = frame.shape if hasattr(frame, "shape") else None
        return {
            "objects": [],
            "timestamp": datetime.utcnow().isoformat(),
            "frame_shape": shape,
            "processing_time_ms": 0.0,
            "detections_count": 0,
            "error": error,
        }
    
    def get_motion_detector(self, camera_id: int) -> MotionDetector:
        """Récupérer ou créer un détecteur de mouvement par caméra"""
        if camera_id not in self.motion_detectors:
            self.motion_detectors[camera_id] = MotionDetector(
                sensitivity=50,
                min_area=500
            )
        return self.motion_detectors[camera_id]
    
    async def detect_objects_async(
        self,
        frame: np.ndarray,
        camera_id: int
    ) -> Dict:
        """
        Inférence async - utilise thread pool pour ne pas bloquer l'event loop
        
        Args:
            frame: np.ndarray (BGR)
            camera_id: ID caméra (pour logs/monitoring)
        
        Returns:
            Dict de résultats de détection
        """
        if self.object_detector is None or not self.object_detector.available:
            return self._empty_objects_result(frame, "detector_unavailable")

        result, error = await self._run_with_limits(
            self.object_detector.detect,
            (frame,),
            timeout_sec=self._object_timeout_sec,
            retries=self._object_retry,
            job_name="object",
        )
        if error:
            return self._empty_objects_result(frame, error)
        return result or self._empty_objects_result(frame, "object_inference_failed")
    
    async def detect_motion_async(
        self,
        frame: np.ndarray,
        camera_id: int
    ) -> Dict:
        """Détection de mouvement async"""
        detector = self.get_motion_detector(camera_id)
        result, error = await self._run_with_limits(
            detector.detect,
            (frame,),
            timeout_sec=self._motion_timeout_sec,
            retries=self._motion_retry,
            job_name="motion",
        )
        if error:
            return self._empty_motion_result(error)
        return result or self._empty_motion_result("motion_inference_failed")
    
    async def detect_batch_objects_async(
        self,
        frames: List[Tuple[int, np.ndarray]]  # [(camera_id, frame), ...]
    ) -> List[Dict]:
        """
        Traitement batch optimisé pour GPU
        - Regroupe les images par résolution
        - Applique YOLO batch inference
        """
        if self.object_detector is None:
            return [self._empty_objects_result(frame, "detector_unavailable") for _, frame in frames]

        image_list = [f[1] for f in frames]
        result, error = await self._run_with_limits(
            self.object_detector.detect_batch,
            (image_list,),
            timeout_sec=self._object_timeout_sec,
            retries=self._object_retry,
            job_name="batch_object",
        )
        if error or result is None:
            return [self._empty_objects_result(frame, error or "batch_inference_failed") for _, frame in frames]

        for (camera_id, _), row in zip(frames, result):
            row["camera_id"] = camera_id

        return result

    def get_statistics(self) -> Dict:
        """Retourner les statistiques d'inférence"""
        return self.stats.copy()
    
    def shutdown(self):
        """Arrêter le gestionnaire proprement"""
        self.executor.shutdown(wait=True)
        logger.info("✅ InferenceManager shutdown complete")


# Instance singleton global
_inference_manager: Optional[InferenceManager] = None

def get_inference_manager() -> InferenceManager:
    """Récupérer l'instance singleton du gestionnaire d'inférence"""
    global _inference_manager
    if _inference_manager is None:
        _inference_manager = InferenceManager()
    return _inference_manager

