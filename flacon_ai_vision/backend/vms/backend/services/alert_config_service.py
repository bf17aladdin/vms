# vms/backend/services/alert_config_service.py - Alert Configuration Service

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class AlertThreshold:
    """Alert threshold configuration"""
    id: str
    name: str
    description: str
    event_type: str  # 'face', 'vehicle', 'zone', 'security', 'performance'
    camera_id: Optional[int]  # None for global, specific camera ID for camera-specific
    enabled: bool = True

    # Threshold values
    min_confidence: float = 0.5
    max_unknown_rate: float = 0.1
    max_false_positive_rate: float = 0.05
    max_latency_ms: float = 500
    min_fps: float = 15
    max_queue_size: int = 100

    # Alert settings
    severity: str = 'medium'  # 'low', 'medium', 'high', 'critical'
    cooldown_minutes: int = 5  # Minimum time between alerts of same type
    notification_channels: List[str] = None  # ['email', 'sms', 'websocket', 'ui']

    # Metadata
    created_at: str = ""
    updated_at: str = ""
    created_by: str = ""

    def __post_init__(self):
        if self.notification_channels is None:
            self.notification_channels = ['ui', 'websocket']
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()

@dataclass
class AlertConfig:
    """Complete alert configuration"""
    thresholds: List[AlertThreshold]
    global_settings: Dict[str, Any]

class AlertConfigService:
    """
    Service for managing alert thresholds and configurations
    """

    def __init__(self, config_file: str = "data/alert_config.json"):
        self.config_file = Path(config_file)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()
        self._last_modified = datetime.utcnow()

    def _load_config(self) -> AlertConfig:
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    thresholds = [AlertThreshold(**t) for t in data.get('thresholds', [])]
                    return AlertConfig(
                        thresholds=thresholds,
                        global_settings=data.get('global_settings', {})
                    )
            except Exception as e:
                logger.error(f"Error loading alert config: {e}")

        # Default configuration
        return AlertConfig(
            thresholds=self._get_default_thresholds(),
            global_settings={
                'email_enabled': False,
                'sms_enabled': False,
                'max_alerts_per_hour': 100,
                'auto_acknowledge_after_hours': 24
            }
        )

    def _get_default_thresholds(self) -> List[AlertThreshold]:
        """Get default alert thresholds"""
        return [
            AlertThreshold(
                id='face_low_confidence',
                name='Face Detection - Low Confidence',
                description='Alert when face detection confidence is below threshold',
                event_type='face',
                min_confidence=0.7,
                severity='low'
            ),
            AlertThreshold(
                id='face_high_unknown_rate',
                name='Face Detection - High Unknown Rate',
                description='Alert when unknown face rate exceeds threshold',
                event_type='face',
                max_unknown_rate=0.15,
                severity='medium'
            ),
            AlertThreshold(
                id='vehicle_low_confidence',
                name='Vehicle Detection - Low Confidence',
                description='Alert when vehicle detection confidence is below threshold',
                event_type='vehicle',
                min_confidence=0.6,
                severity='low'
            ),
            AlertThreshold(
                id='performance_high_latency',
                name='Performance - High Latency',
                description='Alert when average detection latency is too high',
                event_type='performance',
                max_latency_ms=300,
                severity='medium'
            ),
            AlertThreshold(
                id='performance_low_fps',
                name='Performance - Low FPS',
                description='Alert when average FPS drops below threshold',
                event_type='performance',
                min_fps=20,
                severity='high'
            ),
            AlertThreshold(
                id='system_queue_full',
                name='System - Processing Queue Full',
                description='Alert when processing queue exceeds safe limit',
                event_type='system',
                max_queue_size=50,
                severity='high'
            )
        ]

    def _save_config(self):
        """Save configuration to file"""
        try:
            data = {
                'thresholds': [asdict(t) for t in self.config.thresholds],
                'global_settings': self.config.global_settings
            }
            with open(self.config_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            self._last_modified = datetime.utcnow()
        except Exception as e:
            logger.error(f"Error saving alert config: {e}")

    def get_all_thresholds(self) -> List[AlertThreshold]:
        """Get all alert thresholds"""
        return self.config.thresholds.copy()

    def get_threshold(self, threshold_id: str) -> Optional[AlertThreshold]:
        """Get a specific threshold by ID"""
        for threshold in self.config.thresholds:
            if threshold.id == threshold_id:
                return threshold
        return None

    def get_thresholds_by_type(self, event_type: str) -> List[AlertThreshold]:
        """Get thresholds for a specific event type"""
        return [t for t in self.config.thresholds if t.event_type == event_type]

    def get_thresholds_by_camera(self, camera_id: int) -> List[AlertThreshold]:
        """Get camera-specific thresholds"""
        return [t for t in self.config.thresholds if t.camera_id == camera_id]

    def create_threshold(self, threshold: AlertThreshold) -> AlertThreshold:
        """Create a new threshold"""
        # Check if ID already exists
        if self.get_threshold(threshold.id):
            raise ValueError(f"Threshold with ID '{threshold.id}' already exists")

        self.config.thresholds.append(threshold)
        self._save_config()
        logger.info(f"Created alert threshold: {threshold.id}")
        return threshold

    def update_threshold(self, threshold_id: str, updates: Dict[str, Any]) -> Optional[AlertThreshold]:
        """Update an existing threshold"""
        for i, threshold in enumerate(self.config.thresholds):
            if threshold.id == threshold_id:
                # Update fields
                for key, value in updates.items():
                    if hasattr(threshold, key):
                        setattr(threshold, key, value)
                threshold.updated_at = datetime.utcnow().isoformat()

                self._save_config()
                logger.info(f"Updated alert threshold: {threshold_id}")
                return threshold
        return None

    def delete_threshold(self, threshold_id: str) -> bool:
        """Delete a threshold"""
        for i, threshold in enumerate(self.config.thresholds):
            if threshold.id == threshold_id:
                self.config.thresholds.pop(i)
                self._save_config()
                logger.info(f"Deleted alert threshold: {threshold_id}")
                return True
        return False

    def get_global_settings(self) -> Dict[str, Any]:
        """Get global alert settings"""
        return self.config.global_settings.copy()

    def update_global_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Update global alert settings"""
        self.config.global_settings.update(settings)
        self._save_config()
        logger.info("Updated global alert settings")
        return self.config.global_settings.copy()

    def validate_threshold(self, threshold: AlertThreshold) -> List[str]:
        """Validate a threshold configuration"""
        errors = []

        if not threshold.id or not threshold.id.strip():
            errors.append("ID is required")

        if not threshold.name or not threshold.name.strip():
            errors.append("Name is required")

        if threshold.event_type not in ['face', 'vehicle', 'zone', 'security', 'performance', 'system']:
            errors.append("Invalid event type")

        if not (0 <= threshold.min_confidence <= 1):
            errors.append("Confidence must be between 0 and 1")

        if threshold.max_latency_ms < 0:
            errors.append("Latency must be positive")

        if threshold.min_fps < 0:
            errors.append("FPS must be positive")

        if threshold.severity not in ['low', 'medium', 'high', 'critical']:
            errors.append("Invalid severity level")

        return errors

# Global service instance
_alert_config_service: Optional[AlertConfigService] = None

def get_alert_config_service() -> AlertConfigService:
    """Get the global alert configuration service instance"""
    global _alert_config_service
    if _alert_config_service is None:
        _alert_config_service = AlertConfigService()
    return _alert_config_service