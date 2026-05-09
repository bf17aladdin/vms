# vms/backend/routers/scenarios_router.py - Entry/Exit Scenario Detection (Sprint 4)

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import logging

from ..services.entry_exit_scenarios import get_scenario_manager
from ..core.security import get_current_user
from ..routers.runtime_guard import ensure_manual_inference_allowed

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios", tags=["Scenarios"])

class PersonnelEntryRequest(BaseModel):
    personnel_id: int
    zone_id: int
    confidence: float

class PersonnelExitRequest(BaseModel):
    personnel_id: int
    zone_id: int
    confidence: float

class VehicleEntryRequest(BaseModel):
    plate: str
    zone_id: int
    confidence: float

class VehicleExitRequest(BaseModel):
    plate: str
    zone_id: int
    confidence: float

@router.post("/personnel/entry", summary="Detect personnel entry")
async def detect_personnel_entry(
    data: PersonnelEntryRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Détecte une entrée personnel
    Retourne le type de scénario (NORMAL_ENTRY, TAILGATE_ENTRY, etc.)
    """
    try:
        ensure_manual_inference_allowed("scenarios.personnel_entry")
        manager = get_scenario_manager()
        result = manager.detect_personnel_entry(
            personnel_id=data.personnel_id,
            zone_id=data.zone_id,
            confidence=data.confidence,
            timestamp=datetime.now()
        )
        
        return {
            "status": "success",
            "scenario": result['scenario'].value,
            "confidence": result['confidence'],
            "alerts": result['alerts'],
            "timestamp": result['timestamp']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting personnel entry: {e}")
        raise HTTPException(status_code=500, detail="Failed to detect entry")

@router.post("/personnel/exit", summary="Detect personnel exit")
async def detect_personnel_exit(
    data: PersonnelExitRequest,
    current_user: dict = Depends(get_current_user)
):
    """Détecte une sortie personnel"""
    try:
        ensure_manual_inference_allowed("scenarios.personnel_exit")
        manager = get_scenario_manager()
        result = manager.detect_personnel_exit(
            personnel_id=data.personnel_id,
            zone_id=data.zone_id,
            confidence=data.confidence,
            timestamp=datetime.now()
        )
        
        return {
            "status": "success",
            "scenario": result['scenario'].value,
            "confidence": result['confidence'],
            "alerts": result['alerts'],
            "timestamp": result['timestamp']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting personnel exit: {e}")
        raise HTTPException(status_code=500, detail="Failed to detect exit")

@router.post("/vehicle/entry", summary="Detect vehicle entry")
async def detect_vehicle_entry(
    data: VehicleEntryRequest,
    current_user: dict = Depends(get_current_user)
):
    """Détecte une entrée véhicule"""
    try:
        ensure_manual_inference_allowed("scenarios.vehicle_entry")
        manager = get_scenario_manager()
        result = manager.detect_vehicle_entry(
            plate=data.plate,
            zone_id=data.zone_id,
            confidence=data.confidence,
            timestamp=datetime.now()
        )
        
        return {
            "status": "success",
            "scenario": result['scenario'].value,
            "confidence": result['confidence'],
            "alerts": result['alerts'],
            "timestamp": result['timestamp']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting vehicle entry: {e}")
        raise HTTPException(status_code=500, detail="Failed to detect entry")

@router.post("/vehicle/exit", summary="Detect vehicle exit")
async def detect_vehicle_exit(
    data: VehicleExitRequest,
    current_user: dict = Depends(get_current_user)
):
    """Détecte une sortie véhicule"""
    try:
        ensure_manual_inference_allowed("scenarios.vehicle_exit")
        manager = get_scenario_manager()
        result = manager.detect_vehicle_exit(
            plate=data.plate,
            zone_id=data.zone_id,
            confidence=data.confidence,
            timestamp=datetime.now()
        )
        
        return {
            "status": "success",
            "scenario": result['scenario'].value,
            "confidence": result['confidence'],
            "alerts": result['alerts'],
            "timestamp": result['timestamp']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting vehicle exit: {e}")
        raise HTTPException(status_code=500, detail="Failed to detect exit")

@router.get("/active/personnel", summary="Get active personnel entries")
async def get_active_personnel(current_user: dict = Depends(get_current_user)):
    """Liste le personnel actuellement en zone"""
    try:
        manager = get_scenario_manager()
        return {
            "status": "success",
            "active_personnel": [
                {
                    "personnel_id": pid,
                    "zone_id": data['zone_id'],
                    "entry_time": data['entry_time'].isoformat(),
                    "duration_seconds": (datetime.now() - data['entry_time']).total_seconds()
                }
                for pid, data in manager.active_personnel.items()
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching active personnel: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch active personnel")

@router.get("/active/vehicles", summary="Get active vehicles in zones")
async def get_active_vehicles(current_user: dict = Depends(get_current_user)):
    """Liste les véhicules actuellement en zone"""
    try:
        manager = get_scenario_manager()
        return {
            "status": "success",
            "active_vehicles": [
                {
                    "plate": plate,
                    "zone_id": data['zone_id'],
                    "entry_time": data['entry_time'].isoformat(),
                    "duration_seconds": (datetime.now() - data['entry_time']).total_seconds()
                }
                for plate, data in manager.active_vehicles.items()
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching active vehicles: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch active vehicles")

@router.get("/stats", summary="Get scenario statistics")
async def get_scenario_stats(
    hours: int = Query(24, ge=1, le=168),
    current_user: dict = Depends(get_current_user)
):
    """Statistiques des scénarios (dernières N heures)"""
    try:
        manager = get_scenario_manager()
        recent = [e for e in manager.recent_entries if 
                  (datetime.now() - e['timestamp']).total_seconds() < hours * 3600]
        
        scenarios = {}
        for entry in recent:
            scenario = entry['scenario'].value
            scenarios[scenario] = scenarios.get(scenario, 0) + 1
        
        return {
            "status": "success",
            "period_hours": hours,
            "total_entries": len(recent),
            "scenarios": scenarios
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stats")
