# vms/backend/services/frame_processor.py - Traitement des frames avec détections

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import os

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None

import io
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

# Imports des détecteurs
try:
    from facial_recognition.face_recognizer import FaceRecognizer
    _HAS_FACE_RECOG = True
except Exception as e:
    logger.warning(f"FaceRecognizer not available: {e}")
    FaceRecognizer = None
    _HAS_FACE_RECOG = False

try:
    from vehicle_detection.vehicle_detector import VehicleDetector
    _HAS_VEHICLE_DETECTOR = True
except Exception as e:
    logger.warning(f"VehicleDetector not available: {e}")
    VehicleDetector = None
    _HAS_VEHICLE_DETECTOR = False

from .alert_service import get_alert_service, AlertSeverity, AlertType
from .rule_engine_service import get_rule_engine_service
from sqlalchemy.orm import Session
import time

# Services DB
try:
    from vms.backend.services.personnel_service import PersonnelService
    from vms.backend.services.vehicle_entry_service import VehicleEntryService
    from vms.backend.schemas import VehicleEntryCreate
    from vms.backend.models import PersonnelEvent
    _HAS_DB_SERVICES = True
except Exception as e:
    logger.warning(f"DB services not available in FrameProcessor: {e}")
    PersonnelService = None
    VehicleEntryService = None
    VehicleEntryCreate = None
    PersonnelEvent = None
    _HAS_DB_SERVICES = False

# AI Inference Manager
try:
    from vms.backend.services.inference_manager import get_inference_manager
    _HAS_INFERENCE_MANAGER = True
except Exception as e:
    logger.warning(f"InferenceManager not available: {e}")
    get_inference_manager = None
    _HAS_INFERENCE_MANAGER = False

try:
    from vms.backend.core.database import SessionLocal
except Exception as e:
    logger.warning(f"SessionLocal not available: {e}")
    SessionLocal = None

try:
    from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline

    _HAS_FACE_PIPELINE = True
except Exception as e:
    logger.warning(f"FaceRecognitionPipeline not available: {e}")
    FaceRecognitionPipeline = None
    _HAS_FACE_PIPELINE = False

try:
    from vms.backend.services.vehicle_ai.vehicle_pipeline import VehicleRecognitionPipeline

    _HAS_VEHICLE_PIPELINE = True
except Exception as e:
    logger.warning(f"VehicleRecognitionPipeline not available: {e}")
    VehicleRecognitionPipeline = None
    _HAS_VEHICLE_PIPELINE = False


class FrameProcessor:
    """Processus de traitement des frames avec détections"""
    
    def __init__(self, camera_id: int, camera_name: str):
        """
        Initialiser le processeur de frames
        
        Args:
            camera_id: ID de la caméra
            camera_name: Nom de la caméra
        """
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.tenant_id = self._resolve_tenant_id()
        
        # Initialiser les détecteurs
        self.face_recognizer = None
        self.vehicle_detector = None
        self._init_detectors()
        
        # Service d'alertes
        self.alert_service = get_alert_service()
        
        # Répertoires
        self.thumbnails_dir = f"data/thumbnails/camera_{camera_id}"
        self.detections_dir = f"data/detections/camera_{camera_id}"
        os.makedirs(self.thumbnails_dir, exist_ok=True)
        os.makedirs(self.detections_dir, exist_ok=True)
        
        # Statistiques
        self.frame_count = 0
        self.last_face_detection = None
        self.last_vehicle_detection = None
        self.detected_persons = {}  # {name: count}
        self.detected_vehicles = {}  # {type: count}
        
        # AI Inference Manager (lazy init)
        self.inference_manager = None
        self.face_pipeline_stride = max(1, int(os.getenv("FACE_REALTIME_STRIDE", "5")))
        self.vehicle_pipeline_stride = max(1, int(os.getenv("VEHICLE_REALTIME_STRIDE", "1")))
    

    def _resolve_tenant_id(self) -> Optional[int]:
        try:
            if SessionLocal is None:
                return None
            from vms.backend.models import Camera

            db = SessionLocal()
            try:
                camera = db.query(Camera).filter(Camera.id == int(self.camera_id)).first()
                return int(camera.tenant_id) if camera and camera.tenant_id is not None else None
            finally:
                db.close()
        except Exception:
            return None

    def _get_inference_manager(self):
        """Lazy initialization of InferenceManager singleton"""
        if not _HAS_INFERENCE_MANAGER or get_inference_manager is None:
            return None
        if self.inference_manager is None:
            try:
                self.inference_manager = get_inference_manager()
            except Exception as e:
                logger.error(f"Failed to get InferenceManager: {e}")
        return self.inference_manager
    
    def _init_detectors(self):
        """Initialiser les détecteurs disponibles"""
        if _HAS_FACE_RECOG and FaceRecognizer:
            try:
                self.face_recognizer = FaceRecognizer()
                logger.info(f"FaceRecognizer initialized for camera {self.camera_id}")
            except Exception as e:
                logger.warning(f"Failed to initialize FaceRecognizer: {e}")
        
        if _HAS_VEHICLE_DETECTOR and VehicleDetector:
            try:
                self.vehicle_detector = VehicleDetector(model_name="yolov8m")
                logger.info(f"VehicleDetector initialized for camera {self.camera_id}")
            except Exception as e:
                logger.warning(f"Failed to initialize VehicleDetector: {e}")
    
    async def process_frame_with_ai(self, frame: np.ndarray) -> Dict:
        """
        Traiter un frame avec les détecteurs IA (motion + objects)
        Utilise le InferenceManager pour une exécution asynchrone et optimisée
        
        Args:
            frame: Frame numpy BGR (OpenCV format)
        
        Returns:
            Dict avec résultats motion detection et object detection
        """
        start_time = time.time()
        results = {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "frame_count": self.frame_count,
            "timestamp": datetime.utcnow().isoformat(),
            "motion": {
                "detected": False,
                "confidence": 0.0,
                "regions": [],
                "coverage": 0.0
            },
            "objects": [],
            "error": None,
            "latency_ms": 0.0
        }
        
        try:
            inf_mgr = self._get_inference_manager()
            if inf_mgr is None:
                logger.warning(f"InferenceManager not available for camera {self.camera_id}")
                results["error"] = "InferenceManager not available"
                return results
            
            # Motion detection (always run)
            try:
                motion_result = await inf_mgr.detect_motion_async(frame, self.camera_id)
                results["motion"] = {
                    "detected": motion_result.get("motion_detected", False),
                    "confidence": motion_result.get("confidence", 0.0),
                    "regions": motion_result.get("regions", []),
                    "coverage": motion_result.get("coverage", 0.0)
                }
            except Exception as e:
                logger.error(f"Motion detection error for camera {self.camera_id}: {e}")
                results["motion"]["error"] = str(e)
            
            # Object detection (if motion detected OR every Nth frame)
            # This optimization reduces CPU load while maintaining detection quality
            should_detect_objects = (
                results["motion"]["detected"] or 
                (self.frame_count % 5 == 0)  # Process every 5th frame regardless
            )
            
            if should_detect_objects:
                try:
                    objects_result = await inf_mgr.detect_objects_async(frame, self.camera_id)
                    results["objects"] = objects_result.get("objects", [])
                    results["objects_latency_ms"] = objects_result.get("processing_time_ms", 0)
                except Exception as e:
                    logger.error(f"Object detection error for camera {self.camera_id}: {e}")
                    results["error"] = str(e)
            else:
                results["objects"] = []
                results["objects_latency_ms"] = 0
            
            results["latency_ms"] = (time.time() - start_time) * 1000
            
            return results
            
        except Exception as e:
            logger.error(f"Error in process_frame_with_ai: {e}")
            results["error"] = str(e)
            results["latency_ms"] = (time.time() - start_time) * 1000
            return results
    
    async def process_frame_async(self, frame: np.ndarray, db: Optional[Session] = None) -> Dict:
        """
        Version ASYNC complète de process_frame intégrant IA et détections classiques
        Combine motion detection, object detection, face recognition, et vehicle detection
        
        Args:
            frame: Frame numpy BGR (OpenCV format)
            db: SQLAlchemy session (optional)
        
        Returns:
            Dict avec résultats consolidés de toutes les détections
        """
        self.frame_count += 1
        start_time = time.time()
        
        results = {
            "frame_count": self.frame_count,
            "timestamp": datetime.utcnow().isoformat(),
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "faces": [],
            "vehicles": [],
            "motion": {"detected": False, "confidence": 0.0},
            "objects": [],  # YOLO objects from motion detection trigger
            "thumbnail_path": None,
            "alerts": [],
            "latency_ms": 0.0,
            "ai_latency_ms": 0.0
        }
        
        try:
            # Redimensionner si trop grand
            if frame.shape[0] > 1080:
                scale = 1080 / frame.shape[0]
                frame = cv2.resize(frame, None, fx=scale, fy=scale)
            
            # === AI Detections (async) ===
            ai_start = time.time()
            ai_results = await self.process_frame_with_ai(frame)
            results["motion"] = ai_results["motion"]
            results["objects"] = ai_results.get("objects", [])
            results["ai_latency_ms"] = (time.time() - ai_start) * 1000
            
            # === Face Detection (sync, but non-blocking in production) ===
            if self.face_recognizer or _HAS_FACE_PIPELINE:
                face_results = self._detect_faces(frame, db=db)
                results["faces"] = face_results["faces"]
                results["alerts"].extend(face_results["alerts"])
            
            # === Vehicle Detection (sync) ===
            if self.vehicle_detector:
                vehicle_results = self._detect_vehicles(frame, db=db)
                results["vehicles"] = vehicle_results["vehicles"]
                results["alerts"].extend(vehicle_results["alerts"])

            # === Rule Engine Evaluation ===
            try:
                zone_context = self._resolve_zone_context(db)
                rule_alerts = self._evaluate_rules_for_detections(
                    faces=results["faces"],
                    vehicles=results["vehicles"],
                    db=db,
                    zone_context=zone_context,
                )
                if rule_alerts:
                    results["alerts"].extend(rule_alerts)
            except Exception as e:
                logger.debug(f"Rule engine evaluation failed for camera {self.camera_id}: {e}")
            
            # === Thumbnail ===
            thumbnail_path = self._save_thumbnail(frame)
            results["thumbnail_path"] = thumbnail_path
            
            # === Event Generation from AI Detections ===
            await self._generate_events_from_ai(ai_results, db)
            
            results["latency_ms"] = (time.time() - start_time) * 1000
            
            # === Log Statistics ===
            if self.frame_count % 30 == 0:  # ~1s at 30fps
                logger.debug(
                    f"Camera {self.camera_id}: frames={self.frame_count}, "
                    f"faces={len(results['faces'])}, vehicles={len(results['vehicles'])}, "
                    f"motion={results['motion']['detected']}, objects={len(results['objects'])}, "
                    f"total_latency={results['latency_ms']:.1f}ms, ai_latency={results['ai_latency_ms']:.1f}ms"
                )
            
            return results
            
        except Exception as e:
            logger.error(f"Error in process_frame_async: {e}")
            results["error"] = str(e)
            results["latency_ms"] = (time.time() - start_time) * 1000
            return results
    
    async def _generate_events_from_ai(self, ai_results: Dict, db: Optional[Session] = None):
        """
        Générer des événements de base de données à partir des détections IA
        
        Args:
            ai_results: Résultats de process_frame_with_ai
            db: SQLAlchemy session
        """
        try:
            # Motion detection event
            if ai_results.get("motion", {}).get("detected", False):
                motion_confidence = ai_results.get("motion", {}).get("confidence", 0.0)
                if motion_confidence > 0.3:  # Threshold
                    logger.info(
                        f"Motion detected on camera {self.camera_id} "
                        f"(confidence={motion_confidence:.2%})"
                    )
                    # TODO: Log to event_service if needed
            
            # Object detection events (high-value detections)
            objects = ai_results.get("objects", [])
            for obj in objects:
                class_name = obj.get("class", "unknown")
                confidence = obj.get("confidence", 0.0)
                
                # Log only high-confidence detections
                if confidence > 0.65:  # Production threshold
                    logger.info(
                        f"Object detected on camera {self.camera_id}: "
                        f"{class_name} (confidence={confidence:.2%})"
                    )
                    # TODO: Link to VehicleEntryService if vehicle
                    if class_name in ["car", "truck", "bus", "motorcycle"]:
                        try:
                            if db is not None and _HAS_DB_SERVICES and VehicleEntryService:
                                # This is where vehicle tracking would be logged
                                pass
                        except Exception as e:
                            logger.warning(f"Failed to log vehicle event: {e}")
        
        except Exception as e:
            logger.error(f"Error generating events from AI: {e}")

    def _resolve_zone_context(self, db: Optional[Session]) -> Dict[str, Any]:
        """Resolve basic zone context for rule evaluation."""
        zone_id = None
        zone_name = None
        zone_restricted = False

        if db is None:
            return {
                "zone_id": zone_id,
                "zone_name": zone_name,
                "zone_restricted": zone_restricted,
            }

        try:
            from vms.backend.models import Camera, Zone

            camera = db.query(Camera).filter(Camera.id == int(self.camera_id)).first()
            if camera and camera.zone_id:
                zone_id = int(camera.zone_id)
                zone = db.query(Zone).filter(Zone.id == zone_id).first()
                if zone:
                    zone_name = zone.name
                    zone_restricted = bool(zone.is_blocked)
        except Exception as e:
            logger.debug(f"Unable to resolve zone context for camera {self.camera_id}: {e}")

        return {
            "zone_id": zone_id,
            "zone_name": zone_name,
            "zone_restricted": zone_restricted,
        }

    def _resolve_vehicle_known(self, detection: Dict[str, Any], db: Optional[Session]) -> Optional[bool]:
        """Determine if a vehicle is known based on registry lookup."""
        plate_text = (
            detection.get("plate_text")
            or detection.get("license_plate")
            or detection.get("plate")
            or ""
        )
        plate_text = str(plate_text or "").strip().upper()
        if not plate_text:
            return None

        if db is None:
            return None

        try:
            from vms.backend.models import VehicleRegistry

            match = (
                db.query(VehicleRegistry.id)
                .filter(VehicleRegistry.matricule == plate_text)
                .first()
            )
            return bool(match)
        except Exception as e:
            logger.debug(f"Unable to resolve registry match for {plate_text}: {e}")
            return None

    @staticmethod
    def _normalize_rule_severity(value: object) -> AlertSeverity:
        raw = str(value or "").strip().lower()
        mapping = {
            "low": AlertSeverity.LOW,
            "medium": AlertSeverity.MEDIUM,
            "high": AlertSeverity.HIGH,
            "critical": AlertSeverity.CRITICAL,
        }
        return mapping.get(raw, AlertSeverity.MEDIUM)

    def _emit_rule_alerts(self, rules: List[Dict[str, Any]], event: Dict[str, Any]) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        if not rules:
            return alerts

        for rule in rules:
            rule_type = str(rule.get("type") or rule.get("id") or "rule").strip()
            action = rule.get("action") or {}
            severity = self._normalize_rule_severity(action.get("severity"))
            message = str(action.get("message") or f"Rule triggered: {rule_type}")

            payload = {
                "rule_id": rule.get("id"),
                "rule_type": rule_type,
                "camera_id": self.camera_id,
                "timestamp": event.get("timestamp"),
                "severity": severity.value,
                "event": {
                    "type": event.get("type"),
                    "person_status": event.get("person_status"),
                    "vehicle_known": event.get("vehicle_known"),
                    "zone_id": event.get("zone_id"),
                    "zone_restricted": event.get("zone_restricted"),
                    "plate_text": event.get("plate_text"),
                },
            }

            alert = self.alert_service.create_alert(
                camera_id=self.camera_id,
                camera_name=self.camera_name,
                alert_type=AlertType.ALARM,
                message=message,
                severity=severity,
                data=payload,
                tenant_id=self.tenant_id,
            )
            alerts.append(alert.to_dict())

        return alerts

    def _evaluate_rules_for_detections(
        self,
        *,
        faces: List[Dict[str, Any]],
        vehicles: List[Dict[str, Any]],
        db: Optional[Session],
        zone_context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        try:
            engine = get_rule_engine_service()
        except Exception as e:
            logger.debug(f"Rule engine unavailable: {e}")
            return []

        rule_alerts: List[Dict[str, Any]] = []

        for face in faces:
            event = {
                "type": "person",
                "camera_id": self.camera_id,
                "tenant_id": self.tenant_id,
                "timestamp": face.get("timestamp"),
                "person_status": "known" if face.get("is_known") else "unknown",
                "is_known": bool(face.get("is_known")),
                "person_id": face.get("person_id"),
                "confidence": face.get("confidence"),
                **zone_context,
            }
            triggered = engine.evaluate_event(event)
            rule_alerts.extend(self._emit_rule_alerts(triggered, event))

        for vehicle in vehicles:
            vehicle_type = str(vehicle.get("type") or vehicle.get("class") or "").strip().lower()
            if vehicle_type == "person":
                continue

            plate_text = (
                vehicle.get("plate_text")
                or vehicle.get("license_plate")
                or vehicle.get("plate")
                or ""
            )
            vehicle_known = self._resolve_vehicle_known(vehicle, db)
            event = {
                "type": "vehicle",
                "camera_id": self.camera_id,
                "tenant_id": self.tenant_id,
                "timestamp": vehicle.get("timestamp"),
                "vehicle_type": vehicle_type,
                "plate_text": str(plate_text or "").strip().upper() or None,
                "plate_number": str(plate_text or "").strip().upper() or None,
                "plate_confidence": vehicle.get("plate_confidence"),
                "vehicle_known": vehicle_known,
                "confidence": vehicle.get("confidence"),
                **zone_context,
            }
            triggered = engine.evaluate_event(event)
            rule_alerts.extend(self._emit_rule_alerts(triggered, event))

        return rule_alerts
    
    def process_frame(self, frame: np.ndarray, db: Optional[Session] = None) -> Dict:
        """
        Traiter un frame avec toutes les détections
        
        Args:
            frame: Frame numpy BGR (OpenCV format)
            
        Returns:
            Dict avec résultats détections + statistiques
        """
        self.frame_count += 1
        results = {
            "frame_count": self.frame_count,
            "timestamp": datetime.utcnow().isoformat(),
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "faces": [],
            "vehicles": [],
            "motion": False,
            "thumbnail_path": None,
            "alerts": []
        }
        
        # Redimensionner si trop grand
        if frame.shape[0] > 1080:
            scale = 1080 / frame.shape[0]
            frame = cv2.resize(frame, None, fx=scale, fy=scale)
        
        # Détection faciale
        if self.face_recognizer or _HAS_FACE_PIPELINE:
            face_results = self._detect_faces(frame, db=db)
            results["faces"] = face_results["faces"]
            results["alerts"].extend(face_results["alerts"])
        
        # Détection de véhicules
        if self.vehicle_detector:
            vehicle_results = self._detect_vehicles(frame, db=db)
            results["vehicles"] = vehicle_results["vehicles"]
            results["alerts"].extend(vehicle_results["alerts"])

        # === Rule Engine Evaluation ===
        try:
            zone_context = self._resolve_zone_context(db)
            rule_alerts = self._evaluate_rules_for_detections(
                faces=results["faces"],
                vehicles=results["vehicles"],
                db=db,
                zone_context=zone_context,
            )
            if rule_alerts:
                results["alerts"].extend(rule_alerts)
        except Exception as e:
            logger.debug(f"Rule engine evaluation failed for camera {self.camera_id}: {e}")
        
        # Créer une miniature
        thumbnail_path = self._save_thumbnail(frame)
        results["thumbnail_path"] = thumbnail_path
        
        # Log statistiques
        if self.frame_count % 30 == 0:  # Tous les ~1s à 30fps
            logger.debug(
                f"Camera {self.camera_id}: frames={self.frame_count}, "
                f"faces={len(results['faces'])}, vehicles={len(results['vehicles'])}"
            )
        
        return results
    
    def _detect_faces(self, frame: np.ndarray, db: Optional[Session] = None) -> Dict:
        """
        Détection faciale avec reconnaissance.

        Priorité:
        1) Nouveau pipeline Detect->Align->Embed->Match (InsightFace/ArcFace)
        2) Fallback legacy FaceRecognizer si indisponible
        """
        results = {"faces": [], "alerts": []}

        # Throttle face inference for real-time performance.
        if self.frame_count % self.face_pipeline_stride != 0:
            return results

        if _HAS_FACE_PIPELINE and FaceRecognitionPipeline is not None:
            local_db = None
            db_session = db
            try:
                if db_session is None and SessionLocal is not None:
                    local_db = SessionLocal()
                    db_session = local_db

                if db_session is not None:
                    pipeline = FaceRecognitionPipeline(db_session)
                    max_faces_runtime = max(0, int(os.getenv("FACE_RUNTIME_MAX_FACES", "10")))
                    payload = pipeline.recognize_many_from_frame(
                        frame_bgr=frame,
                        camera_id=self.camera_id,
                        zone_id=None,
                        persist=True,
                        top_k=3,
                        max_faces=max_faces_runtime,
                    )

                    faces_payload = payload.get("faces") or []
                    if faces_payload:
                        now_iso = datetime.utcnow().isoformat()
                        for face_payload in faces_payload:
                            status = face_payload.get("status")
                            if status not in {"matched", "unknown"}:
                                continue

                            person_name = (
                                face_payload.get("personnel_name")
                                or face_payload.get("label")
                                or "Unknown"
                            )
                            face_info = {
                                "bbox": face_payload.get("bbox") or {},
                                "name": person_name,
                                "person_id": face_payload.get("personnel_id"),
                                "track_id": face_payload.get("track_id"),
                                "is_known": status == "matched",
                                "confidence": float(face_payload.get("confidence", 0.0)),
                                "timestamp": now_iso,
                                "match_quality": face_payload.get("match_quality"),
                                "decision": face_payload.get("decision"),
                                "reason_code": face_payload.get("reason_code"),
                                "event_id": face_payload.get("event_id"),
                                "unknown_detection_id": face_payload.get("unknown_detection_id"),
                            }
                            results["faces"].append(face_info)

                            decision = str(face_payload.get("decision") or "").lower()
                            if status == "unknown":
                                self.detected_persons["Unknown"] = self.detected_persons.get("Unknown", 0) + 1
                            else:
                                self.detected_persons[person_name] = self.detected_persons.get(person_name, 0) + 1

                            if decision in {"deny", "review"}:
                                alert = {
                                    "type": f"face_{decision}",
                                    "camera_id": self.camera_id,
                                    "name": person_name,
                                    "track_id": face_info.get("track_id"),
                                    "confidence": face_info["confidence"],
                                    "reason_code": face_payload.get("reason_code"),
                                    "event_id": face_payload.get("event_id"),
                                    "unknown_detection_id": face_payload.get("unknown_detection_id"),
                                    "timestamp": now_iso,
                                }
                                results["alerts"].append(alert)

                        self.last_face_detection = datetime.utcnow()
                        return results

                    status = payload.get("status")
                    if status in {"matched", "unknown"}:
                        person_name = payload.get("personnel_name") or payload.get("label") or "Unknown"
                        face_info = {
                            "bbox": payload.get("bbox") or {},
                            "name": person_name,
                            "person_id": payload.get("personnel_id"),
                            "track_id": payload.get("track_id"),
                            "is_known": status == "matched",
                            "confidence": float(payload.get("confidence", 0.0)),
                            "timestamp": datetime.utcnow().isoformat(),
                            "match_quality": payload.get("match_quality"),
                            "decision": payload.get("decision"),
                            "reason_code": payload.get("reason_code"),
                            "event_id": payload.get("event_id"),
                            "unknown_detection_id": payload.get("unknown_detection_id"),
                        }
                        results["faces"].append(face_info)

                        decision = str(payload.get("decision") or "").lower()
                        if status == "unknown":
                            self.detected_persons["Unknown"] = self.detected_persons.get("Unknown", 0) + 1
                        else:
                            self.detected_persons[person_name] = self.detected_persons.get(person_name, 0) + 1

                        if decision in {"deny", "review"}:
                            alert = {
                                "type": f"face_{decision}",
                                "camera_id": self.camera_id,
                                "name": person_name,
                                "confidence": face_info["confidence"],
                                "reason_code": payload.get("reason_code"),
                                "event_id": payload.get("event_id"),
                                "unknown_detection_id": payload.get("unknown_detection_id"),
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                            results["alerts"].append(alert)

                        self.last_face_detection = datetime.utcnow()
                        return results
            except Exception as e:
                logger.warning(f"Face pipeline failed for camera {self.camera_id}, fallback to legacy recognizer: {e}")
            finally:
                if local_db is not None:
                    try:
                        local_db.close()
                    except Exception:
                        pass

        if not self.face_recognizer:
            return results

        try:
            faces = self.face_recognizer.detect_and_align_face(frame)

            for face_data in faces:
                face_roi = face_data['image']
                bbox = face_data['bbox']
                recognition_result = self.face_recognizer.recognize_face(face_roi)

                face_info = {
                    "bbox": bbox,
                    "name": recognition_result.get("name", "Unknown"),
                    "person_id": recognition_result.get("person_id"),
                    "is_known": recognition_result.get("is_known", False),
                    "confidence": recognition_result.get("confidence", 0.0),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                results["faces"].append(face_info)

                if not recognition_result.get("is_known", False):
                    alert = {
                        "type": "unknown_face",
                        "camera_id": self.camera_id,
                        "name": "Unknown",
                        "confidence": face_info["confidence"],
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    results["alerts"].append(alert)
                    self.detected_persons["Unknown"] = self.detected_persons.get("Unknown", 0) + 1
                else:
                    person_name = face_info["name"]
                    self.detected_persons[person_name] = self.detected_persons.get(person_name, 0) + 1

                    try:
                        if db is not None and _HAS_DB_SERVICES and PersonnelService:
                            personnel_svc = PersonnelService()
                            person_id = recognition_result.get("person_id")
                            if person_id:
                                personnel_svc.log_personnel_event(
                                    db,
                                    personnel_id=person_id,
                                    camera_id=self.camera_id,
                                    direction="passage",
                                    confidence=face_info["confidence"],
                                    method="lbph",
                                )
                    except Exception as e:
                        logger.warning(f"Unable to log personnel event: {e}")

                self.last_face_detection = datetime.utcnow()

            return results
        except Exception as e:
            logger.error(f"Erreur dans _detect_faces: {e}")
            return results

    def _detect_vehicles(self, frame: np.ndarray, db: Optional[Session] = None) -> Dict:
        """
        Détection de véhicules et personnes
        
        Args:
            frame: Frame numpy BGR
            
        Returns:
            Dict avec objets détectés et alertes
        """
        results = {"vehicles": [], "alerts": []}

        if _HAS_VEHICLE_PIPELINE and VehicleRecognitionPipeline is not None:
            if self.frame_count % self.vehicle_pipeline_stride != 0:
                return results

            local_db = None
            db_session = db
            try:
                if db_session is None and SessionLocal is not None:
                    local_db = SessionLocal()
                    db_session = local_db

                if db_session is not None:
                    pipeline = VehicleRecognitionPipeline(db_session)
                    payload = pipeline.recognize_from_frame(
                        frame_bgr=frame,
                        camera_id=self.camera_id,
                        zone_id=None,
                        gate_id=None,
                        direction="IN",
                        persist=True,
                        save_snapshot=False,
                        image_bytes=None,
                    )

                    if (
                        bool(payload.get("vehicle_detected"))
                        or payload.get("plate_number")
                        or payload.get("event_id")
                        or payload.get("decision_event_id")
                        or payload.get("unknown_detection_id")
                        or str(payload.get("status") or "").lower() == "camera_tamper"
                    ):
                        vehicle_info = {
                            "type": payload.get("vehicle_class") or "vehicle",
                            "confidence": float(payload.get("confidence", 0.0)),
                            "bbox": payload.get("vehicle_bbox") or {},
                            "track_id": payload.get("track_id"),
                            "timestamp": payload.get("timestamp") or datetime.utcnow().isoformat(),
                            "plate_text": payload.get("plate_number"),
                            "plate_confidence": payload.get("plate_confidence"),
                            "decision": payload.get("access_decision") or payload.get("decision"),
                            "reason_code": payload.get("access_reason_code") or payload.get("decision_reason"),
                            "event_id": payload.get("event_id"),
                            "decision_event_id": payload.get("decision_event_id"),
                            "unknown_detection_id": payload.get("unknown_detection_id"),
                            "access_decision_result": payload.get("access_decision_result"),
                        }
                        results["vehicles"].append(vehicle_info)

                        vehicle_type = str(vehicle_info.get("type") or "vehicle")
                        self.detected_vehicles[vehicle_type] = self.detected_vehicles.get(vehicle_type, 0) + 1
                        self.last_vehicle_detection = datetime.utcnow()

                        access_decision = str(vehicle_info.get("decision") or "").lower()
                        if access_decision in {"deny", "review"}:
                            results["alerts"].append(
                                {
                                    "type": f"vehicle_{access_decision}",
                                    "camera_id": self.camera_id,
                                    "vehicle_type": vehicle_type,
                                    "plate_text": vehicle_info.get("plate_text"),
                                    "confidence": vehicle_info["confidence"],
                                    "reason_code": vehicle_info.get("reason_code"),
                                    "event_id": vehicle_info.get("decision_event_id") or vehicle_info.get("event_id"),
                                    "unknown_detection_id": vehicle_info.get("unknown_detection_id"),
                                    "timestamp": vehicle_info["timestamp"],
                                }
                            )
                        return results
                    return results
            except Exception as e:
                logger.warning(f"Vehicle pipeline failed for camera {self.camera_id}, fallback to legacy detector: {e}")
            finally:
                if local_db is not None:
                    try:
                        local_db.close()
                    except Exception:
                        pass
        
        if not self.vehicle_detector:
            return results
        
        try:
            # Utiliser le détecteur YOLO avec tracking
            detections = self.vehicle_detector.detect_with_tracking(frame, confidence=0.5)
            
            vehicles_by_type = {}
            persons_count = 0
            
            for det in detections:
                class_name = det.get("class", "unknown")
                confidence = det.get("confidence", 0.0)
                
                detection_data = {
                    "type": class_name,
                    "confidence": float(confidence),
                    "bbox": det.get("bbox", (0, 0, 0, 0)),
                    "track_id": det.get("track_id"),
                    "timestamp": datetime.utcnow().isoformat()
                }

                plate_info = det.get("plate") or det.get("license_plate") or det.get("plate_info") or {}
                if isinstance(plate_info, dict):
                    plate_text = plate_info.get("text") or plate_info.get("plate") or plate_info.get("value")
                    plate_conf = plate_info.get("confidence")
                else:
                    plate_text = plate_info
                    plate_conf = None

                plate_text = str(plate_text).strip().upper() if plate_text else None
                if plate_text:
                    detection_data["plate_text"] = plate_text
                if plate_conf is not None:
                    try:
                        detection_data["plate_confidence"] = float(plate_conf)
                    except Exception:
                        detection_data["plate_confidence"] = plate_conf
                
                # Compter par type
                if class_name == "person":
                    persons_count += 1
                else:
                    vehicles_by_type[class_name] = vehicles_by_type.get(class_name, 0) + 1
                
                results["vehicles"].append(detection_data)
                # Si OCR plaque disponible et DB accessible, créer entrée véhicule
                try:
                    # plate_text already extracted above
                    if plate_text and db is not None and _HAS_DB_SERVICES and VehicleEntryService:
                        vehicle_svc = VehicleEntryService()
                        # Eviter duplications: vérifier si plate déjà active
                        active_list = vehicle_svc.get_active_vehicles(db)
                        exists = next((e for e in active_list if e.license_plate == plate_text.upper()), None)
                        if not exists:
                            entry_payload = VehicleEntryCreate(
                                license_plate=plate_text.upper(),
                                vehicle_type=det.get('class', 'unknown'),
                                brand=det.get('brand', 'unknown'),
                                model=det.get('model', 'unknown'),
                                color=det.get('color', 'unknown'),
                                entry_camera_id=self.camera_id,
                                entry_time=datetime.utcnow(),
                                entry_confidence=float(confidence)
                            )
                            vehicle_entry = vehicle_svc.create_entry(db, entry_payload)
                            results_count = results.get('events_logged', 0)
                            results['events_logged'] = results_count + 1
                            results['vehicles'][-1].update({
                                'db_id': vehicle_entry.id,
                                'status': 'logged'
                            })
                except Exception as e:
                    logger.warning(f"Unable to log vehicle entry: {e}")
            
            # Créer alertes pour détections
            if persons_count > 0:
                alert = self.alert_service.trigger_person_alert(
                    camera_id=self.camera_id,
                    camera_name=self.camera_name,
                    confidence=0.85,
                    count=persons_count,
                    tenant_id=self.tenant_id
                )
                results["alerts"].append(alert.to_dict())
                self.last_vehicle_detection = datetime.utcnow()
            
            for vehicle_type, count in vehicles_by_type.items():
                self.detected_vehicles[vehicle_type] = self.detected_vehicles.get(vehicle_type, 0) + count
                
                alert = self.alert_service.trigger_vehicle_alert(
                    camera_id=self.camera_id,
                    camera_name=self.camera_name,
                    vehicle_type=vehicle_type,
                    confidence=0.85,
                    count=count,
                    tenant_id=self.tenant_id
                )
                results["alerts"].append(alert.to_dict())
                self.last_vehicle_detection = datetime.utcnow()
        
        except Exception as e:
            logger.error(f"Vehicle detection error: {e}")
        
        return results
    
    def _save_thumbnail(self, frame: np.ndarray) -> str:
        """
        Sauvegarder une miniature du frame
        
        Args:
            frame: Frame numpy BGR
            
        Returns:
            Chemin vers la miniature
        """
        try:
            # Redimensionner pour miniature
            h, w = frame.shape[:2]
            thumbnail = cv2.resize(frame, (320, int(320 * h / w)))
            
            # Sauvegarder
            filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = os.path.join(self.thumbnails_dir, filename)
            
            cv2.imwrite(filepath, thumbnail)
            return filepath
        except Exception as e:
            logger.error(f"Failed to save thumbnail: {e}")
            return None
    
    def _save_unknown_face(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]):
        """
        Sauvegarder un visage inconnu
        
        Args:
            frame: Frame complet
            bbox: Boîte englobante (left, top, right, bottom)
        """
        try:
            left, top, right, bottom = bbox
            face_img = frame[max(0, top):bottom, max(0, left):right]
            
            if face_img.size == 0:
                return
            
            unknown_dir = f"{self.detections_dir}/unknown_faces"
            os.makedirs(unknown_dir, exist_ok=True)
            
            filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
            filepath = os.path.join(unknown_dir, filename)
            
            cv2.imwrite(filepath, face_img)
            logger.debug(f"Unknown face saved: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save unknown face: {e}")
    
    def get_statistics(self) -> Dict:
        """Récupérer les statistiques du processeur"""
        return {
            "camera_id": self.camera_id,
            "camera_name": self.camera_name,
            "frame_count": self.frame_count,
            "detected_persons": self.detected_persons,
            "detected_vehicles": self.detected_vehicles,
            "last_face_detection": self.last_face_detection.isoformat() if self.last_face_detection else None,
            "last_vehicle_detection": self.last_vehicle_detection.isoformat() if self.last_vehicle_detection else None
        }


# Registry global pour les processeurs de caméras
_frame_processors: Dict[int, FrameProcessor] = {}


def get_frame_processor(camera_id: int, camera_name: str) -> FrameProcessor:
    """Obtenir ou créer un processeur de frames pour une caméra"""
    if camera_id not in _frame_processors:
        _frame_processors[camera_id] = FrameProcessor(camera_id, camera_name)
    return _frame_processors[camera_id]


def remove_frame_processor(camera_id: int):
    """Supprimer un processeur de frames"""
    if camera_id in _frame_processors:
        del _frame_processors[camera_id]
