"""
Virtual Zones Router
Endpoints for managing virtual zones, occupancy tracking, and entry/exit detection
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from vms.backend.core.security import get_current_user
from vms.backend.routers.ws import broadcast_api_event
from vms.backend.services.virtual_zones import get_virtual_zones_service
from pydantic import BaseModel


# Request/Response Models
class ZoneCreate(BaseModel):
    zone_id: str
    name: str
    type: str  # "rectangle" or "polygon"
    coordinates: Dict  # {x, y, width, height} or {vertices: [[x,y], ...]}
    camera_ids: List[int]
    description: Optional[str] = ""


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    coordinates: Optional[Dict] = None
    camera_ids: Optional[List[int]] = None
    description: Optional[str] = None


class OccupancyEvent(BaseModel):
    zone_id: str
    object_id: str
    object_type: str  # "person" or "vehicle"
    event: str  # "entry" or "exit"


router = APIRouter(prefix="/api/zones", tags=["Virtual Zones"])


async def _broadcast_zone_occupancy_event(
    *,
    zone_id: str,
    object_id: str,
    object_type: str,
    event: str,
    occupancy_count: int,
) -> None:
    await broadcast_api_event(
        "occupancy",
        {
            "zone_id": zone_id,
            "object_id": object_id,
            "object_type": object_type,
            "event": event,
            "count": int(occupancy_count),
            "current_occupancy": int(occupancy_count),
        },
        channel="occupancy",
    )


def _build_list_zones_response(camera_id: Optional[int] = None) -> Dict:
    zones_service = get_virtual_zones_service()
    zones = zones_service.list_zones(camera_id)
    return {
        "status": "success",
        "count": len(zones),
        "zones": zones,
        "timestamp": datetime.now().isoformat()
    }


@router.get("")
@router.get("/")
async def list_zones_root(
    camera_id: Optional[int] = None,
    current_user = Depends(get_current_user)
) -> Dict:
    """Compatibility route for clients calling GET /api/zones."""
    try:
        return _build_list_zones_response(camera_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_zone(zone: ZoneCreate, current_user = Depends(get_current_user)) -> Dict:
    """
    Create a new virtual zone
    
    Args:
        zone: Zone creation request
        
    Returns:
        {"status": "success", "zone_id": ..., "name": ...}
    """
    try:
        zones_service = get_virtual_zones_service()
        result = zones_service.create_zone(
            zone_id=zone.zone_id,
            name=zone.name,
            zone_type=zone.type,
            coordinates=zone.coordinates,
            camera_ids=zone.camera_ids,
            description=zone.description
        )
        
        if result['status'] == 'success':
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get('message', 'Failed to create zone'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_zones(
    camera_id: Optional[int] = None,
    current_user = Depends(get_current_user)
) -> Dict:
    """
    List all zones or zones for specific camera
    
    Args:
        camera_id: Optional camera ID to filter zones
        
    Returns:
        {"status": "success", "zones": [...], "count": N}
    """
    try:
        return _build_list_zones_response(camera_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{zone_id}")
async def get_zone(zone_id: str, current_user = Depends(get_current_user)) -> Dict:
    """Get details for a specific zone"""
    try:
        zones_service = get_virtual_zones_service()
        zone = zones_service.get_zone(zone_id)
        
        if zone:
            return {
                "status": "success",
                "zone": zone,
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=404, detail=f"Zone {zone_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{zone_id}")
async def update_zone(
    zone_id: str,
    zone_update: ZoneUpdate,
    current_user = Depends(get_current_user)
) -> Dict:
    """Update zone properties"""
    try:
        zones_service = get_virtual_zones_service()
        
        # Build update kwargs from non-None fields
        update_data = {}
        if zone_update.name is not None:
            update_data['name'] = zone_update.name
        if zone_update.coordinates is not None:
            update_data['coordinates'] = zone_update.coordinates
        if zone_update.camera_ids is not None:
            update_data['camera_ids'] = zone_update.camera_ids
        if zone_update.description is not None:
            update_data['description'] = zone_update.description
        
        result = zones_service.update_zone(zone_id, **update_data)
        
        if result['status'] == 'success':
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get('message', 'Failed to update zone'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{zone_id}")
async def delete_zone(zone_id: str, current_user = Depends(get_current_user)) -> Dict:
    """Delete a zone"""
    try:
        zones_service = get_virtual_zones_service()
        result = zones_service.delete_zone(zone_id)
        
        if result['status'] == 'success':
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get('message', 'Failed to delete zone'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{zone_id}/cameras/add")
async def add_camera_to_zone(
    zone_id: str,
    camera_id: int,
    current_user = Depends(get_current_user)
) -> Dict:
    """Add camera to zone monitoring"""
    try:
        zones_service = get_virtual_zones_service()
        result = zones_service.add_camera_to_zone(zone_id, camera_id)
        
        if result['status'] == 'success':
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get('message'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{zone_id}/cameras/remove")
async def remove_camera_from_zone(
    zone_id: str,
    camera_id: int,
    current_user = Depends(get_current_user)
) -> Dict:
    """Remove camera from zone monitoring"""
    try:
        zones_service = get_virtual_zones_service()
        result = zones_service.remove_camera_from_zone(zone_id, camera_id)
        
        if result['status'] == 'success':
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get('message'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{zone_id}/occupancy")
async def get_zone_occupancy(
    zone_id: str,
    current_user = Depends(get_current_user)
) -> Dict:
    """Get current occupancy for a zone"""
    try:
        zones_service = get_virtual_zones_service()
        occupancy = zones_service.get_zone_occupancy(zone_id)
        
        if occupancy:
            return {
                "status": "success",
                "occupancy": occupancy,
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=404, detail=f"Zone {zone_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{zone_id}/occupancy/entry")
async def record_zone_entry(
    zone_id: str,
    object_id: str,
    object_type: str = "person",
    current_user = Depends(get_current_user)
) -> Dict:
    """Record person/vehicle entry into zone"""
    try:
        zones_service = get_virtual_zones_service()
        result = zones_service.increment_occupancy(zone_id, object_id, object_type)
        
        if result['status'] == 'success':
            await _broadcast_zone_occupancy_event(
                zone_id=zone_id,
                object_id=object_id,
                object_type=object_type,
                event="entry",
                occupancy_count=int(result.get("occupancy", 0)),
            )
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get('message'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{zone_id}/occupancy/exit")
async def record_zone_exit(
    zone_id: str,
    object_id: str,
    object_type: str = "person",
    current_user = Depends(get_current_user)
) -> Dict:
    """Record person/vehicle exit from zone"""
    try:
        zones_service = get_virtual_zones_service()
        result = zones_service.decrement_occupancy(zone_id, object_id, object_type)
        
        if result['status'] == 'success':
            await _broadcast_zone_occupancy_event(
                zone_id=zone_id,
                object_id=object_id,
                object_type=object_type,
                event="exit",
                occupancy_count=int(result.get("occupancy", 0)),
            )
            return result
        else:
            raise HTTPException(status_code=400, detail=result.get('message'))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{zone_id}/history")
async def get_occupancy_history(
    zone_id: str,
    limit: int = 100,
    current_user = Depends(get_current_user)
) -> Dict:
    """Get occupancy history for a zone"""
    try:
        zones_service = get_virtual_zones_service()
        history = zones_service.get_occupancy_history(zone_id, limit)
        
        return {
            "status": "success",
            "zone_id": zone_id,
            "count": len(history),
            "history": history,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{zone_id}/detect")
async def detect_in_zone(
    zone_id: str,
    x: float,
    y: float,
    current_user = Depends(get_current_user)
) -> Dict:
    """
    Check if a point is inside a zone
    
    Args:
        zone_id: Zone identifier
        x: X coordinate
        y: Y coordinate
        
    Returns:
        {"status": "success", "in_zone": bool, "zone_id": ...}
    """
    try:
        zones_service = get_virtual_zones_service()
        in_zone = zones_service.point_in_zone(zone_id, (x, y))
        
        return {
            "status": "success",
            "zone_id": zone_id,
            "point": {"x": x, "y": y},
            "in_zone": in_zone,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect-all")
async def detect_in_all_zones(
    x: float,
    y: float,
    current_user = Depends(get_current_user)
) -> Dict:
    """
    Find all zones containing a point
    
    Args:
        x: X coordinate
        y: Y coordinate
        
    Returns:
        {"status": "success", "zones": [...], "count": N}
    """
    try:
        zones_service = get_virtual_zones_service()
        containing_zones = zones_service.search_object_in_zones((x, y))
        
        zones_info = [zones_service.get_zone(z_id) for z_id in containing_zones]
        zones_info = [z for z in zones_info if z is not None]
        
        return {
            "status": "success",
            "point": {"x": x, "y": y},
            "zones_count": len(zones_info),
            "zones": zones_info,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_zones_stats(current_user = Depends(get_current_user)) -> Dict:
    """Get statistics about all zones"""
    try:
        zones_service = get_virtual_zones_service()
        stats = zones_service.get_zones_stats()
        
        return {
            "status": "success",
            "stats": stats,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
