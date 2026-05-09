# 🚀 AI Production Integration Roadmap – Falcon AI Vision

**Objectif**: Passer d'une architecture POC à une solution **100% production-ready** avec validation complète.

**Durée estimée**: 3-5 jours de développement intensif  
**Progress Tracking**: [Suivre ci-dessous](#progress-tracking)

---

## 📋 Executive Summary

Votre projet dispose d'une **excellente fondation** (FastAPI, DB, auth, routers). Trois tâches blocantes à accomplir:

1. **Implémenter les détecteurs réels**
   - Motion Detection avec OpenCV (MOG2, KNN, ou optique stationnaire)
   - Object Detection avec YOLO v8/v9 (person, car, truck, etc.)
   - Face Recognition avec encodings stockés (déjà partiellement fait)

2. **Optimiser le pipeline d'inférence**
   - Multi-threading/async pour multi-caméras
   - Batching d'images pour GPU efficace
   - Caching de modèles et NMS
   - Fallback CPU/GPU intelligent

3. **Valider et déployer**
   - Tests de charge multi-caméras (2, 4, 8 flux simultanés)
   - Benchmarks de latence (FPS réel, détection/sec)
   - Monitoring en production
   - Documentation déploiement

---

## ✅ Phase 1: Real AI Model Implementation (Jour 1-2)

### 1.1 Motion Detection – Réimplémentation avec OpenCV

**Fichier**: `vms/backend/ai/motion.py`

```python
# NOUVEAU: Détection de mouvement avec OpenCV MOG2

import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class MotionDetector:
    """
    Détection de mouvement avec algorithme MOG2 (Mixture of Gaussians)
    - Adaptatif
    - Supprime les bruits (ombres, illumination)
    - ~10ms par frame 720p sur CPU
    """
    
    def __init__(self, sensitivity: int = 50, min_area: int = 500):
        """
        Args:
            sensitivity: 0-100, défaut 50 (algo KNN à 100, MOG2 à <50)
            min_area: pixels min pour une région valide
        """
        self.sensitivity = sensitivity
        self.min_area = min_area
        self.threshold = (100 - sensitivity) / 100.0 * 20 + 5  # 5-25
        
        # Initialiser le modèle de soustraction de fond
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            detectShadows=True,
            varThreshold=self.threshold
        )
        self.initialized = False
        self.frame_count = 0
    
    def detect(self, frame: np.ndarray, background_frame: Optional[np.ndarray] = None) -> Dict:
        """
        Détecter le mouvement dans une image
        
        Args:
            frame: np.ndarray (BGR ou Gray)
            background_frame: frame de référence (ignoré avec MOG2)
        
        Returns:
            {
                'motion_detected': bool,
                'confidence': float (0-1),
                'regions': [{'x': int, 'y': int, 'w': int, 'h': int, 'area': int}],
                'coverage': float (% de l'image),
                'processing_time_ms': float
            }
        """
        import time
        start = time.time()
        
        try:
            # Gérer les formats d'entrée
            if len(frame.shape) == 2:  # Grayscale
                working_frame = frame
            else:  # Color
                working_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # Appliquer le soustracteur de fond
            fg_mask = self.bg_subtractor.apply(working_frame)
            
            # Appliquer un morphological closing pour réduire le bruit
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            
            # Trouver les contours
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filtrer les régions valides
            regions = []
            total_area = 0
            image_area = working_frame.shape[0] * working_frame.shape[1]
            
            for contour in contours:
                area = cv2.contourArea(contour)
                if area >= self.min_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    regions.append({
                        'x': int(x),
                        'y': int(y),
                        'w': int(w),
                        'h': int(h),
                        'area': int(area)
                    })
                    total_area += area
            
            # Calculer les statistiques
            coverage = (total_area / image_area) * 100
            motion_detected = len(regions) > 0 and coverage > 0.5  # >0.5% de couverture
            confidence = min(coverage / 50.0, 1.0)  # Saturation à 50%
            
            self.frame_count += 1
            
            return {
                'motion_detected': motion_detected,
                'confidence': float(confidence),
                'regions': regions,
                'coverage': float(coverage),
                'processing_time_ms': float((time.time() - start) * 1000)
            }
            
        except Exception as e:
            logger.error(f"Motion detection error: {e}")
            return {
                'motion_detected': False,
                'confidence': 0.0,
                'regions': [],
                'coverage': 0.0,
                'processing_time_ms': float((time.time() - start) * 1000),
                'error': str(e)
            }
    
    def update_background(self, frame: np.ndarray):
        """Mettre à jour le modèle de fond"""
        if len(frame.shape) == 2:
            working_frame = frame
        else:
            working_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self.bg_subtractor.apply(working_frame)
        self.initialized = True
    
    def reset(self):
        """Réinitialiser le détecteur"""
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            detectShadows=True,
            varThreshold=self.threshold
        )
        self.initialized = False
        self.frame_count = 0
```

**Configuration des paramètres par sensibilité:**

| Sensibilité | Use Case | Min Area |
|---|---|---|
| 10-30 | Haute précision (retail, banques) | 1000 px |
| 40-60 | Équilibré (standard) | 500 px |
| 70-100 | Détection tout (parking, route) | 200 px |

---

### 1.2 Object Detection – YOLO v8/v9 Intégration

**Fichier**: `vms/backend/ai/objects.py`

```python
# NOUVEAU: Détection d'objets avec YOLO v8/v9

import numpy as np
from typing import Dict, List, Optional, Tuple
import logging
import os
from pathlib import Path

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
    
    # Classes standard COCO
    COCO_CLASSES = [
        'person', 'bicycle', 'car', 'motorcycle', 'airplane',
        'bus', 'train', 'truck', 'boat', 'traffic light',
        'fire hydrant', 'stop sign', 'parking meter', 'bench',
        'cat', 'dog', 'horse', 'sheep', 'cow', 'elephant',
        'bear', 'zebra', 'giraffe', 'backpack', 'umbrella'
        # ... (complète les 80 classes COCO)
    ]
    
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
        """Détecter GPU/CPU automatiquement"""
        if HAS_YOLO:
            try:
                import torch
                if torch.cuda.is_available():
                    return 'cuda'
            except:
                pass
        return 'cpu'
    
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
                'objects': [
                    {
                        'class': 'person',
                        'class_id': 0,
                        'confidence': 0.95,
                        'bbox': {'x': int, 'y': int, 'w': int, 'h': int},
                        'bbox_norm': [0-1, 0-1, 0-1, 0-1]  # Normalized
                    },
                    ...
                ],
                'timestamp': datetime.now().isoformat(),
                'frame_shape': (H, W, C),
                'processing_time_ms': float,
                'detections_count': int
            }
        """
        import time
        from datetime import datetime
        
        if not self.available or self.model is None:
            return self._empty_result(frame, "Model not available")
        
        start = time.time()
        
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
                    # YOLO retourne: [x_center, y_center, w, h] normalisé ou pixels selon la version
                    xyxy = box.xyxy[0].tolist()  # [x1, y1, x2, y2] pixels
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    
                    # Convertir en bbox standard
                    x1, y1, x2, y2 = xyxy
                    x, y, w, h = int(x1), int(y1), int(x2 - x1), int(y2 - y1)
                    
                    # Nom de la classe
                    class_name = (
                        result.names[cls_id] if result.names and cls_id < len(result.names)
                        else f"class_{cls_id}"
                    )
                    
                    # Normalizer les coordonnées
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
        """
        Détecter dans un batch d'images (optimisé GPU)
        
        Args:
            frames: List[np.ndarray]
        
        Returns:
            List[Dict] de résultats de détection
        """
        import time
        
        if not self.available or self.model is None:
            return [self._empty_result(f, "Model not available") for f in frames]
        
        start = time.time()
        
        try:
            # Inférence batch
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
        from datetime import datetime
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
```

---

### 1.3 Mettre à jour requirements.txt

```
# Ajouter à requirements.txt:

# Deep Learning & Computer Vision
opencv-python==4.8.1.78
numpy==1.24.3
ultralytics==8.0.238          # YOLOv8/v9
torch==2.1.2                   # GPU: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
torchvision==0.16.2

# Face Recognition
face-recognition==1.3.5        # Déjà en phase 0, confirmé
face-recognition-models==0.3.0

# Optimisations
opencv-python-headless==4.8.1.78  # Alternative sans GUI (serveur)
scipy==1.11.4                  # Utilisé par face-recognition
Pillow==10.1.0                 # Image processing
```

---

## ✅ Phase 2: Production Inference Pipeline (Jour 2-3)

### 2.1 Inference Manager (Orchestration multi-flux)

**Fichier**: `vms/backend/services/inference_manager.py`

```python
"""
Gestionnaire d'inférence pour multi-caméras en temps réel
- Scheduling intelligent des détections
- Batching GPU
- Caching de modèles
- Fallback CPU si nécessaire
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from datetime import datetime
import threading

logger = logging.getLogger("falcon_ai_vision.inference")

from vms.backend.ai.motion import MotionDetector
from vms.backend.ai.objects import ObjectDetector


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
        
        # Thread pool pour inférences asynchrones
        self.executor = ThreadPoolExecutor(
            max_workers=4,  # À adapter selon GPU/CPU disponible
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
        """Initialiser les modèles au démarrage"""
        try:
            # Object Detection (YOLO)
            logger.info("🔄 Initializing object detector (YOLO)...")
            self.object_detector = ObjectDetector(
                model_name="yolov8n",  # nano pour CPU rapide
                confidence_threshold=0.5,
                device="cpu"  # ou "cuda" si GPU disponible
            )
            logger.info("✅ Object detector initialized")
        except Exception as e:
            logger.error(f"Failed to init object detector: {e}")
            self.object_detector = None
    
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
            return {'objects': [], 'error': 'detector_unavailable'}
        
        # Soumettre au thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self.object_detector.detect,
            frame
        )
    
    async def detect_motion_async(
        self,
        frame: np.ndarray,
        camera_id: int
    ) -> Dict:
        """Détection de mouvement async"""
        detector = self.get_motion_detector(camera_id)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            detector.detect,
            frame
        )
    
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
            return [{'objects': [], 'error': 'detector_unavailable'} for _ in frames]
        
        try:
            # Extraire juste les frames
            image_list = [f[1] for f in frames]
            
            # Exécuter batch dans thread executor
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                self.executor,
                self.object_detector.detect_batch,
                image_list
            )
            
            # Augmenter avec les metadata caméra
            for (camera_id, _), result in zip(frames, results):
                result['camera_id'] = camera_id
            
            return results
            
        except Exception as e:
            logger.error(f"Batch detection error: {e}")
            return [{'objects': [], 'error': str(e)} for _ in frames]
    
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
```

---

### 2.2 Intégration au Frame Processor

**Mise à jour de** `vms/backend/services/frame_processor.py`:

```python
# AJOUT à frame_processor.py

async def process_frame_with_ai(
    self,
    frame: np.ndarray
) -> Dict:
    """
    Traiter un frame avec toutes les détections IA
    
    Returns:
        {
            'motion': {...motion detection results...},
            'objects': {...object detection results...},
            'timestamp': ISO datetime,
            'total_latency_ms': float
        }
    """
    start = time.time()
    
    from vms.backend.services.inference_manager import get_inference_manager
    inf_mgr = get_inference_manager()
    
    try:
        # Détection mouvement
        motion_task = asyncio.create_task(
            inf_mgr.detect_motion_async(frame, self.camera_id)
        )
        
        # Détection objets (si mouvement détecté OU tous les N frames)
        if self.frame_count % 5 == 0:  # Tous les 5 frames
            object_task = asyncio.create_task(
                inf_mgr.detect_objects_async(frame, self.camera_id)
            )
        else:
            object_task = asyncio.create_task(
                asyncio.sleep(0)
            )  # No-op si saut
            object_task.set_result({'objects': []})
        
        motion_result = await motion_task
        object_result = await object_task
        
        return {
            'motion': motion_result,
            'objects': object_result.get('objects', []),
            'timestamp': datetime.now().isoformat(),
            'total_latency_ms': (time.time() - start) * 1000,
            'camera_id': self.camera_id
        }
        
    except Exception as e:
        logger.error(f"Frame processing error: {e}")
        return {
            'motion': {'error': str(e), 'motion_detected': False},
            'objects': [],
            'timestamp': datetime.now().isoformat(),
            'total_latency_ms': (time.time() - start) * 1000,
            'error': str(e)
        }
```

---

## ✅ Phase 3: Performance Validation & Optimization (Jour 3)

### 3.1 Benchmark Script

**Fichier**: `vms/backend/tests/benchmark_inference.py`

```python
"""
Benchmark de performance IA
- Latence par détecteur
- Throughput (FPS)
- Utilisation mémoire/CPU
- Multi-caméra stress test
"""

import cv2
import numpy as np
import time
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

class InferenceBenchmark:
    
    @staticmethod
    def benchmark_motion_detection(
        num_frames: int = 100,
        frame_size: Tuple[int, int] = (1280, 720)
    ) -> Dict:
        """Benchmarker le détecteur de mouvement"""
        from vms.backend.ai.motion import MotionDetector
        
        detector = MotionDetector()
        
        # Générer des frames de test
        frames = [np.random.randint(0, 255, (*frame_size, 3), dtype=np.uint8) 
                  for _ in range(num_frames)]
        
        latencies = []
        start = time.time()
        
        for frame in frames:
            result = detector.detect(frame)
            latencies.append(result.get('processing_time_ms', 0))
        
        total_time = time.time() - start
        
        return {
            'detector': 'motion',
            'frames_tested': num_frames,
            'total_time_sec': total_time,
            'fps': num_frames / total_time,
            'avg_latency_ms': np.mean(latencies),
            'min_latency_ms': np.min(latencies),
            'max_latency_ms': np.max(latencies),
            'p95_latency_ms': np.percentile(latencies, 95)
        }
    
    @staticmethod
    def benchmark_object_detection(
        num_frames: int = 50,
        frame_size: Tuple[int, int] = (1280, 720)
    ) -> Dict:
        """Benchmarker YOLO"""
        from vms.backend.ai.objects import ObjectDetector
        
        detector = ObjectDetector(
            model_name="yolov8n",
            device="cpu"
        )
        
        # Générer frames de test
        frames = [np.random.randint(0, 255, (*frame_size, 3), dtype=np.uint8) 
                  for _ in range(num_frames)]
        
        latencies = []
        start = time.time()
        
        for frame in frames:
            result = detector.detect(frame)
            latencies.append(result.get('processing_time_ms', 0))
        
        total_time = time.time() - start
        
        return {
            'detector': 'yolo',
            'model': 'yolov8n',
            'frames_tested': num_frames,
            'total_time_sec': total_time,
            'fps': num_frames / total_time,
            'avg_latency_ms': np.mean(latencies),
            'min_latency_ms': np.min(latencies),
            'max_latency_ms': np.max(latencies),
            'p95_latency_ms': np.percentile(latencies, 95)
        }
    
    @staticmethod
    def run_all_benchmarks() -> Dict:
        """Exécuter tous les benchmarks et générer un rapport"""
        print("🔄 Starting inference benchmarks...")
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'benchmarks': {
                'motion': InferenceBenchmark.benchmark_motion_detection(),
                'yolo': InferenceBenchmark.benchmark_object_detection()
            }
        }
        
        # Afficher les résultats
        print("\n" + "="*60)
        print("📊 BENCHMARK RESULTS")
        print("="*60)
        
        for detector_name, stats in results['benchmarks'].items():
            print(f"\n{detector_name.upper()}:")
            print(f"  FPS: {stats['fps']:.2f}")
            print(f"  Avg Latency: {stats['avg_latency_ms']:.2f}ms")
            print(f"  P95 Latency: {stats['p95_latency_ms']:.2f}ms")
        
        # Sauvegarder rapport JSON
        with open("benchmark_results.json", "w") as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n✅ Benchmark saved to benchmark_results.json")
        
        return results

if __name__ == "__main__":
    InferenceBenchmark.run_all_benchmarks()
```

**Lancer les benchmarks:**

```bash
python -m vms.backend.tests.benchmark_inference
```

---

## ✅ Phase 4: End-to-End Integration Testing (Jour 4)

### 4.1 Test de la pipeline complète

**Fichier**: `vms/backend/tests/test_e2e_pipeline.py`

```python
"""
Tests end-to-end: Caméra → AI → Event → DB → Frontend
"""

import pytest
import asyncio
import numpy as np
from datetime import datetime
from sqlalchemy.orm import Session

@pytest.mark.asyncio
async def test_object_detection_pipeline(db: Session):
    """Test: Détection objet → Création événement"""
    from vms.backend.services.inference_manager import get_inference_manager
    from vms.backend.services.event_service import EventService
    from vms.backend.models import Camera
    
    # Setup: créer une caméra de test
    camera = Camera(
        name="Test_Camera_1",
        owner_id=1,
        object_detection_enabled=True,
        ai_enabled=True
    )
    db.add(camera)
    db.commit()
    
    # Générer une image de test avec du contenu
    frame = np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8)
    
    # Exécuter l'inférence
    inf_mgr = get_inference_manager()
    result = await inf_mgr.detect_objects_async(frame, camera.id)
    
    # Assertions
    assert result is not None
    assert 'objects' in result
    assert result.get('processing_time_ms') >= 0
    
    print(f"✅ Détection: {result['detections_count']} objets, {result['processing_time_ms']:.2f}ms")


@pytest.mark.asyncio
async def test_motion_event_creation(db: Session):
    """Test: Mouvement détecté → Événement créé en DB"""
    from vms.backend.services.inference_manager import get_inference_manager
    from vms.backend.models import Camera, Event
    
    # Setup caméra
    camera = Camera(
        name="Test_Motion_Cam",
        owner_id=1,
        motion_detection_enabled=True
    )
    db.add(camera)
    db.commit()
    
    # Générer frame avec changement
    frame1 = np.zeros((720, 1280, 3), dtype=np.uint8)
    frame2 = np.ones((720, 1280, 3), dtype=np.uint8) * 255  # Blanc
    
    # Détection mouvement
    inf_mgr = get_inference_manager()
    detector = inf_mgr.get_motion_detector(camera.id)
    
    result1 = detector.detect(frame1)
    result2 = detector.detect(frame2)
    
    # Créer événement si mouvement
    if result2.get('motion_detected'):
        event = Event(
            camera_id=camera.id,
            event_type="motion",
            event_data={
                "confidence": result2.get('confidence'),
                "regions": result2.get('regions')
            },
            creator_id=1
        )
        db.add(event)
        db.commit()
        
        assert event.id is not None
        print(f"✅ Motion event created: {event.id}")


@pytest.mark.asyncio
async def test_multi_camera_stress(db: Session):
    """Test de stress: 4 caméras simultanées"""
    from vms.backend.services.inference_manager import get_inference_manager
    
    inf_mgr = get_inference_manager()
    
    # Créer 4 frames de test
    frames = [
        (i, np.random.randint(0, 255, (720, 1280, 3), dtype=np.uint8))
        for i in range(1, 5)
    ]
    
    # Inférence batch
    start = time.time()
    results = await inf_mgr.detect_batch_objects_async(frames)
    elapsed = time.time() - start
    
    # Assertions
    assert len(results) == 4
    assert all('objects' in r for r in results)
    
    avg_latency = np.mean([r.get('processing_time_ms', 0) for r in results])
    print(f"✅ 4-camera batch: {elapsed*1000:.2f}ms, avg latency: {avg_latency:.2f}ms")
```

---

## ✅ Phase 5: Production Deployment & Documentation (Jour 5)

### 5.1 Docker Deployment

**Fichier**: `Dockerfile.production`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Dépendances système
RUN apt-get update && apt-get install -y \
    libsm6 libxext6 libxrender-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY vms/ ./vms/
COPY data/ ./data/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5003/health')"

# Startup
CMD ["python", "-m", "uvicorn", "vms.backend.main:app", "--host", "0.0.0.0", "--port", "5003"]
```

**Build and run:**

```bash
docker build -f Dockerfile.production -t falcon-ai-vision:prod .
docker run -p 5003:5003 -v $(pwd)/data:/app/data falcon-ai-vision:prod
```

---

### 5.2 Production Configuration Guide

**Fichier**: `PRODUCTION_DEPLOYMENT.md`

```markdown
# Production Deployment Guide

## Hardware Recommendations

| Component | Min | Recommended | Best |
|---|---|---|---|
| CPU | 4 cores | 8 cores | 16+ cores |
| RAM | 8GB | 16GB | 32GB+ |
| GPU | None | RTX 3070/4070 | RTX 4090 / A100 |
| Storage | 256GB SSD | 1TB NVMe | 2TB+ NVMe |

## Performance Targets

- **Motion Detection**: <10ms per frame @ 1080p
- **YOLO Inference**: 30-50ms per frame (yolov8n on CPU)
- **Multi-camera throughput**: 5+ FPS per camera @ 4K
- **Memory footprint**: <4GB (yolov8n + motion)

## Optimization Checklist

- [ ] Use `yolov8n` (nano) on CPU, `yolov8m+` on GPU
- [ ] Enable frame skipping (process every Nth frame)
- [ ] Implement model quantization (INT8) for embedded
- [ ] Use batch inference for >2 cameras
- [ ] Cache models in memory (singleton pattern ✅)
- [ ] Monitor inference latency in production

## Monitoring & Alerts

```python
# Setup Prometheus metrics
from prometheus_client import Counter, Histogram

inference_counter = Counter(
    'ai_inferences_total', 'Total inferences',
    ['camera_id', 'detector_type']
)

inference_latency = Histogram(
    'ai_inference_latency_ms', 'Inference latency',
    ['detector_type']
)
```

## Fallback Strategy

If GPU is unavailable or overloaded:
1. Switch to CPU inference automatically
2. Reduce frame resolution (720p → 480p)
3. Increase frame skip interval
4. Disable lower-priority detections (objects if motion is off)
```

---

## 📊 Progress Tracking

| Phase | Task | Status | Est. Time |
|---|---|---|---|
| **1** | Motion detection (OpenCV MOG2) | ⏳ TODO | 2h |
| **1** | Object detection (YOLO v8) | ⏳ TODO | 3h |
| **1** | Update requirements.txt | ⏳ TODO | 15min |
| **2** | InferenceManager (singleton) | ⏳ TODO | 2h |
| **2** | Async integration | ⏳ TODO | 1h |
| **3** | Benchmark suite | ⏳ TODO | 1h |
| **4** | E2E integration tests | ⏳ TODO | 2h |
| **5** | Docker + Deployment docs | ⏳ TODO | 1h |
| | **TOTAL** | | **14h** |

---

## 🎯 Success Criteria

- ✅ Motion detection working with real frames
- ✅ YOLO inference running (CPU or GPU)
- ✅ Multi-camera async pipeline operational
- ✅ Benchmarks showing <50ms latency per frame
- ✅ E2E tests passing (detection → event → DB)
- ✅ Production Docker image building
- ✅ Documentation complete & deployment tested

---

## Next Steps

1. **Start Phase 1**: Copy code from "Motion Detection" section → `vms/backend/ai/motion.py`
2. **Confirm YOLO installation**: `pip install ultralytics torch torchvision`
3. **Run basic test**: `python -c "from vms.backend.ai.objects import ObjectDetector; ObjectDetector()"`
4. **Report any blockers** for Phase 2 integration

---

**Questions ou problèmes? Review sections:**
- GPU/CPU not detected → See InferenceManager._auto_detect_device()
- YOLO model too slow → Use yolov8n (nano), not yolov8x
- Memory issues → Reduce model cache, enable frame skipping
- Async errors → Check event loop in routers (use async endpoints)
