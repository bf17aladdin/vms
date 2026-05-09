# vms/backend/routers/calibration_router.py - AI Calibration Endpoints (Sprint 3)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging

from ..services.ai_calibration import get_calibration_manager
from ..core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calibration", tags=["AI Calibration"])

class ThresholdUpdate(BaseModel):
    value: float
    reason: Optional[str] = None

class CalibrationConfig(BaseModel):
    lbph_threshold: float
    yolo_confidence: float
    plate_confidence: float

@router.get("/config", summary="Get current calibration config")
async def get_calibration_config(current_user: dict = Depends(get_current_user)):
    """Récupère config d'étalonnage actuelle"""
    try:
        manager = get_calibration_manager()
        config = manager.get_all_thresholds()
        return {
            "lbph_threshold": config.get("lbph", {}).get("threshold", 100),
            "yolo_confidence": config.get("yolo", {}).get("confidence", 0.5),
            "plate_confidence": config.get("vehicle", {}).get("plate_confidence", 0.6),
            "raw": config,
        }
    except Exception as e:
        logger.error(f"Error fetching calibration: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch calibration")

@router.put("/thresholds/lbph", summary="Update LBPH distance threshold (0-255)")
async def update_lbph_threshold(
    data: ThresholdUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Met à jour le seuil de distance LBPH (reconnaissance faciale)
    - Valeur: 0-255 (plus bas = plus strict)
    - Défaut: 100
    """
    if not (0 <= data.value <= 255):
        raise HTTPException(status_code=400, detail="LBPH threshold must be 0-255")
    
    try:
        manager = get_calibration_manager()
        manager.update_lbph_threshold(data.value, data.reason or "Manual adjustment")
        return {
            "status": "success",
            "message": f"LBPH threshold updated to {data.value}",
            "lbph_threshold": data.value
        }
    except Exception as e:
        logger.error(f"Error updating LBPH: {e}")
        raise HTTPException(status_code=500, detail="Failed to update LBPH threshold")

@router.put("/thresholds/yolo", summary="Update YOLO confidence threshold (0.0-1.0)")
async def update_yolo_confidence(
    data: ThresholdUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Met à jour la confiance YOLO (détection objets)
    - Valeur: 0.0-1.0 (plus bas = moins de filtrage)
    - Défaut: 0.5
    """
    if not (0.0 <= data.value <= 1.0):
        raise HTTPException(status_code=400, detail="YOLO confidence must be 0.0-1.0")
    
    try:
        manager = get_calibration_manager()
        manager.update_yolo_confidence(data.value, data.reason or "Manual adjustment")
        return {
            "status": "success",
            "message": f"YOLO confidence updated to {data.value}",
            "yolo_confidence": data.value
        }
    except Exception as e:
        logger.error(f"Error updating YOLO: {e}")
        raise HTTPException(status_code=500, detail="Failed to update YOLO confidence")

@router.put("/thresholds/plate", summary="Update plate OCR confidence (0.0-1.0)")
async def update_plate_confidence(
    data: ThresholdUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Met à jour la confiance OCR plaque d'immatriculation
    - Valeur: 0.0-1.0
    - Défaut: 0.7
    """
    if not (0.0 <= data.value <= 1.0):
        raise HTTPException(status_code=400, detail="Plate confidence must be 0.0-1.0")
    
    try:
        manager = get_calibration_manager()
        manager.update_plate_confidence(data.value, data.reason or "Manual adjustment")
        return {
            "status": "success",
            "message": f"Plate confidence updated to {data.value}",
            "plate_confidence": data.value
        }
    except Exception as e:
        logger.error(f"Error updating plate confidence: {e}")
        raise HTTPException(status_code=500, detail="Failed to update plate confidence")

@router.post("/thresholds/apply", summary="Apply batch threshold updates")
async def apply_batch_thresholds(
    config: CalibrationConfig,
    current_user: dict = Depends(get_current_user)
):
    """Applique plusieurs mises à jour d'étalonnage à la fois"""
    try:
        manager = get_calibration_manager()
        manager.update_lbph_threshold(config.lbph_threshold, "Batch update")
        manager.update_yolo_confidence(config.yolo_confidence, "Batch update")
        manager.update_plate_confidence(config.plate_confidence, "Batch update")
        
        return {
            "status": "success",
            "message": "All thresholds updated",
            "config": manager.get_all_thresholds()
        }
    except Exception as e:
        logger.error(f"Error applying batch update: {e}")
        raise HTTPException(status_code=500, detail="Failed to apply thresholds")

@router.get("/history", summary="Get calibration tuning history")
async def get_tuning_history(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Récupère l'historique des modifications d'étalonnage"""
    try:
        manager = get_calibration_manager()
        history = manager.get_tuning_history()
        return {
            "total": len(history),
            "history": history[-limit:]  # Derniers N
        }
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch history")

@router.post("/reset", summary="Reset to default thresholds")
async def reset_to_defaults(current_user: dict = Depends(get_current_user)):
    """Réinitialise tous les seuils aux valeurs par défaut"""
    try:
        manager = get_calibration_manager()
        manager.reset_to_defaults("Reset to defaults")
        
        return {
            "status": "success",
            "message": "All thresholds reset to defaults",
            "config": manager.get_all_thresholds()
        }
    except Exception as e:
        logger.error(f"Error resetting thresholds: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset thresholds")
