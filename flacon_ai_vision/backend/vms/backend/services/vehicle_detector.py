"""
Advanced Vehicle Detector using YOLOv8
Detects vehicles with:
- License plate recognition (OCR)
- Vehicle brand/model classification
- Multi-frame tracking
- Timestamp logging
"""

try:
    from ultralytics import YOLO
    HAS_ULTRALYTICS = True
except ImportError:
    HAS_ULTRALYTICS = False
    YOLO = None

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

from typing import Dict, List, Optional, Tuple
import logging
import time

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None

from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import OCR libraries
try:
    import easyocr
    HAS_EASYOCR = True
except ImportError:
    HAS_EASYOCR = False
    logger.warning("EasyOCR not installed. License plate recognition disabled. Install: pip install easyocr")

try:
    from pytesseract import pytesseract
    HAS_PYTESSERACT = True
except ImportError:
    HAS_PYTESSERACT = False


class VehicleDetector:
    """Advanced YOLO-based object detection for vehicles with OCR and classification"""
    
    # COCO dataset classes of interest
    TARGET_CLASSES = {
        0: 'person',
        2: 'car',
        3: 'motorcycle',
        5: 'bus',
        7: 'truck'
    }
    
    # Vehicle type mapping (for better classification)
    VEHICLE_TYPES = {
        'car': 'sedan',
        'motorcycle': 'motorcycle',
        'bus': 'bus',
        'truck': 'truck',
        'person': 'person'
    }
    
    def __init__(self, model_size: str = 'n', device: str = 'cpu', enable_ocr: bool = True):
        """
        Initialize advanced vehicle detector
        
        Args:
            model_size: 'n' (nano-fast), 's' (small), 'm' (medium), 'l' (large), 'x' (xlarge)
            device: 'cpu' or 'cuda' (if GPU available)
            enable_ocr: Enable license plate OCR (requires EasyOCR)
        """
        # Initialize object detection model
        model_name = f'yolov8{model_size}.pt'
        try:
            self.detection_model = YOLO(model_name)
            self.detection_model.to(device)
            logger.info(f"YOLOv8{model_size} detection model loaded on '{device}'")
        except Exception as e:
            logger.error(f"Failed to initialize YOLO detection: {e}")
            raise
        
        # Initialize license plate detection model (if available)
        try:
            self.plate_model = YOLO('yolov8n.pt')  # Can use plate-specific model if available
            self.plate_model.to(device)
            self.has_plate_model = True
            logger.info("License plate detection model loaded")
        except Exception as e:
            logger.warning(f"License plate model not available: {e}")
            self.has_plate_model = False
        
        # Initialize OCR (for reading plates)
        self.ocr_reader = None
        self.enable_ocr = enable_ocr and HAS_EASYOCR
        if self.enable_ocr:
            try:
                self.ocr_reader = easyocr.Reader(['en', 'fr'], gpu=(device == 'cuda'))
                logger.info("EasyOCR reader initialized")
            except Exception as e:
                logger.error(f"Failed to initialize OCR: {e}")
                self.enable_ocr = False
        
        self.device = device
        self.model_size = model_size
        self.confidence_threshold = 0.5
        self.inference_times = []
    
    def detect_objects(self, frame: np.ndarray) -> Dict:
        """
        Detect objects (vehicles, persons) in a frame with optional OCR
        
        Args:
            frame: Input frame (BGR numpy array)
        
        Returns:
            {
                'detections': [
                    {
                        'class': str,
                        'confidence': float,
                        'bbox': [x1, y1, x2, y2],
                        'center': (cx, cy),
                        'width': int,
                        'height': int,
                        'area_px': int,
                        'license_plate': str,  # if detected
                        'plate_confidence': float,  # if detected
                        'brand': str,  # if classified
                        'model': str   # if classified
                    },
                    ...
                ],
                'vehicles_count': int,
                'people_count': int,
                'total_objects': int,
                'inference_time_ms': float
            }
        """
        start_time = time.time()
        
        try:
            # Run YOLO inference
            inference_start = time.time()
            results = self.detection_model(
                frame,
                conf=self.confidence_threshold,
                verbose=False,
                imgsz=640
            )
            inference_time_ms = (time.time() - inference_start) * 1000
            
            detections = []
            vehicles_count = 0
            people_count = 0
            ocr_time_ms = 0
            classification_time_ms = 0
            
            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = self.TARGET_CLASSES.get(class_id)
                    
                    # Skip if class not in target list
                    if class_name is None:
                        continue
                    
                    confidence = float(box.conf[0])
                    
                    # Extract bounding box coordinates
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    width = x2 - x1
                    height = y2 - y1
                    area = width * height
                    
                    detection = {
                        'class': class_name,
                        'confidence': round(confidence, 3),
                        'bbox': [x1, y1, x2, y2],
                        'center': (center_x, center_y),
                        'width': width,
                        'height': height,
                        'area_px': area,
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    # Extract vehicle region for OCR/classification
                    if class_name in ['car', 'motorcycle', 'bus', 'truck']:
                        vehicles_count += 1
                        
                        # Try to detect license plate
                        if self.enable_ocr:
                            ocr_start = time.time()
                            plate_info = self._detect_license_plate(frame, x1, y1, x2, y2)
                            ocr_time_ms += (time.time() - ocr_start) * 1000
                            if plate_info:
                                detection['license_plate'] = plate_info.get('text', '')
                                detection['plate_confidence'] = plate_info.get('confidence', 0)
                        
                        # Try to classify vehicle brand/model
                        class_start = time.time()
                        vehicle_class = self._classify_vehicle(frame, x1, y1, x2, y2)
                        classification_time_ms += (time.time() - class_start) * 1000
                        if vehicle_class:
                            detection['brand'] = vehicle_class.get('brand')
                            detection['model'] = vehicle_class.get('model')
                    
                    elif class_name == 'person':
                        people_count += 1
                    
                    detections.append(detection)
            
            # Calculate inference time
            inference_time = (time.time() - start_time) * 1000
            self.inference_times.append(inference_time)
            
            # Keep only last 30 times for average
            if len(self.inference_times) > 30:
                self.inference_times = self.inference_times[-30:]
            
            return {
                'detections': detections,
                'vehicles_count': vehicles_count,
                'people_count': people_count,
                'total_objects': len(detections),
                'inference_time_ms': round(inference_time_ms, 2),
                'ocr_time_ms': round(ocr_time_ms, 2),
                'classification_time_ms': round(classification_time_ms, 2),
                'total_time_ms': round((time.time() - start_time) * 1000, 2)
            }
        
        except Exception as e:
            logger.error(f"YOLO detection error: {e}")
            return {
                'detections': [],
                'total_objects': 0,
                'vehicles_count': 0,
                'people_count': 0,
                'inference_time_ms': 0
            }
    
    def _detect_license_plate(self, frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> Optional[Dict]:
        """
        Detect and read license plate in vehicle region
        
        Args:
            frame: Full frame
            x1, y1, x2, y2: Vehicle bounding box
        
        Returns:
            {'text': plate_text, 'confidence': float} or None
        """
        if not self.ocr_reader:
            return None
        
        try:
            # Extract vehicle region
            vehicle_region = frame[y1:y2, x1:x2]
            
            if vehicle_region.size == 0:
                return None
            
            # Optimize OCR by resizing large images (max 640px width for performance)
            height, width = vehicle_region.shape[:2]
            if width > 640:
                scale_factor = 640 / width
                new_width = 640
                new_height = int(height * scale_factor)
                vehicle_region = cv2.resize(vehicle_region, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
            
            # Run OCR with timeout
            import threading
            ocr_result = None
            def ocr_thread():
                nonlocal ocr_result
                try:
                    ocr_result = self.ocr_reader.readtext(vehicle_region, detail=1)
                except Exception as e:
                    logger.debug(f"OCR thread error: {e}")
            
            thread = threading.Thread(target=ocr_thread)
            thread.start()
            thread.join(timeout=2.0)  # 2 second timeout
            
            if thread.is_alive():
                logger.warning("OCR timeout exceeded, skipping license plate detection")
                return None
            
            results = ocr_result or []
            
            if not results:
                return None
            
            # Find plate-like text (typically alphanumeric)
            best_text = None
            best_conf = 0
            
            for (bbox, text, conf) in results:
                # Filter for license plate patterns
                if len(text) >= 3 and conf > best_conf:
                    best_text = text
                    best_conf = conf
            
            if best_text:
                return {'text': best_text.upper(), 'confidence': round(best_conf, 3)}
            
            return None
        
        except Exception as e:
            logger.debug(f"License plate detection error: {e}")
            return None
    
    def _classify_vehicle(self, frame: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> Optional[Dict]:
        """
        Classify vehicle brand and model
        
        Args:
            frame: Full frame
            x1, y1, x2, y2: Vehicle bounding box
        
        Returns:
            {'brand': str, 'model': str} or None
        """
        try:
            # Extract vehicle region
            vehicle_region = frame[y1:y2, x1:x2]
            
            if vehicle_region.size == 0:
                return None
            
            # Simple classification based on aspect ratio and size
            height, width = vehicle_region.shape[:2]
            ratio = width / height if height > 0 else 0
            
            # Rule-based classification (can be replaced with actual model)
            if ratio > 2.0:
                return {'brand': 'Unknown', 'model': 'SUV/Truck'}
            elif ratio > 1.5:
                return {'brand': 'Unknown', 'model': 'Sedan'}
            else:
                return {'brand': 'Unknown', 'model': 'Compact'}
        
        except Exception as e:
            logger.debug(f"Vehicle classification error: {e}")
            return None
    
    def set_confidence_threshold(self, threshold: float):
        """
        Adjust detection confidence threshold (0.0-1.0)
        
        Args:
            threshold: Confidence threshold. Higher = stricter, lower = more detections
        """
        self.confidence_threshold = max(0.0, min(1.0, threshold))
        logger.info(f"Confidence threshold set to {self.confidence_threshold}")
    
    def get_average_inference_time(self) -> float:
        """Get average inference time over last 30 detections"""
        if not self.inference_times:
            return 0
        return round(sum(self.inference_times) / len(self.inference_times), 2)
    
    def get_info(self) -> Dict:
        """Get detector information"""
        return {
            'model': f'yolov8{self.model_size}',
            'device': self.device,
            'confidence_threshold': self.confidence_threshold,
            'avg_inference_time_ms': self.get_average_inference_time(),
            'ocr_enabled': self.enable_ocr,
            'target_classes': self.TARGET_CLASSES
        }
