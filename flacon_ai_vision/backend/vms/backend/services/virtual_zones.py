"""
Virtual Zones Management Service
Manages virtual zones (polygons/rectangles) for area monitoring, occupancy tracking, and entry/exit detection
"""

import logging
import json
from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import threading

logger = logging.getLogger(__name__)

# Ensure data directory exists
ZONES_DATA_DIR = Path("data/zones")
ZONES_DATA_DIR.mkdir(parents=True, exist_ok=True)
ZONES_METADATA_FILE = ZONES_DATA_DIR / "zones_metadata.json"
OCCUPANCY_HISTORY_FILE = ZONES_DATA_DIR / "occupancy_history.json"


class ZoneType(Enum):
    """Zone shape types"""
    RECTANGLE = "rectangle"  # Format: {x, y, width, height}
    POLYGON = "polygon"      # Format: list of {x, y} vertices


@dataclass
class Zone:
    """Zone object"""
    zone_id: str
    name: str
    type: str  # "rectangle" or "polygon"
    coordinates: Dict  # {x, y, width, height} or {vertices: [[x,y], ...]}
    camera_ids: List[int]
    occupancy_count: int = 0
    created_at: str = None
    updated_at: str = None
    description: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()


class VirtualZonesService:
    """Service for managing virtual zones and occupancy tracking"""
    
    def __init__(self):
        """Initialize virtual zones service"""
        self.zones: Dict[str, Zone] = {}
        self.occupancy_lock = threading.Lock()
        self.metadata_lock = threading.Lock()
        self.occupancy_history: List[Dict] = []
        self._load_zones()
        logger.info(f"VirtualZonesService initialized with {len(self.zones)} zones")

    def _load_zones(self):
        """Load zones from metadata file"""
        try:
            if ZONES_METADATA_FILE.exists():
                with open(ZONES_METADATA_FILE, 'r') as f:
                    zones_data = json.load(f)
                    for zone_data in zones_data:
                        zone = Zone(**zone_data)
                        self.zones[zone.zone_id] = zone
                logger.info(f"Loaded {len(self.zones)} zones from metadata")
        except Exception as e:
            logger.error(f"Error loading zones: {e}")

    def _save_zones(self):
        """Save zones to metadata file"""
        try:
            with self.metadata_lock:
                zones_list = [asdict(zone) for zone in self.zones.values()]
                with open(ZONES_METADATA_FILE, 'w') as f:
                    json.dump(zones_list, f, indent=2)
                logger.info(f"Saved {len(self.zones)} zones to metadata")
        except Exception as e:
            logger.error(f"Error saving zones: {e}")

    def _save_occupancy_history(self):
        """Save occupancy history to file"""
        try:
            with self.metadata_lock:
                with open(OCCUPANCY_HISTORY_FILE, 'w') as f:
                    json.dump(self.occupancy_history[-10000:], f, indent=2)  # Keep last 10k entries
        except Exception as e:
            logger.error(f"Error saving occupancy history: {e}")

    def create_zone(self, zone_id: str, name: str, zone_type: str, 
                   coordinates: Dict, camera_ids: List[int], 
                   description: str = "") -> Dict:
        """
        Create a new virtual zone
        
        Args:
            zone_id: Unique zone identifier
            name: Zone name
            zone_type: "rectangle" or "polygon"
            coordinates: Zone coordinates {x, y, width, height} or {vertices: [[x,y], ...]}
            camera_ids: List of camera IDs monitoring this zone
            description: Zone description
            
        Returns:
            {"status": "success", "zone_id": ..., "name": ...} or {"status": "error", "message": ...}
        """
        try:
            if zone_id in self.zones:
                return {"status": "error", "message": f"Zone {zone_id} already exists"}
            
            zone = Zone(
                zone_id=zone_id,
                name=name,
                type=zone_type,
                coordinates=coordinates,
                camera_ids=camera_ids,
                description=description
            )
            
            with self.metadata_lock:
                self.zones[zone_id] = zone
                self._save_zones()
            
            logger.info(f"Created zone: {zone_id} ({name})")
            return {
                "status": "success",
                "zone_id": zone_id,
                "name": name,
                "type": zone_type,
                "created_at": zone.created_at
            }
        except Exception as e:
            logger.error(f"Error creating zone: {e}")
            return {"status": "error", "message": str(e)}

    def update_zone(self, zone_id: str, **kwargs) -> Dict:
        """
        Update zone properties
        
        Args:
            zone_id: Zone identifier
            **kwargs: Fields to update (name, coordinates, camera_ids, description)
            
        Returns:
            {"status": "success"} or {"status": "error"}
        """
        try:
            if zone_id not in self.zones:
                return {"status": "error", "message": f"Zone {zone_id} not found"}
            
            zone = self.zones[zone_id]
            with self.metadata_lock:
                for key, value in kwargs.items():
                    if key in ['name', 'coordinates', 'camera_ids', 'description']:
                        setattr(zone, key, value)
                zone.updated_at = datetime.now().isoformat()
                self._save_zones()
            
            logger.info(f"Updated zone: {zone_id}")
            return {"status": "success", "zone_id": zone_id}
        except Exception as e:
            logger.error(f"Error updating zone: {e}")
            return {"status": "error", "message": str(e)}

    def delete_zone(self, zone_id: str) -> Dict:
        """Delete a zone"""
        try:
            if zone_id not in self.zones:
                return {"status": "error", "message": f"Zone {zone_id} not found"}
            
            with self.metadata_lock:
                del self.zones[zone_id]
                self._save_zones()
            
            logger.info(f"Deleted zone: {zone_id}")
            return {"status": "success", "message": f"Zone {zone_id} deleted"}
        except Exception as e:
            logger.error(f"Error deleting zone: {e}")
            return {"status": "error", "message": str(e)}

    def get_zone(self, zone_id: str) -> Optional[Dict]:
        """Get zone details"""
        if zone_id not in self.zones:
            return None
        zone = self.zones[zone_id]
        return asdict(zone)

    def list_zones(self, camera_id: Optional[int] = None) -> List[Dict]:
        """
        List all zones or zones for specific camera
        
        Args:
            camera_id: Optional camera ID to filter zones
            
        Returns:
            List of zone dictionaries
        """
        zones_list = []
        for zone in self.zones.values():
            if camera_id is None or camera_id in zone.camera_ids:
                zones_list.append(asdict(zone))
        return zones_list

    def add_camera_to_zone(self, zone_id: str, camera_id: int) -> Dict:
        """Add camera to zone monitoring"""
        try:
            if zone_id not in self.zones:
                return {"status": "error", "message": f"Zone {zone_id} not found"}
            
            zone = self.zones[zone_id]
            if camera_id not in zone.camera_ids:
                with self.metadata_lock:
                    zone.camera_ids.append(camera_id)
                    self._save_zones()
            
            return {"status": "success", "message": f"Camera {camera_id} added to zone {zone_id}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def remove_camera_from_zone(self, zone_id: str, camera_id: int) -> Dict:
        """Remove camera from zone monitoring"""
        try:
            if zone_id not in self.zones:
                return {"status": "error", "message": f"Zone {zone_id} not found"}
            
            zone = self.zones[zone_id]
            if camera_id in zone.camera_ids:
                with self.metadata_lock:
                    zone.camera_ids.remove(camera_id)
                    self._save_zones()
            
            return {"status": "success", "message": f"Camera {camera_id} removed from zone {zone_id}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def point_in_zone(self, zone_id: str, point: Tuple[float, float]) -> bool:
        """
        Check if point is inside zone
        
        Args:
            zone_id: Zone identifier
            point: (x, y) tuple
            
        Returns:
            True if point is in zone
        """
        if zone_id not in self.zones:
            return False
        
        zone = self.zones[zone_id]
        x, y = point
        
        if zone.type == "rectangle":
            coords = zone.coordinates
            rect_x, rect_y = coords['x'], coords['y']
            width, height = coords['width'], coords['height']
            return (rect_x <= x <= rect_x + width and 
                    rect_y <= y <= rect_y + height)
        
        elif zone.type == "polygon":
            # Ray casting algorithm for polygon containment
            vertices = zone.coordinates.get('vertices', [])
            return self._point_in_polygon(point, vertices)
        
        return False

    @staticmethod
    def _point_in_polygon(point: Tuple[float, float], vertices: List[List[float]]) -> bool:
        """
        Ray casting algorithm for point-in-polygon detection
        
        Args:
            point: (x, y) tuple
            vertices: List of [x, y] vertices
            
        Returns:
            True if point is inside polygon
        """
        x, y = point
        inside = False
        
        p1x, p1y = vertices[0]
        for i in range(1, len(vertices) + 1):
            p2x, p2y = vertices[i % len(vertices)]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside

    def increment_occupancy(self, zone_id: str, object_id: str, object_type: str) -> Dict:
        """
        Increment occupancy count for zone (person/vehicle entry)
        
        Args:
            zone_id: Zone identifier
            object_id: Person/vehicle identifier
            object_type: "person" or "vehicle"
            
        Returns:
            {"status": "success", "zone_id": ..., "occupancy": ...}
        """
        try:
            if zone_id not in self.zones:
                return {"status": "error", "message": f"Zone {zone_id} not found"}
            
            zone = self.zones[zone_id]
            with self.occupancy_lock:
                zone.occupancy_count += 1
                self._record_occupancy_event(zone_id, object_id, object_type, "entry")
            
            logger.info(f"Occupancy +1 in zone {zone_id}: {zone.occupancy_count}")
            return {
                "status": "success",
                "zone_id": zone_id,
                "occupancy": zone.occupancy_count,
                "event": "entry"
            }
        except Exception as e:
            logger.error(f"Error incrementing occupancy: {e}")
            return {"status": "error", "message": str(e)}

    def decrement_occupancy(self, zone_id: str, object_id: str, object_type: str) -> Dict:
        """
        Decrement occupancy count for zone (person/vehicle exit)
        
        Args:
            zone_id: Zone identifier
            object_id: Person/vehicle identifier
            object_type: "person" or "vehicle"
            
        Returns:
            {"status": "success", "zone_id": ..., "occupancy": ...}
        """
        try:
            if zone_id not in self.zones:
                return {"status": "error", "message": f"Zone {zone_id} not found"}
            
            zone = self.zones[zone_id]
            with self.occupancy_lock:
                if zone.occupancy_count > 0:
                    zone.occupancy_count -= 1
                    self._record_occupancy_event(zone_id, object_id, object_type, "exit")
            
            logger.info(f"Occupancy -1 in zone {zone_id}: {zone.occupancy_count}")
            return {
                "status": "success",
                "zone_id": zone_id,
                "occupancy": zone.occupancy_count,
                "event": "exit"
            }
        except Exception as e:
            logger.error(f"Error decrementing occupancy: {e}")
            return {"status": "error", "message": str(e)}

    def _record_occupancy_event(self, zone_id: str, object_id: str, 
                               object_type: str, event: str):
        """Record occupancy change event"""
        try:
            event_record = {
                "timestamp": datetime.now().isoformat(),
                "zone_id": zone_id,
                "object_id": object_id,
                "object_type": object_type,
                "event": event,  # "entry" or "exit"
                "occupancy_count": self.zones[zone_id].occupancy_count
            }
            self.occupancy_history.append(event_record)
            
            # Save periodically (every 100 events)
            if len(self.occupancy_history) % 100 == 0:
                self._save_occupancy_history()
        except Exception as e:
            logger.error(f"Error recording occupancy event: {e}")

    def get_zone_occupancy(self, zone_id: str) -> Optional[Dict]:
        """Get current occupancy for zone"""
        if zone_id not in self.zones:
            return None
        
        zone = self.zones[zone_id]
        return {
            "zone_id": zone_id,
            "name": zone.name,
            "occupancy_count": zone.occupancy_count,
            "timestamp": datetime.now().isoformat()
        }

    def get_occupancy_history(self, zone_id: str, limit: int = 100) -> List[Dict]:
        """Get occupancy history for zone"""
        history = [h for h in self.occupancy_history if h['zone_id'] == zone_id]
        return history[-limit:]

    def get_zones_stats(self) -> Dict:
        """Get statistics about all zones"""
        total_zones = len(self.zones)
        total_occupancy = sum(z.occupancy_count for z in self.zones.values())
        rectangle_zones = sum(1 for z in self.zones.values() if z.type == "rectangle")
        polygon_zones = sum(1 for z in self.zones.values() if z.type == "polygon")
        
        return {
            "total_zones": total_zones,
            "rectangle_zones": rectangle_zones,
            "polygon_zones": polygon_zones,
            "total_occupancy": total_occupancy,
            "total_events": len(self.occupancy_history),
            "timestamp": datetime.now().isoformat()
        }

    def search_object_in_zones(self, point: Tuple[float, float]) -> List[str]:
        """
        Find all zones containing a point
        
        Args:
            point: (x, y) tuple
            
        Returns:
            List of zone IDs containing the point
        """
        containing_zones = []
        for zone_id, zone in self.zones.items():
            if self.point_in_zone(zone_id, point):
                containing_zones.append(zone_id)
        return containing_zones


# Global instance
_virtual_zones_service: Optional[VirtualZonesService] = None


def get_virtual_zones_service() -> VirtualZonesService:
    """Get or create global VirtualZonesService instance"""
    global _virtual_zones_service
    if _virtual_zones_service is None:
        _virtual_zones_service = VirtualZonesService()
    return _virtual_zones_service
