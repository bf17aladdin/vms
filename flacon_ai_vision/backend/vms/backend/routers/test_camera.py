# vms/backend/routers/test_camera.py
from fastapi import APIRouter, HTTPException
import subprocess
import sys
import os
from pathlib import Path

router = APIRouter(
    prefix="/api/test-camera",
    tags=["test-camera"],
)

@router.get("/")
async def test_camera_info():
    """Informations sur le test de caméra"""
    return {
        "name": "Test Camera Module",
        "description": "Endpoints pour tester les fonctionnalités de caméra",
        "available": True,
        "script_path": "services/test_camera.py"
    }

@router.post("/run")
async def run_camera_test():
    """Exécuter le script de test de caméra en arrière-plan"""
    try:
        # Chemin absolu vers le script
        script_path = Path(__file__).parent.parent / "services" / "test_camera.py"
        
        if not script_path.exists():
            return {
                "success": False,
                "error": f"Script non trouvé: {script_path}"
            }
        
        # Exécuter le script dans un sous-processus
        process = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        return {
            "success": True,
            "message": "Test de caméra démarré",
            "pid": process.pid,
            "note": "Le test s'exécute dans un terminal séparé"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur: {str(e)}")

@router.get("/check")
async def check_camera():
    """Vérifier si la caméra fonctionne"""
    try:
        import cv2
        
        # Tester l'ouverture de la caméra
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            
            if ret:
                return {
                    "camera_available": True,
                    "message": "Caméra détectée et fonctionnelle",
                    "resolution": f"{frame.shape[1]}x{frame.shape[0]}" if ret else "Inconnue"
                }
            else:
                return {
                    "camera_available": True,
                    "message": "Caméra détectée mais impossible de lire une frame",
                    "warning": "Vérifiez les permissions ou le driver"
                }
        else:
            return {
                "camera_available": False,
                "message": "Caméra non détectée",
                "suggestion": "Vérifiez la connexion de la webcam"
            }
            
    except ImportError:
        return {
            "opencv_available": False,
            "camera_available": False,
            "message": "OpenCV n'est pas installé",
            "install": "pip install opencv-contrib-python"
        }
    except Exception as e:
        return {
            "camera_available": False,
            "error": str(e)
        }
