"""
Configuration de la reconnaissance faciale pour Falcon AI Vision
"""
import os
from pathlib import Path

# Chemins relatifs au projet
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class FacialRecognitionConfig:
    # Chemins des modèles
    MODELS_DIR = BASE_DIR / "models" / "face_recognition"
    MODEL_FILE = "res10_300x300_ssd_iter_140000_fp16.caffemodel"
    CONFIG_FILE = "deploy.prototxt"
    FACE_RECOGNITION_MODEL = MODELS_DIR / "face_recognizer.pkl"
    
    # Dossiers de stockage
    DATA_DIR = BASE_DIR / "data"
    KNOWN_FACES_DIR = DATA_DIR / "known_faces"
    UNKNOWN_FACES_DIR = DATA_DIR / "unknown_faces"
    EXPORT_DIR = DATA_DIR / "exports"
    
    # Configuration des caméras (à adapter avec votre configuration existante)
    CAMERAS = {
        "entrance": {
            "id": 1,
            "name": "Entrée principale",
            "source": 0,  # Webcam par défaut
            "location": "Bâtiment A, Entrée",
            "is_active": True
        },
        "reception": {
            "id": 2,
            "name": "Réception",
            "source": "rtsp://admin:password@192.168.1.100:554",
            "location": "Bâtiment A, Réception",
            "is_active": True
        }
    }
    
    # Seuils de détection
    DETECTION_THRESHOLD = 0.5
    RECOGNITION_THRESHOLD = 0.6
    MIN_FACE_SIZE = (100, 100)
    
    # Paramètres de performance
    FRAME_SKIP = 2  # Traiter 1 frame sur 3 pour réduire la charge CPU
    MAX_FACES_PER_FRAME = 10
    
    # Intégration avec la base de données existante
    DATABASE_PATH = BASE_DIR / "falcon_ai_vision.db"
    ENABLE_DB_LOGGING = True
    
    # API configuration (si vous avez une API REST)
    API_BASE_URL = "http://localhost:8000/api"
    API_ENDPOINTS = {
        "face_events": "/face-detections/",
        "alerts": "/alerts/",
        "cameras": "/cameras/",
        "persons": "/persons/"
    }
    
    # Alertes
    ALERT_UNKNOWN_FACES = True
    ALERT_BLACKLIST_MATCH = True
    SEND_EMAIL_ALERTS = False
    SEND_WEBHOOK_ALERTS = True
    
    @classmethod
    def init_directories(cls):
        """Crée les répertoires nécessaires"""
        directories = [
            cls.MODELS_DIR,
            cls.DATA_DIR,
            cls.KNOWN_FACES_DIR,
            cls.UNKNOWN_FACES_DIR,
            cls.EXPORT_DIR
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            print(f"✓ Répertoire créé/verifié: {directory}")
    
    @classmethod
    def get_camera_config(cls, camera_id):
        """Récupère la configuration d'une caméra"""
        for cam_key, cam_config in cls.CAMERAS.items():
            if cam_config.get("id") == camera_id:
                return cam_config
        return None