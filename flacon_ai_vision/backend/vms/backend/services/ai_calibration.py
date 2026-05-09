# vms/backend/services/ai_calibration.py - LBPH & YOLO threshold management (Sprint 3)

import json
import logging
from typing import Dict, Tuple
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class AICalibrationManager:
    """
    Gère la calibration des seuils AI (LBPH distances, YOLO confidence).
    UI configurable pour ajuster en temps réel.
    
    **Sprint 3 Deliverable**: AI Calibration Interface
    """
    
    # Defaults (peut être surchargé via UI)
    DEFAULTS = {
        'lbph': {
            'threshold': 100,  # Distance max (0-255)
            'min_samples': 2,
            'grid_x': 8,
            'grid_y': 8,
            'radius': 1,
            'neighbors': 8
        },
        'yolo': {
            'confidence': 0.5,
            'iou_threshold': 0.45,
            'max_detections': 100
        },
        'vehicle': {
            'plate_confidence': 0.6,
            'vehicle_confidence': 0.7,
            'min_plate_area': 50
        }
    }
    
    def __init__(self, config_path: Path = Path("data/ai_calibration.json")):
        self.config_path = config_path
        self.config = self.load_config()
        self.tuning_history: list = []
    
    def load_config(self) -> Dict:
        """Charger config depuis fichier ou utiliser defaults"""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load calibration config: {e}. Using defaults.")
        return self.DEFAULTS.copy()
    
    def save_config(self):
        """Sauvegarder config dans fichier"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
        logger.info(f"✓ AI calibration saved to {self.config_path}")
    
    def update_lbph_threshold(self, threshold: int, reason: str = "manual adjustment"):
        """Mettre à jour LBPH distance threshold (0-255)"""
        threshold = max(0, min(255, threshold))
        old_val = self.config['lbph']['threshold']
        self.config['lbph']['threshold'] = threshold
        self.tuning_history.append({
            'timestamp': datetime.now().isoformat(),
            'parameter': 'lbph.threshold',
            'old_value': old_val,
            'new_value': threshold,
            'reason': reason
        })
        self.save_config()
        logger.info(f"✓ LBPH threshold updated: {old_val} → {threshold}")
        return threshold
    
    def update_yolo_confidence(self, confidence: float, reason: str = "manual adjustment"):
        """Mettre à jour YOLO confidence threshold (0.0-1.0)"""
        confidence = max(0.0, min(1.0, confidence))
        old_val = self.config['yolo']['confidence']
        self.config['yolo']['confidence'] = confidence
        self.tuning_history.append({
            'timestamp': datetime.now().isoformat(),
            'parameter': 'yolo.confidence',
            'old_value': old_val,
            'new_value': confidence,
            'reason': reason
        })
        self.save_config()
        logger.info(f"✓ YOLO confidence updated: {old_val} → {confidence}")
        return confidence
    
    def update_plate_confidence(self, confidence: float, reason: str = "manual adjustment"):
        """Mettre à jour plate OCR confidence threshold"""
        confidence = max(0.0, min(1.0, confidence))
        old_val = self.config['vehicle']['plate_confidence']
        self.config['vehicle']['plate_confidence'] = confidence
        self.tuning_history.append({
            'timestamp': datetime.now().isoformat(),
            'parameter': 'vehicle.plate_confidence',
            'old_value': old_val,
            'new_value': confidence,
            'reason': reason
        })
        self.save_config()
        logger.info(f"✓ Plate confidence updated: {old_val} → {confidence}")
        return confidence
    
    def get_all_thresholds(self) -> Dict:
        """Retourner tous les seuils actuels"""
        return self.config.copy()
    
    def get_lbph_config(self) -> Dict:
        """Config LBPH pour FaceRecognizer"""
        return self.config['lbph'].copy()
    
    def get_yolo_config(self) -> Dict:
        """Config YOLO pour détecteur"""
        return self.config['yolo'].copy()
    
    def reset_to_defaults(self, reason: str = "admin reset"):
        """Réinitialiser tous les seuils aux defaults"""
        self.config = self.DEFAULTS.copy()
        self.tuning_history.append({
            'timestamp': datetime.now().isoformat(),
            'action': 'reset_to_defaults',
            'reason': reason
        })
        self.save_config()
        logger.info("✓ AI calibration reset to defaults")
    
    def get_tuning_history(self, limit: int = 50) -> list:
        """Retourner l'historique des ajustements"""
        return self.tuning_history[-limit:]
    
    def export_report(self) -> Dict:
        """Export du rapport de calibration"""
        return {
            'timestamp': datetime.now().isoformat(),
            'current_config': self.config,
            'history_entries': len(self.tuning_history),
            'recent_changes': self.get_tuning_history(10)
        }

# Instance globale
_calibration: AICalibrationManager | None = None

def get_calibration_manager() -> AICalibrationManager:
    """Get or create global calibration manager"""
    global _calibration
    if _calibration is None:
        _calibration = AICalibrationManager()
    return _calibration
