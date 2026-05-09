"""
Vehicle Logger: Advanced database logging for vehicles
- Entry/exit events with timestamps
- License plate OCR data
- Vehicle classification (brand/model)
- Multi-camera tracking
- Daily summaries and exports
"""

from typing import Dict, Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class VehicleEventLogger:
    """Advanced vehicle event logger with OCR and classification data"""
    
    def __init__(self, db: Session):
        """
        Initialize logger
        
        Args:
            db: SQLAlchemy database session
        """
        self.db = db
    
    def log_vehicle_detection(
        self,
        camera_id: int,
        event_id: int,
        detection: Dict,
        track_info: Dict = None
    ) -> Optional[int]:
        """
        Log vehicle detection to database
        
        Args:
            camera_id: Camera ID from database
            event_id: Event ID (parent event)
            detection: Detection dict from VehicleDetector
            track_info: Tracking info from VehicleTracker (optional)
        
        Returns:
            Vehicle record ID or None if failed
        """
        try:
            from ..models import Vehicle
            
            vehicle = Vehicle(
                event_id=event_id,
                camera_id=camera_id,
                
                # Detection details
                license_plate=detection.get('license_plate'),
                vehicle_type=detection.get('class'),
                color=None,  # Can be added from image analysis
                brand=detection.get('brand'),
                model=detection.get('model'),
                
                # Detection confidence
                confidence=detection.get('confidence', 0.0),
                
                # Bounding box
                bounding_box={
                    'x': detection['bbox'][0],
                    'y': detection['bbox'][1],
                    'width': detection['bbox'][2] - detection['bbox'][0],
                    'height': detection['bbox'][3] - detection['bbox'][1]
                },
                
                # Tracking info
                direction=track_info.get('direction') if track_info else None,
                speed=track_info.get('speed_kmh') if track_info else None,
                
                # Timestamp
                detected_at=datetime.fromisoformat(detection.get('timestamp', datetime.now().isoformat()))
            )
            
            self.db.add(vehicle)
            self.db.commit()
            self.db.refresh(vehicle)
            
            logger.info(f"Vehicle logged: ID={vehicle.id}, plate={vehicle.license_plate}, camera_id={camera_id}")
            return vehicle.id
        
        except Exception as e:
            logger.error(f"Failed to log vehicle: {e}")
            self.db.rollback()
            return None
    
    def log_entry_event(
        self,
        camera_id: int,
        vehicle_track_id: int,
        vehicle_class: str,
        license_plate: Optional[str] = None,
        brand: Optional[str] = None,
        model: Optional[str] = None
    ) -> Optional[int]:
        """
        Log vehicle entry event (confirmed detection)
        
        Args:
            camera_id: Camera ID
            vehicle_track_id: Vehicle track ID from tracker
            vehicle_class: Vehicle type (car, truck, etc.)
            license_plate: License plate (optional)
            brand: Vehicle brand (optional)
            model: Vehicle model (optional)
        
        Returns:
            Event record ID or None if failed
        """
        try:
            from ..models import Event
            
            event = Event(
                camera_id=camera_id,
                event_type='vehicle_entry',
                severity='info',
                description=f"Vehicle entry detected: {vehicle_class}",
                detected_objects={
                    'type': vehicle_class,
                    'track_id': vehicle_track_id,
                    'license_plate': license_plate,
                    'brand': brand,
                    'model': model
                },
                detected_at=datetime.now(),
                is_acknowledged=False,
                is_archived=False,
                extra_data={
                    'vehicle_type': vehicle_class,
                    'track_id': vehicle_track_id,
                    'license_plate': license_plate,
                    'brand': brand,
                    'model': model
                }
            )
            
            # Set creator to system user (ID 1 or first admin)
            try:
                from ..models import User
                system_user = self.db.query(User).filter(User.is_admin == True).first()
                if system_user:
                    event.creator_id = system_user.id
                else:
                    event.creator_id = 1
            except:
                event.creator_id = 1
            
            self.db.add(event)
            self.db.commit()
            self.db.refresh(event)
            
            logger.info(f"Vehicle entry event logged: ID={event.id}, track_id={vehicle_track_id}")
            return event.id
        
        except Exception as e:
            logger.error(f"Failed to log entry event: {e}")
            self.db.rollback()
            return None
    
    def log_exit_event(
        self,
        camera_id: int,
        vehicle_track_id: int,
        vehicle_class: str,
        duration_seconds: float,
        distance_traveled_px: float,
        license_plate: Optional[str] = None
    ) -> Optional[int]:
        """
        Log vehicle exit event (track disappeared)
        
        Args:
            camera_id: Camera ID
            vehicle_track_id: Vehicle track ID
            vehicle_class: Vehicle type
            duration_seconds: Time vehicle was visible
            distance_traveled_px: Distance traveled in pixels
            license_plate: License plate (optional)
        
        Returns:
            Event record ID or None if failed
        """
        try:
            from ..models import Event
            
            event = Event(
                camera_id=camera_id,
                event_type='vehicle_exit',
                severity='info',
                description=f"Vehicle exit detected: {vehicle_class}",
                detected_objects={
                    'type': vehicle_class,
                    'track_id': vehicle_track_id,
                    'duration_seconds': duration_seconds,
                    'distance_traveled_px': distance_traveled_px,
                    'license_plate': license_plate
                },
                detected_at=datetime.now(),
                is_acknowledged=False,
                is_archived=False,
                extra_data={
                    'vehicle_type': vehicle_class,
                    'track_id': vehicle_track_id,
                    'duration_seconds': duration_seconds,
                    'distance_traveled_px': distance_traveled_px,
                    'license_plate': license_plate
                }
            )
            
            # Set creator
            try:
                from ..models import User
                system_user = self.db.query(User).filter(User.is_admin == True).first()
                if system_user:
                    event.creator_id = system_user.id
                else:
                    event.creator_id = 1
            except:
                event.creator_id = 1
            
            self.db.add(event)
            self.db.commit()
            self.db.refresh(event)
            
            logger.info(f"Vehicle exit event logged: ID={event.id}, track_id={vehicle_track_id}")
            return event.id
        
        except Exception as e:
            logger.error(f"Failed to log exit event: {e}")
            self.db.rollback()
            return None
    
    def get_vehicles_by_plate(self, plate: str, limit: int = 50) -> List[Dict]:
        """
        Get vehicle records by license plate
        
        Args:
            plate: License plate to search
            limit: Maximum results
        
        Returns:
            List of vehicle records
        """
        try:
            from ..models import Vehicle
            
            vehicles = self.db.query(Vehicle)\
                .filter(Vehicle.license_plate.ilike(f"%{plate}%"))\
                .order_by(Vehicle.detected_at.desc())\
                .limit(limit)\
                .all()
            
            return [
                {
                    'id': v.id,
                    'camera_id': v.camera_id,
                    'license_plate': v.license_plate,
                    'vehicle_type': v.vehicle_type,
                    'brand': v.brand,
                    'model': v.model,
                    'confidence': v.confidence,
                    'detected_at': v.detected_at.isoformat() if v.detected_at else None
                }
                for v in vehicles
            ]
        
        except Exception as e:
            logger.error(f"Failed to query vehicles: {e}")
            return []
    
    def get_vehicles_by_camera(self, camera_id: int, hours: int = 24, limit: int = 100) -> List[Dict]:
        """
        Get recent vehicle detections by camera
        
        Args:
            camera_id: Camera ID
            hours: Look back hours
            limit: Maximum results
        
        Returns:
            List of vehicle records
        """
        try:
            from ..models import Vehicle
            from datetime import timezone, timedelta
            
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            vehicles = self.db.query(Vehicle)\
                .filter(Vehicle.camera_id == camera_id)\
                .filter(Vehicle.detected_at >= cutoff_time)\
                .order_by(Vehicle.detected_at.desc())\
                .limit(limit)\
                .all()
            
            return [
                {
                    'id': v.id,
                    'license_plate': v.license_plate,
                    'vehicle_type': v.vehicle_type,
                    'brand': v.brand,
                    'model': v.model,
                    'confidence': v.confidence,
                    'detected_at': v.detected_at.isoformat() if v.detected_at else None
                }
                for v in vehicles
            ]
        
        except Exception as e:
            logger.error(f"Failed to query cameras: {e}")
            return []
    
    def get_vehicle_statistics(self, camera_id: int = None, hours: int = 24) -> Dict:
        """
        Get vehicle statistics
        
        Args:
            camera_id: Camera ID filter (optional)
            hours: Look back hours
        
        Returns:
            Statistics dict
        """
        try:
            from ..models import Vehicle
            from datetime import timezone, timedelta
            
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            query = self.db.query(Vehicle)\
                .filter(Vehicle.detected_at >= cutoff_time)
            
            if camera_id:
                query = query.filter(Vehicle.camera_id == camera_id)
            
            vehicles = query.all()
            
            # Count by type
            type_counts = {}
            for v in vehicles:
                vehicle_type = v.vehicle_type or 'unknown'
                type_counts[vehicle_type] = type_counts.get(vehicle_type, 0) + 1
            
            # Plates detected
            plates_with_confidence = [
                (v.license_plate, v.confidence)
                for v in vehicles
                if v.license_plate
            ]
            unique_plates = len(set(v.license_plate for v in vehicles if v.license_plate))
            
            # Average confidence
            avg_confidence = sum(v.confidence for v in vehicles) / len(vehicles) if vehicles else 0
            
            return {
                'total_vehicles': len(vehicles),
                'by_type': type_counts,
                'unique_plates': unique_plates,
                'avg_confidence': round(avg_confidence, 3),
                'time_period_hours': hours
            }
        
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            return {}


# Backward-compatible alias used by existing routers.
class VehicleLogger(VehicleEventLogger):
    pass
