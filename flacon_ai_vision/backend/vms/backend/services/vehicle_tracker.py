"""
Advanced Vehicle Tracker: Track vehicles across frames with full details
- Camera ID tracking
- Entry/Exit timestamps
- License plate OCR integration
- Vehicle classification
- Multi-frame trajectory analysis
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import math

logger = logging.getLogger(__name__)


@dataclass
class TrackedVehicle:
    """Represents a tracked vehicle across frames"""
    
    vehicle_id: str  # Unique ID for this tracked vehicle
    class_name: str  # 'car', 'truck', 'bus'
    first_detection_time: datetime = field(default_factory=datetime.now)
    last_detection_time: datetime = field(default_factory=datetime.now)
    last_position: Tuple[int, int] = (0, 0)  # (cx, cy)
    detections_count: int = 0
    
    # Classification info
    vehicle_type: str = 'unknown'
    brand: str = 'unknown'
    model: str = 'unknown'
    
    # Entry/Exit times
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    status: str = 'active'  # 'active', 'exited', 'lost'
    
    # Statistics
    max_confidence: float = 0.0
    avg_confidence: float = 0.0
    confidence_sum: float = 0.0
    
    # Camera info
    camera_id: str = 'unknown'
    entry_location: Optional[Tuple[int, int]] = None
    exit_location: Optional[Tuple[int, int]] = None
    
    # License plate
    license_plate: Optional[str] = None
    plate_confidence: float = 0.0
    
    # Position history
    positions: List[Tuple[int, int]] = field(default_factory=list)
    bboxes: List[List[int]] = field(default_factory=list)


class VehicleTracker:
    """
    Track vehicles across video frames
    Maintains vehicle IDs, entry/exit times, and spatial information
    """
    
    def __init__(
        self,
        camera_id: str,
        max_distance: float = 100.0,
        max_age_frames: int = 30,
        min_detections: int = 3
    ):
        """
        Initialize tracker
        
        Args:
            camera_id: ID of camera for this tracker
            max_distance: Max distance (pixels) to link detection to existing track
            max_age_frames: Max frames without detection before marking as lost
            min_detections: Min detections required to confirm vehicle
        """
        self.camera_id = camera_id
        self.max_distance = max_distance
        self.max_age_frames = max_age_frames
        self.min_detections = min_detections
        
        self.tracked_vehicles: Dict[str, TrackedVehicle] = {}
        self.next_vehicle_id = 1
        self.frame_count = 0
        
        logger.info(f"VehicleTracker initialized for camera '{camera_id}'")
    
    def _calculate_distance(
        self,
        pos1: Tuple[int, int],
        pos2: Tuple[int, int]
    ) -> float:
        """Calculate Euclidean distance between two positions"""
        return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)
    
    def _find_best_match(
        self,
        detection: Dict,
        active_vehicles: List[TrackedVehicle]
    ) -> Optional[TrackedVehicle]:
        """Find best matching tracked vehicle for a detection"""
        
        center = detection.get('center', (0, 0))
        best_vehicle = None
        best_distance = self.max_distance
        
        for vehicle in active_vehicles:
            distance = self._calculate_distance(center, vehicle.last_position)
            
            if distance < best_distance:
                best_distance = distance
                best_vehicle = vehicle
        
        return best_vehicle
    
    def update(self, detections: List[Dict]) -> Dict:
        """
        Update tracker with new detections
        
        Args:
            detections: List of vehicle detections from current frame
        
        Returns:
            {
                'tracked_vehicles': [TrackedVehicle, ...],
                'new_vehicles': int,
                'vehicles_entered': [vehicle_id, ...],
                'vehicles_exited': [vehicle_id, ...],
                'frame': int
            }
        """
        self.frame_count += 1
        
        # Get active vehicles
        active_vehicles = [
            v for v in self.tracked_vehicles.values()
            if v.status == 'active'
        ]
        
        matched_vehicles = set()
        new_vehicles = []
        entered_vehicles = []
        exited_vehicles = []
        
        # Match detections to existing tracks
        for detection in detections:
            matched_vehicle = self._find_best_match(detection, active_vehicles)
            
            if matched_vehicle:
                # Update existing track
                matched_vehicle.detections_count += 1
                matched_vehicle.last_detection_time = datetime.now()
                matched_vehicle.last_position = detection.get('center', (0, 0))
                matched_vehicle.positions.append(matched_vehicle.last_position)
                matched_vehicle.bboxes.append(detection.get('bbox', [0, 0, 0, 0]))
                
                # Keep history limited
                if len(matched_vehicle.positions) > 30:
                    matched_vehicle.positions = matched_vehicle.positions[-30:]
                    matched_vehicle.bboxes = matched_vehicle.bboxes[-30:]
                
                # Update confidence stats
                confidence = detection.get('confidence', 0)
                matched_vehicle.confidence_sum += confidence
                matched_vehicle.avg_confidence = matched_vehicle.confidence_sum / matched_vehicle.detections_count
                matched_vehicle.max_confidence = max(matched_vehicle.max_confidence, confidence)
                
                # Update plate if found
                plate_data = detection.get('plate')
                if plate_data and not matched_vehicle.license_plate:
                    matched_vehicle.license_plate = plate_data.get('text')
                    matched_vehicle.plate_confidence = plate_data.get('confidence', 0)
                
                # Update classification
                classification = detection.get('classification', {})
                if classification.get('type') != 'unknown':
                    matched_vehicle.vehicle_type = classification.get('type', 'unknown')
                    matched_vehicle.brand = classification.get('brand', 'unknown')
                    matched_vehicle.model = classification.get('model', 'unknown')
                
                matched_vehicles.add(matched_vehicle.vehicle_id)
                
                # Check if vehicle just entered (first confirmed detection)
                if matched_vehicle.detections_count == self.min_detections:
                    if not matched_vehicle.entry_time:
                        matched_vehicle.entry_time = datetime.now()
                        matched_vehicle.entry_location = detection.get('center')
                        entered_vehicles.append(matched_vehicle.vehicle_id)
            
            else:
                # Create new track
                vehicle_id = f"VEH_{self.camera_id}_{self.next_vehicle_id:04d}"
                self.next_vehicle_id += 1
                
                new_vehicle = TrackedVehicle(
                    vehicle_id=vehicle_id,
                    class_name=detection.get('class', 'unknown'),
                    first_detection_time=datetime.now(),
                    last_detection_time=datetime.now(),
                    last_position=detection.get('center', (0, 0)),
                    detections_count=1,
                    camera_id=self.camera_id,
                    vehicle_type=detection.get('classification', {}).get('type', 'unknown'),
                    brand=detection.get('classification', {}).get('brand', 'unknown'),
                    model=detection.get('classification', {}).get('model', 'unknown')
                )
                
                # Check plate
                plate_data = detection.get('plate')
                if plate_data:
                    new_vehicle.license_plate = plate_data.get('text')
                    new_vehicle.plate_confidence = plate_data.get('confidence', 0)
                
                new_vehicle.positions.append(new_vehicle.last_position)
                new_vehicle.bboxes.append(detection.get('bbox', [0, 0, 0, 0]))
                
                self.tracked_vehicles[vehicle_id] = new_vehicle
                new_vehicles.append(new_vehicle)
        
        # Check for lost tracks
        for vehicle in active_vehicles:
            if vehicle.vehicle_id not in matched_vehicles:
                frames_since_detection = (
                    (datetime.now() - vehicle.last_detection_time).total_seconds() * 30  # Assume 30 fps
                )
                
                if frames_since_detection > self.max_age_frames:
                    vehicle.status = 'lost'
                    vehicle.exit_time = datetime.now()
                    vehicle.exit_location = vehicle.last_position
                    exited_vehicles.append(vehicle.vehicle_id)
        
        return {
            'tracked_vehicles': list(self.tracked_vehicles.values()),
            'active_vehicles': [v for v in self.tracked_vehicles.values() if v.status == 'active'],
            'new_vehicles': len(new_vehicles),
            'new_vehicles_list': new_vehicles,
            'vehicles_entered': entered_vehicles,
            'vehicles_exited': exited_vehicles,
            'frame': self.frame_count,
            'total_vehicles_tracked': len(self.tracked_vehicles)
        }
    
    def get_vehicle(self, vehicle_id: str) -> Optional[TrackedVehicle]:
        """Get tracked vehicle by ID"""
        return self.tracked_vehicles.get(vehicle_id)
    
    def get_all_vehicles(self) -> List[TrackedVehicle]:
        """Get all tracked vehicles"""
        return list(self.tracked_vehicles.values())
    
    def get_active_vehicles(self) -> List[TrackedVehicle]:
        """Get only active vehicles"""
        return [v for v in self.tracked_vehicles.values() if v.status == 'active']
    
    def get_exited_vehicles(self) -> List[TrackedVehicle]:
        """Get vehicles that have exited"""
        return [v for v in self.tracked_vehicles.values() if v.status in ['exited', 'lost']]
    
    def get_vehicle_summary(self, vehicle_id: str) -> Optional[Dict]:
        """Get summary of tracked vehicle"""
        vehicle = self.get_vehicle(vehicle_id)
        if not vehicle:
            return None
        
        duration = (vehicle.last_detection_time - vehicle.first_detection_time).total_seconds()
        
        return {
            'vehicle_id': vehicle.vehicle_id,
            'license_plate': vehicle.license_plate,
            'class': vehicle.class_name,
            'type': vehicle.vehicle_type,
            'brand': vehicle.brand,
            'model': vehicle.model,
            'camera_id': vehicle.camera_id,
            'detections': vehicle.detections_count,
            'first_seen': vehicle.first_detection_time.isoformat(),
            'last_seen': vehicle.last_detection_time.isoformat(),
            'entry_time': vehicle.entry_time.isoformat() if vehicle.entry_time else None,
            'exit_time': vehicle.exit_time.isoformat() if vehicle.exit_time else None,
            'duration_seconds': round(duration, 2),
            'status': vehicle.status,
            'confidence': {
                'max': vehicle.max_confidence,
                'avg': round(vehicle.avg_confidence, 3)
            }
        }
    
    def get_all_summaries(self) -> List[Dict]:
        """Get summaries of all tracked vehicles"""
        return [
            self.get_vehicle_summary(v.vehicle_id)
            for v in self.tracked_vehicles.values()
        ]
    
    def cleanup_old_tracks(self, max_age_hours: int = 24):
        """Remove very old tracks to free memory"""
        now = datetime.now()
        cutoff_time = now - timedelta(hours=max_age_hours)
        
        vehicles_to_remove = [
            v_id for v_id, v in self.tracked_vehicles.items()
            if v.last_detection_time < cutoff_time
        ]
        
        for v_id in vehicles_to_remove:
            del self.tracked_vehicles[v_id]
        
        logger.info(f"Cleaned {len(vehicles_to_remove)} old tracks from {self.camera_id}")
        
        return len(vehicles_to_remove)
    
    def get_stats(self) -> Dict:
        """Get tracker statistics"""
        all_vehicles = self.get_all_vehicles()
        active = self.get_active_vehicles()
        exited = self.get_exited_vehicles()
        
        plates_recognized = sum(1 for v in all_vehicles if v.license_plate)
        
        return {
            'camera_id': self.camera_id,
            'frames_processed': self.frame_count,
            'total_vehicles_tracked': len(all_vehicles),
            'active_vehicles': len(active),
            'exited_vehicles': len(exited),
            'plates_recognized': plates_recognized,
            'next_vehicle_id': self.next_vehicle_id
        }
