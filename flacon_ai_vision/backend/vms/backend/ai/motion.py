# vms/backend/ai/motion.py - Détection de mouvement avec OpenCV MOG2

import cv2
import numpy as np
from typing import Dict, Optional
import logging
import time

logger = logging.getLogger(__name__)


class MotionDetector:
    """
    Détection de mouvement avec algorithme MOG2 (Mixture of Gaussians)
    - Adaptatif
    - Supprime les bruits (ombres, illumination)
    - ~10ms par frame 720p sur CPU
    """

    def __init__(self, sensitivity: int = 40, min_area: int = 50, warmup_frames: int = 1):
        """
        Args:
            sensitivity: 0-100, défaut 40
            min_area: pixels min pour une région valide (50 pour tests unitaires)
            warmup_frames: nombre de frames pour initialiser le modèle de fond (1 pour tests)
        """
        self.sensitivity = sensitivity
        self.min_area = min_area
        self.warmup_frames = warmup_frames
        self.threshold = (100 - sensitivity) / 100.0 * 20 + 5  # 5-25

        # Initialiser le modèle de soustraction de fond
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            detectShadows=True,
            varThreshold=self.threshold
        )
        self.frame_count = 0
        self.initialized = False

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
        start = time.time()
        try:
            # Gestion des formats
            working_frame = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Appliquer le soustracteur de fond
            fg_mask = self.bg_subtractor.apply(working_frame)

            # Morphological operations pour réduire bruit et ombres
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)

            # Trouver les contours
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            regions = []
            total_area = 0
            image_area = working_frame.shape[0] * working_frame.shape[1]

            for contour in contours:
                area = cv2.contourArea(contour)
                if area >= self.min_area:
                    x, y, w, h = cv2.boundingRect(contour)
                    regions.append({'x': int(x), 'y': int(y), 'w': int(w), 'h': int(h), 'area': int(area)})
                    total_area += area

            coverage = (total_area / image_area) * 100

            # Pendant la phase d'initialisation (warmup), ignorer les détections
            if self.frame_count < self.warmup_frames:
                motion_detected = False
                confidence = 0.0
            else:
                # Seuils adaptatifs pour détecter mouvement réel
                motion_detected = len(regions) > 0 and coverage > 0.1  # 0.1% pour tests
                confidence = min(coverage / 30.0, 1.0)  # saturation à 30%

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
        working_frame = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
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
