# vms/vehicle_detection/vehicle_detector.py - Détecteur de véhicules avec YOLOv8

import numpy as np
from typing import List, Dict, Optional, Tuple
import os
import logging

logger = logging.getLogger(__name__)

try:
    from ultralytics import YOLO
    _HAS_YOLO = True
except Exception:
    YOLO = None
    _HAS_YOLO = False

try:
    import cv2
    _HAS_CV2 = True
except Exception:
    cv2 = None
    _HAS_CV2 = False


class VehicleDetector:
    """Détecteur de véhicules avec YOLOv8.
    
    Utilise ultralytics YOLO si disponible, sinon mode dégradé (placeholders).
    Classes supportées: voitures, camions, motos, bus, bateaux, personnes, animaux.
    """
    
    # Classes YOLOv8 coco pertinentes
    YOLO_CLASSES = {
        0: 'person', 2: 'car', 3: 'motorcycle', 5: 'bus',
        7: 'truck', 8: 'boat', 15: 'cat', 16: 'dog'
    }
    
    def __init__(self, model_name: str = "yolov8m"):
        """
        Initialiser le détecteur YOLOv8.
        
        Args:
            model_name: yolov8n (fast) | yolov8s | yolov8m (balanced) | yolov8l | yolov8x (accurate)
        """
        self.model_name = model_name
        self.model = None
        self.confidence_threshold = 0.5
        self.track_history = {}  # Pour tracking multi-frame
        
        if _HAS_YOLO:
            try:
                # Auto-download model from Ultralytics Hub
                self.model = YOLO(f"{model_name}.pt")
                logger.info(f"YOLOv8 {model_name} loaded successfully")
            except Exception as e:
                logger.warning(f"Could not load YOLOv8 model: {e}")
                self.model = None
        else:
            logger.warning("ultralytics not installed; YOLOv8 disabled (fallback mode)")
    
    def detect_vehicles(self, image: np.ndarray, confidence: float = 0.5) -> List[Dict]:
        """
        Détecter les véhicules et personnes dans une image.
        
        Args:
            image: Image numpy (BGR ou RGB)
            confidence: Seuil de confiance (0-1)
            
        Returns:
            Liste de dictionnaires avec détections
        """
        try:
            if self.model is None or not _HAS_YOLO:
                # Fallback mode
                logger.debug("YOLOv8 not available, returning empty detections")
                return []
            
            results = self.model(image, conf=confidence, verbose=False)
            detections = []
            
            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls.item())
                    if class_id in self.YOLO_CLASSES:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        detections.append({
                            'class': self.YOLO_CLASSES[class_id],
                            'class_id': class_id,
                            'bbox': (int(x1), int(y1), int(x2), int(y2)),
                            'confidence': float(box.conf.item()),
                            'area': int((x2 - x1) * (y2 - y1))
                        })
            
            return detections
        except Exception as e:
            logger.error(f"YOLOv8 detection error: {e}")
            return []
    
    def detect_with_tracking(self, image: np.ndarray, confidence: float = 0.5) -> List[Dict]:
        """
        Détecter avec tracking multi-frame (assigne IDs persistantes).
        
        Args:
            image: Image numpy
            confidence: Seuil de confiance
            
        Returns:
            Détections avec track_id pour suivi
        """
        try:
            if self.model is None or not _HAS_YOLO:
                return []
            
            results = self.model.track(image, persist=True, conf=confidence, verbose=False)
            detections = []
            
            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls.item())
                    track_id = int(box.id.item()) if box.id is not None else None
                    
                    if class_id in self.YOLO_CLASSES:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        detections.append({
                            'track_id': track_id,
                            'class': self.YOLO_CLASSES[class_id],
                            'class_id': class_id,
                            'bbox': (int(x1), int(y1), int(x2), int(y2)),
                            'confidence': float(box.conf.item()),
                            'area': int((x2 - x1) * (y2 - y1))
                        })
            
            return detections
        except Exception as e:
            logger.error(f"YOLOv8 tracking error: {e}")
            return []
    
    def batch_process(self, frames: List[np.ndarray], confidence: float = 0.5) -> List[List[Dict]]:
        """
        Traiter plusieurs frames efficacement.
        
        Args:
            frames: Liste d'images numpy
            confidence: Seuil de confiance
            
        Returns:
            Liste de listes de détections
        """
        try:
            if self.model is None or not _HAS_YOLO:
                return [[] for _ in frames]
            
            results = self.model(frames, conf=confidence, verbose=False)
            detections_list = []
            
            for result in results:
                detections = []
                for box in result.boxes:
                    class_id = int(box.cls.item())
                    if class_id in self.YOLO_CLASSES:
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        detections.append({
                            'class': self.YOLO_CLASSES[class_id],
                            'bbox': (int(x1), int(y1), int(x2), int(y2)),
                            'confidence': float(box.conf.item())
                        })
                detections_list.append(detections)
            
            return detections_list
        except Exception as e:
            logger.error(f"YOLOv8 batch processing error: {e}")
            return [[] for _ in frames]
    
    def detect_license_plates(self, image: np.ndarray) -> List[Dict]:
        """
        Détecter les plaques d'immatriculation (placeholder).
        
        Nécessite un modèle spécialisé à entraîner.
        """
        # TODO: Intégrer modèle licence plate détection
        logger.info("License plate detection not yet implemented")
        return []
    
    def classify_vehicle(self, image: np.ndarray, bbox: Tuple[int, int, int, int]) -> Dict:
        """
        Classifier un véhicule (marque, couleur, etc.).
        
        Args:
            image: Image complète
            bbox: (x1, y1, x2, y2) région du véhicule
            
        Returns:
            Classification détaillée (placeholder)
        """
        try:
            x1, y1, x2, y2 = bbox
            vehicle_img = image[y1:y2, x1:x2]
            
            # TODO: Intégrer modèle classification véhicule
            return {
                'type': 'vehicle',
                'color': 'unknown',
                'brand': 'unknown'
            }
        except Exception as e:
            logger.error(f"Vehicle classification error: {e}")
            return {}
    
    def draw_detections(self, image: np.ndarray, detections: List[Dict]) -> np.ndarray:
        """Dessiner les détections sur l'image."""
        try:
            if not _HAS_CV2:
                return image
            
            img_copy = image.copy()
            
            for det in detections:
                x1, y1, x2, y2 = det['bbox']
                class_name = det['class']
                confidence = det['confidence']
                
                # Couleur par classe
                color_map = {
                    'car': (0, 255, 0),
                    'truck': (0, 165, 255),
                    'motorcycle': (255, 0, 0),
                    'bus': (0, 255, 255),
                    'person': (255, 0, 255),
                    'boat': (0, 128, 255)
                }
                color = color_map.get(class_name, (255, 255, 255))
                
                # Rectangle
                cv2.rectangle(img_copy, (x1, y1), (x2, y2), color, 2)
                
                # Label
                label = f"{class_name} {confidence:.2f}"
                cv2.putText(img_copy, label, (x1, y1 - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
            return img_copy
        except Exception as e:
            logger.error(f"Draw detections error: {e}")
            return image
    
    @staticmethod
    def get_statistics(detections_list: List[List[Dict]]) -> Dict:
        """
        Calculer statistiques sur une liste de détections.
        
        Args:
            detections_list: Résultat de batch_process ou plusieurs frames
            
        Returns:
            Statistiques agrégées
        """
        try:
            stats = {
                'total_detections': 0,
                'by_class': {},
                'avg_confidence': 0.0
            }
            
            total_confidence = 0.0
            total_count = 0
            
            for detections in detections_list:
                for det in detections:
                    class_name = det['class']
                    confidence = det['confidence']
                    
                    stats['by_class'][class_name] = stats['by_class'].get(class_name, 0) + 1
                    stats['total_detections'] += 1
                    total_confidence += confidence
                    total_count += 1
            
            if total_count > 0:
                stats['avg_confidence'] = total_confidence / total_count
            
            return stats
        except Exception as e:
            logger.error(f"Statistics calculation error: {e}")
            return {'total_detections': 0, 'by_class': {}, 'avg_confidence': 0.0}
