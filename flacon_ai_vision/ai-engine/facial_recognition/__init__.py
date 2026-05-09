"""
Module de reconnaissance faciale pour Falcon AI Vision
"""
import os
import sys

# Ajouter le chemin du projet
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .face_detector import FaceDetector
from .face_recognizer import FaceRecognizer

__version__ = "1.0.0"
__all__ = ['FaceDetector', 'FaceRecognizer']