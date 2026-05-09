# vms/backend/ai/objects.py - Détection d'objets avec YOLO v8/v9

import numpy as np
import os
from typing import Dict, List, Optional, Tuple
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# Chargement optionnel de ultralytics
try:
    from ultralytics import YOLO
    HAS_YOLO = True
except ImportError:
    HAS_YOLO = False
    logger.warning("⚠️ ultralytics not installed (pip install ultralytics)")
    YOLO = None


class ObjectDetector:
    """
    Détecteur d'objets avec YOLO (v8, v8-seg, v9)
    - Support CPU et GPU
    - Caching de modèles
    - Classe filtering
    - Confidence + NMS tuning
    """
    
    # Modèles disponibles (à télécharger automatiquement)
    AVAILABLE_MODELS = {
        'yolov8n': 'nano (fast, low memory)',
        'yolov8s': 'small (balanced)',
        'yolov8m': 'medium (standard)',
        'yolov8l': 'large (better accuracy)',
        'yolov8x': 'xlarge (best accuracy, needs GPU)'
    }
    
    _model_cache = {}  # Cache global des modèles
    
    def __init__(
        self,
        model_name: str = "yolov8n",
        confidence_threshold: float = 0.5,
        iou_threshold: float = 0.45,
        device: Optional[str] = None
    ):
        """
        Args:
            model_name: 'yolov8n' (nano - CPU rapide) à 'yolov8x' (xlarge - GPU)
            confidence_threshold: 0.3-0.9 (0.5 = bon compromis)
            iou_threshold: 0.3-0.7 (0.45 = standard)
            device: 'cpu', 'cuda', ou None (auto-détect)
        """
        self.model_name = model_name
        self.confidence_threshold = confidence_threshold
        self.iou_threshold = iou_threshold
        self.device = device or self._auto_detect_device()
        self.model = None
        self.available = HAS_YOLO
        
        if self.available:
            self._load_model()
        else:
            logger.warning(f"YOLO not available, detector disabled")
    
    @staticmethod
    def _auto_detect_device() -> str:
        """Auto-detect GPU/CPU with environment overrides."""
        forced_device = os.getenv("AI_DEVICE", "").strip()
        forced_gpu_index = os.getenv("AI_GPU_INDEX", "").strip()

        if forced_device:
            if forced_device.startswith("cuda"):
                try:
                    import torch
                    if not torch.cuda.is_available():
                        logger.warning(
                            "AI_DEVICE=%s set but CUDA is not available, using CPU",
                            forced_device,
                        )
                        return "cpu"
                except Exception:
                    logger.warning(
                        "AI_DEVICE=%s set but torch.cuda check failed, using CPU",
                        forced_device,
                    )
                    return "cpu"
            logger.info("Using configured AI_DEVICE=%s", forced_device)
            return forced_device

        if HAS_YOLO:
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    if forced_gpu_index:
                        device = "cuda:" + forced_gpu_index
                    logger.info("CUDA GPU detected, using %s", device)
                    return device
            except Exception:
                pass

        logger.info("Using CPU for inference")
        return "cpu"
    
    def _load_model(self):
        """Charger ou réutiliser le modèle depuis cache"""
        cache_key = (self.model_name, self.device)
        
        if cache_key in ObjectDetector._model_cache:
            self.model = ObjectDetector._model_cache[cache_key]
            logger.info(f"✅ Model {self.model_name} loaded from cache")
            return
        
        try:
            logger.info(f"📦 Loading YOLO model {self.model_name} on {self.device}...")
            self.model = YOLO(f"{self.model_name}.pt")
            self.model.to(self.device)
            
            # Cache pour les réutilisations futures
            ObjectDetector._model_cache[cache_key] = self.model
            logger.info(f"✅ Model {self.model_name} loaded successfully")
        except Exception as e:
            logger.error(f"❌ Failed to load model {self.model_name}: {e}")
            self.model = None
            self.available = False
    
    def detect(self, frame: np.ndarray) -> Dict:
        """
        Détecter les objets dans une image
        
        Args:
            frame: np.ndarray (BGR)
        
        Returns:
            {
                'objects': [...],
                'timestamp': datetime.now().isoformat(),
                'frame_shape': (H, W, C),
                'processing_time_ms': float,
                'detections_count': int
            }
        """
        start = time.time()
        
        if not self.available or self.model is None:
            return self._empty_result(frame, "Model not available")
        
        try:
            # Inférence YOLO
            results = self.model(
                frame,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                verbose=False
            )
            
            objects = []
            
            if results and len(results) > 0:
                result = results[0]
                
                # Parcourir les détections
                for box in result.boxes:
                    xyxy = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    
                    x1, y1, x2, y2 = xyxy
                    x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)
                    
                    class_name = (
                        result.names[cls_id] if result.names and cls_id < len(result.names)
                        else f"class_{cls_id}"
                    )
                    
                    h_img, w_img = frame.shape[:2]
                    bbox_norm = [x / w_img, y / h_img, (x + w) / w_img, (y + h) / h_img]
                    
                    objects.append({
                        'class': class_name,
                        'class_id': cls_id,
                        'confidence': float(conf),
                        'bbox': {'x': x, 'y': y, 'w': w, 'h': h},
                        'bbox_norm': bbox_norm
                    })
            
            return {
                'objects': objects,
                'timestamp': datetime.now().isoformat(),
                'frame_shape': frame.shape,
                'processing_time_ms': float((time.time() - start) * 1000),
                'detections_count': len(objects)
            }
            
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return self._empty_result(frame, str(e))
    
    def detect_batch(self, frames: List[np.ndarray]) -> List[Dict]:
        """Détecter dans un batch d'images (optimisé GPU)"""
        if not self.available or self.model is None:
            return [self._empty_result(f, "Model not available") for f in frames]
        
        start = time.time()
        
        try:
            results = self.model(
                frames,
                conf=self.confidence_threshold,
                iou=self.iou_threshold,
                verbose=False
            )
            
            batch_results = []
            
            for frame, result in zip(frames, results):
                objects = []
                
                if result.boxes:
                    for box in result.boxes:
                        xyxy = box.xyxy[0].tolist()
                        conf = float(box.conf[0])
                        cls_id = int(box.cls[0])
                        
                        x1, y1, x2, y2 = xyxy
                        x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)
                        
                        class_name = (
                            result.names[cls_id] if result.names and cls_id < len(result.names)
                            else f"class_{cls_id}"
                        )
                        
                        h_img, w_img = frame.shape[:2]
                        bbox_norm = [x / w_img, y / h_img, (x + w) / w_img, (y + h) / h_img]
                        
                        objects.append({
                            'class': class_name,
                            'class_id': cls_id,
                            'confidence': float(conf),
                            'bbox': {'x': x, 'y': y, 'w': w, 'h': h},
                            'bbox_norm': bbox_norm
                        })
                
                batch_results.append({
                    'objects': objects,
                    'frame_shape': frame.shape,
                    'detections_count': len(objects)
                })
            
            logger.info(f"Batch processed: {len(frames)} frames in {(time.time() - start)*1000:.1f}ms")
            return batch_results
            
        except Exception as e:
            logger.error(f"Batch detection error: {e}")
            return [self._empty_result(f, str(e)) for f in frames]
    
    def filter_by_class(self, objects: List[Dict], classes: List[str]) -> List[Dict]:
        """Filtrer les objets par classe"""
        return [obj for obj in objects if obj['class'] in classes]
    
    def filter_by_confidence(self, objects: List[Dict], min_conf: float) -> List[Dict]:
        """Filtrer par score de confiance minimum"""
        return [obj for obj in objects if obj['confidence'] >= min_conf]
    
    @staticmethod
    def _empty_result(frame: np.ndarray, error: Optional[str] = None) -> Dict:
        """Retourner un résultat vide (pas de détections)"""
        return {
            'objects': [],
            'timestamp': datetime.now().isoformat(),
            'frame_shape': frame.shape,
            'processing_time_ms': 0.0,
            'detections_count': 0,
            'error': error
        }
    
    @staticmethod
    def get_available_models() -> Dict[str, str]:
        """Retourner les modèles disponibles"""
        return ObjectDetector.AVAILABLE_MODELS

