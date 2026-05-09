"""
Service de gestion des zones avec support polygones et occupancy
Priorité 3: Coordonnées polygonales, vérification ∈ zone, occupancy
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

logger = logging.getLogger("falcon_ai_vision.zones")


class ZoneService:
    """Service de gestion des zones virtuelles"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_zone(
        self,
        name: str,
        camera_id: int,
        polygon_coords: List[Tuple[float, float]],
        description: Optional[str] = None,
        sensitivity: int = 5
    ) -> dict:
        """Créer une zone virtuelle"""
        from vms.backend.models import Zone
        
        try:
            # Valider les coordonnées (minimum 3 points)
            if len(polygon_coords) < 3:
                return {
                    "success": False,
                    "message": "Zone needs at least 3 points"
                }
            
            zone = Zone(
                name=name,
                description=description,
                camera_id=camera_id,
                points=polygon_coords,
                sensitivity=sensitivity,
                is_active=True,
                created_at=datetime.utcnow()
            )
            self.db.add(zone)
            self.db.commit()
            
            logger.info(f"✅ Zone created: {name} with {len(polygon_coords)} points")
            
            return {
                "success": True,
                "zone_id": zone.id,
                "name": name,
                "points": len(polygon_coords),
                "message": "Zone created successfully"
            }
            
        except Exception as e:
            logger.error(f"Error: {e}")
            self.db.rollback()
            return {
                "success": False,
                "message": str(e)
            }
    
    def point_in_polygon(self, point: Tuple[float, float], polygon: List[Tuple[float, float]]) -> bool:
        """
        Vérifier si un point est dans un polygone (algorithme ray casting)
        Point = (x, y)
        Polygon = [(x1, y1), (x2, y2), ...]
        """
        x, y = point
        n = len(polygon)
        inside = False
        
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            
            if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            
            j = i
        
        return inside
    
    def record_entry(self, zone_id: int, personnel_id: Optional[int], vehicle_entry_id: Optional[int]) -> dict:
        """Enregistrer une entrée dans une zone"""
        from vms.backend.models import ZoneOccupancy, Zone
        
        try:
            zone = self.db.query(Zone).filter(Zone.id == zone_id).first()
            if not zone:
                return {"success": False, "message": "Zone not found"}
            
            occupancy = ZoneOccupancy(
                zone_id=zone_id,
                personnel_id=personnel_id,
                vehicle_entry_id=vehicle_entry_id,
                entry_time=datetime.utcnow(),
                is_active=True
            )
            self.db.add(occupancy)
            self.db.commit()
            
            logger.info(f"✅ Entry in zone {zone.name}")
            
            return {
                "success": True,
                "occupancy_id": occupancy.id,
                "message": "Entry recorded"
            }
            
        except Exception as e:
            logger.error(f"Error: {e}")
            self.db.rollback()
            return {
                "success": False,
                "message": str(e)
            }
    
    def record_exit(self, occupancy_id: int) -> dict:
        """Enregistrer une sortie d'une zone"""
        from vms.backend.models import ZoneOccupancy
        
        try:
            occupancy = self.db.query(ZoneOccupancy).filter(
                ZoneOccupancy.id == occupancy_id,
                ZoneOccupancy.is_active == True
            ).first()
            
            if not occupancy:
                return {"success": False, "message": "Occupancy not found"}
            
            occupancy.exit_time = datetime.utcnow()
            occupancy.is_active = False
            
            self.db.commit()
            
            logger.info(f"✅ Exit from zone")
            
            return {
                "success": True,
                "message": "Exit recorded"
            }
            
        except Exception as e:
            logger.error(f"Error: {e}")
            self.db.rollback()
            return {
                "success": False,
                "message": str(e)
            }
    
    def get_zone_occupancy(self, zone_id: int) -> dict:
        """Récupérer l'occupance actuell d'une zone"""
        from vms.backend.models import ZoneOccupancy, Zone, Personnel, VehicleEntry
        
        try:
            zone = self.db.query(Zone).filter(Zone.id == zone_id).first()
            if not zone:
                return {"success": False, "message": "Zone not found"}
            
            # Occupants actifs
            active_occupancy = self.db.query(ZoneOccupancy).filter(
                ZoneOccupancy.zone_id == zone_id,
                ZoneOccupancy.is_active == True
            ).all()
            
            occupants = []
            for occ in active_occupancy:
                occupant_info = {
                    "occupancy_id": occ.id,
                    "entry_time": occ.entry_time.isoformat(),
                    "type": None,
                    "name": None
                }
                
                if occ.personnel_id:
                    personnel = self.db.query(Personnel).filter(
                        Personnel.id == occ.personnel_id
                    ).first()
                    if personnel:
                        occupant_info["type"] = "personnel"
                        occupant_info["name"] = personnel.full_name
                
                elif occ.vehicle_entry_id:
                    vehicle = self.db.query(VehicleEntry).filter(
                        VehicleEntry.id == occ.vehicle_entry_id
                    ).first()
                    if vehicle:
                        occupant_info["type"] = "vehicle"
                        occupant_info["name"] = vehicle.license_plate
                
                occupants.append(occupant_info)
            
            return {
                "success": True,
                "zone_id": zone_id,
                "zone_name": zone.name,
                "current_occupancy": len(active_occupancy),
                "occupants": occupants
            }
            
        except Exception as e:
            logger.error(f"Error: {e}")
            return {
                "success": False,
                "message": str(e)
            }
    
    def get_zone_statistics(self, zone_id: int, days: int = 7) -> dict:
        """Récupérer les statistiques de zone"""
        from vms.backend.models import ZoneOccupancy
        
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            
            # Total passages
            total_entries = self.db.query(ZoneOccupancy).filter(
                ZoneOccupancy.zone_id == zone_id,
                ZoneOccupancy.entry_time >= cutoff
            ).count()
            
            # Durée moyenne
            avg_duration = self.db.query(func.avg(
                func.extract('epoch', ZoneOccupancy.exit_time - ZoneOccupancy.entry_time)
            )).filter(
                ZoneOccupancy.zone_id == zone_id,
                ZoneOccupancy.exit_time.isnot(None),
                ZoneOccupancy.entry_time >= cutoff
            ).scalar() or 0
            
            # Peak occupancy (max simultané)
            # Simulé: compter max occupants par heure
            
            return {
                "total_entries": total_entries,
                "avg_duration_seconds": round(float(avg_duration), 2),
                "period_days": days
            }
            
        except Exception as e:
            logger.error(f"Error: {e}")
            return {}
