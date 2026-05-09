"""
Vehicle Detection Configuration
Settings for YOLO, OCR, and tracking
"""

# YOLO Settings
YOLO_MODEL_SIZE = 'n'  # 'n' (nano), 's' (small), 'm' (medium), 'l' (large)
YOLO_CONFIDENCE_THRESHOLD = 0.5
YOLO_DEVICE = 'cpu'  # 'cpu' or 'cuda'

# OCR Settings
OCR_LANGUAGES = ['en', 'fr']  # English and French
OCR_CONFIDENCE_THRESHOLD = 0.4  # Min confidence for plate recognition
OCR_ENABLED = True

# Tracking Settings
TRACKER_MAX_DISTANCE = 100.0  # pixels
TRACKER_MAX_AGE_FRAMES = 30  # frames
TRACKER_MIN_DETECTIONS = 3  # min detections to confirm vehicle

# Vehicle Classification
VEHICLE_CLASSES = {
    0: 'person',
    2: 'car',
    3: 'motorcycle',
    5: 'bus',
    7: 'truck'
}

# Alerts
ALERT_ON_VEHICLE_ENTRY = True
ALERT_ON_VEHICLE_EXIT = True
ALERT_ON_PLATE_RECOGNIZED = True
ALERT_CONFIDENCE_THRESHOLD = 0.7  # Minimum confidence for alert

# Database
LOG_VEHICLE_DETECTIONS = True
LOG_PLATE_RECOGNITION = True
LOG_VEHICLES_TO_EVENT_TABLE = True
CLEANUP_OLD_TRACKS_AFTER_HOURS = 24

# Performance
FRAME_PROCESS_INTERVAL = 1  # Process every Nth frame (1 = all frames)
MAX_CONCURRENT_CAMERAS = 4
BATCH_DETECTIONS = False  # Batch multiple frames

# Database Models
VEHICLE_DB_FIELDS = [
    'camera_id',
    'license_plate',
    'vehicle_type',
    'vehicle_class',
    'brand',
    'model',
    'confidence',
    'entry_timestamp',
    'exit_timestamp',
    'duration_seconds',
    'entry_location',
    'exit_location'
]
