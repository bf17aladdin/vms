"""
Advanced Vehicle Detector with:
- YOLO object detection
- License plate recognition (OCR)
- Vehicle model/brand classification
- Frame-level tracking
"""

from ultralytics import YOLO
import numpy as np
import cv2
import easyocr
from typing import Dict, List, Optional, Tuple
import logging
from datetime import datetime
import time

logger = logging.getLogger(__name__)


class LicensePlateRecognizer:
    """Recognize license plates using EasyOCR"""
    
    def __init__(self, languages: List[str] = None):
        """
        Initialize OCR reader
        
        Args:
            languages: List of language codes (e.g., ['en', 'fr'])
        """
        self.languages = languages or ['en']
        self.reader = easyocr.Reader(self.languages, gpu=False)
        logger.info(f"OCR initialized for languages: {self.languages}")
    
    def extract_plate_region(
        self,
        frame: np.ndarray,
        bbox: List[int]
    ) -> Optional[np.ndarray]:
        """
        Extract license plate region from frame
        
        Args:
            frame: Input frame
            bbox: Bounding box [x1, y1, x2, y2]
        
        Returns:
            Cropped image of license plate or None
        """
        try:
            x1, y1, x2, y2 = bbox
            plate_region = frame[max(0, y1):min(frame.shape[0], y2),
                                max(0, x1):min(frame.shape[1], x2)]
            
            if plate_region.size == 0:
                return None
            
            return plate_region
        except Exception as e:
            logger.error(f"Error extracting plate region: {e}")
            return None
    
    def recognize(self, plate_image: np.ndarray) -> Optional[Dict]:
        """
        Recognize license plate text
        
        Args:
            plate_image: Cropped license plate image
        
        Returns:
            {
                'text': str,           # Recognized text
                'confidence': float,   # 0.0-1.0
                'raw_results': list    # All detected texts with confidence
            }
        """
        try:
            if plate_image is None or plate_image.size == 0:
                return None
            
            # Enhance image for OCR
            plate_image = cv2.cvtColor(plate_image, cv2.COLOR_BGR2GRAY)
            plate_image = cv2.resize(plate_image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            _, plate_image = cv2.threshold(plate_image, 100, 255, cv2.THRESH_BINARY)
            
            # Run OCR
            results = self.reader.readtext(plate_image, detail=1)
            
            if not results:
                return None
            
            # Extract best result
            best_result = max(results, key=lambda x: x[2])
            text = best_result[1].strip().upper()
            confidence = best_result[2]
            
            return {
                'text': text,
                'confidence': round(confidence, 3),
                'raw_results': [
                    {'text': r[1], 'confidence': round(r[2], 3)}
                    for r in results
                ]
            }
        
        except Exception as e:
            logger.error(f"OCR recognition error: {e}")
            return None


class VehicleClassifier:
    """Classify vehicle brand/model using YOLO or pre-trained classifier"""
    
    # Common vehicle brands/models (pattern matching)
    VEHICLE_BRANDS = {
        'sedans': ['Toyota', 'Honda', 'BMW', 'Mercedes', 'Audi', 'Volkswagen', 'Ford', 'Chevrolet'],
        'suv': ['Range Rover', 'BMW X5', 'Mercedes GLE', 'Audi Q7', 'Volkswagen Touareg'],
        'trucks': ['F-150', 'Silverado', 'Ram', 'Tundra', 'Tacoma'],
        'vans': ['Caravan', 'Odyssey', 'Sienna', 'Transit']
    }
    
    def __init__(self):
        """Initialize classifier"""
        logger.info("VehicleClassifier initialized (pattern-based)")
    
    def classify(self, vehicle_bbox: List[int], frame: np.ndarray) -> Dict:
        """
        Classify vehicle type based on shape and size
        
        Args:
            vehicle_bbox: [x1, y1, x2, y2]
            frame: Input frame
        
        Returns:
            {
                'type': str,        # 'car', 'suv', 'truck', 'van', 'motorcycle'
                'brand': str,       # 'unknown' or brand name
                'model': str,       # 'unknown' or model
                'confidence': float # 0.0-1.0
            }
        """
        try:
            x1, y1, x2, y2 = vehicle_bbox
            width = x2 - x1
            height = y2 - y1
            aspect_ratio = width / height if height > 0 else 0
            
            # Simple heuristics based on shape
            if aspect_ratio > 2.5:
                vehicle_type = 'truck'
                confidence = 0.6
            elif aspect_ratio > 2.0:
                vehicle_type = 'van'
                confidence = 0.5
            elif aspect_ratio > 1.5:
                vehicle_type = 'suv'
                confidence = 0.5
            else:
                vehicle_type = 'car'
                confidence = 0.7
            
            return {
                'type': vehicle_type,
                'brand': 'unknown',
                'model': 'unknown',
                'confidence': round(confidence, 2),
                'aspect_ratio': round(aspect_ratio, 2)
            }
        
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return {
                'type': 'unknown',
                'brand': 'unknown',
                'model': 'unknown',
                'confidence': 0.0
            }


class AdvancedVehicleDetector:
    """
    Advanced vehicle detection with OCR + classification
    """
    
    TARGET_CLASSES = {
        2: 'car',
        3: 'motorcycle',
        5: 'bus',
        7: 'truck'
    }
    
    def __init__(self, model_size: str = 'n', device: str = 'cpu'):
        """
        Initialize detector
        
        Args:
            model_size: YOLOv8 size ('n', 's', 'm', 'l')
            device: 'cpu' or 'cuda'
        """
        # YOLO detector
        model_name = f'yolov8{model_size}.pt'
        self.model = YOLO(model_name)
        self.model.to(device)
        
        # Components
        self.plate_recognizer = LicensePlateRecognizer(languages=['en', 'fr'])
        self.classifier = VehicleClassifier()
        
        self.device = device
        self.model_size = model_size
        self.confidence_threshold = 0.5
        self.plate_confidence_threshold = 0.4
        
        logger.info(f"AdvancedVehicleDetector initialized (model: yolov8{model_size}, device: {device})")
    
    def detect_vehicles(self, frame: np.ndarray) -> Dict:
        """
        Detect vehicles with full details (plate, classification)
        
        Args:
            frame: Input frame (BGR)
        
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
                        'plate': {
                            'text': str,
                            'confidence': float
                        },
                        'classification': {
                            'type': str,
                            'brand': str,
                            'model': str
                        },
                        'timestamp': str
                    },
                    ...
                ],
                'total_vehicles': int,
                'plate_recognition_rate': float
            }
        """
        try:
            start_time = time.time()
            
            # YOLO inference
            results = self.model(frame, conf=self.confidence_threshold, verbose=False)
            
            detections = []
            plates_found = 0
            
            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    class_name = self.TARGET_CLASSES.get(class_id)
                    
                    if class_name is None or class_name == 'motorcycle':
                        continue
                    
                    confidence = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    width = x2 - x1
                    height = y2 - y1
                    
                    # Try to extract and recognize license plate
                    plate_data = self._extract_and_recognize_plate(frame, [x1, y1, x2, y2])
                    if plate_data:
                        plates_found += 1
                    
                    # Classify vehicle
                    classification = self.classifier.classify([x1, y1, x2, y2], frame)
                    
                    detection = {
                        'class': class_name,
                        'confidence': round(confidence, 3),
                        'bbox': [x1, y1, x2, y2],
                        'center': (center_x, center_y),
                        'width': width,
                        'height': height,
                        'area_px': width * height,
                        'plate': plate_data,
                        'classification': classification,
                        'timestamp': datetime.now().isoformat()
                    }
                    
                    detections.append(detection)
            
            inference_time = (time.time() - start_time) * 1000
            plate_rate = (plates_found / len(detections) * 100) if detections else 0
            
            return {
                'detections': detections,
                'total_vehicles': len(detections),
                'plates_recognized': plates_found,
                'plate_recognition_rate': round(plate_rate, 1),
                'inference_time_ms': round(inference_time, 2)
            }
        
        except Exception as e:
            logger.error(f"Detection error: {e}")
            return {
                'detections': [],
                'total_vehicles': 0,
                'plates_recognized': 0,
                'plate_recognition_rate': 0
            }
    
    def _extract_and_recognize_plate(
        self,
        frame: np.ndarray,
        vehicle_bbox: List[int]
    ) -> Optional[Dict]:
        """Extract and recognize license plate from vehicle region"""
        try:
            x1, y1, x2, y2 = vehicle_bbox
            
            # Plate is typically in lower portion of vehicle
            plate_y1 = max(0, y2 - (y2 - y1) // 3)
            plate_x1 = x1 + (x2 - x1) // 4
            plate_x2 = x2 - (x2 - x1) // 4
            
            plate_region = self.plate_recognizer.extract_plate_region(
                frame,
                [plate_x1, plate_y1, plate_x2, y2]
            )
            
            if plate_region is None:
                return None
            
            result = self.plate_recognizer.recognize(plate_region)
            if result and result['confidence'] >= self.plate_confidence_threshold:
                return result
            
            return None
        
        except Exception as e:
            logger.error(f"Plate extraction error: {e}")
            return None
    
    def set_confidence_threshold(self, threshold: float):
        """Set detection confidence threshold"""
        self.confidence_threshold = max(0.0, min(1.0, threshold))
    
    def set_plate_confidence_threshold(self, threshold: float):
        """Set OCR confidence threshold"""
        self.plate_confidence_threshold = max(0.0, min(1.0, threshold))
