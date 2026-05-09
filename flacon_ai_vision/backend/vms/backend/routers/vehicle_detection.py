# vms/backend/routers/vehicle_detection.py - Routes détection véhicules

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from ..core.database import get_db
from ..core.security import get_current_user, get_current_admin
from ..core.time_utils import utc_now_naive_iso
from ..routers.runtime_guard import ensure_manual_inference_allowed
from ..services.vehicle_service import VehicleService

router = APIRouter(prefix="/api/vehicle-detections", tags=["vehicle-detections"])

# ============= ROUTES DÉTECTION VÉHICULES =============

@router.get("/", response_model=dict)
def get_vehicle_detections(
    camera_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les détections de véhicules"""
    try:
        detections = VehicleService.get_all_detections(
            db, camera_id=camera_id, skip=skip, limit=limit
        )
        return {
            "count": len(detections),
            "detections": detections,
            "message": "Vehicle detections retrieved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detect/{camera_id}", response_model=dict)
def detect_vehicles_in_camera(
    camera_id: int,
    confidence: float = 0.5,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Détecter les véhicules dans le flux d'une caméra"""
    try:
        ensure_manual_inference_allowed("vehicle_detection.detect_in_camera")
        detections = VehicleService.detect_vehicles_in_stream(
            db, camera_id, confidence_threshold=confidence
        )
        return {
            "camera_id": camera_id,
            "detections_count": len(detections),
            "detections": detections,
            "timestamp": utc_now_naive_iso()
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/track-plate", response_model=dict)
def track_license_plate(
    plate_number: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Tracker une plaque d'immatriculation"""
    try:
        results = VehicleService.track_plate(db, plate_number)
        return {
            "plate": plate_number,
            "detections_count": len(results),
            "detections": results,
            "timestamp": utc_now_naive_iso()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics", response_model=dict)
def get_vehicle_statistics(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtenir les statistiques de détection de véhicules"""
    try:
        stats = VehicleService(db).get_statistics()
        return {
            "total_detections": stats.get("total"),
            "by_type": stats.get("by_type"),
            "by_camera": stats.get("by_camera"),
            "timestamp": utc_now_naive_iso()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts", response_model=dict)
def get_vehicle_alerts(
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Récupérer les alertes de détection de véhicules"""
    try:
        alerts = VehicleService.get_alerts(db, skip=skip, limit=limit)
        return {
            "count": len(alerts),
            "alerts": alerts,
            "message": "Vehicle alerts retrieved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/set-alert-zone/{camera_id}", response_model=dict)
def set_alert_zone(
    camera_id: int,
    zone_name: str,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Définir une zone d'alerte pour les véhicules"""
    try:
        result = VehicleService.create_alert_zone(db, camera_id, zone_name)
        return {
            "zone_id": result["id"],
            "camera_id": camera_id,
            "zone_name": zone_name,
            "message": "Alert zone created successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
