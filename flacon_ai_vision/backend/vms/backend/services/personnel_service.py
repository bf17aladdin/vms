# vms/backend/services/personnel_service.py - Service Personnel + Reconnaissance Faciale

import os
import pickle
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta, date
from pathlib import Path

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None

from sqlalchemy.orm import Session
from sqlalchemy import desc, func
import logging

try:
    from facial_recognition.face_recognizer import FaceRecognizer
    HAS_FACE_RECOGNIZER = True
except (ImportError, ModuleNotFoundError):
    HAS_FACE_RECOGNIZER = False
    FaceRecognizer = None
from ..models import Personnel, PersonnelEvent, Camera
from ..schemas import PersonnelCreate, PersonnelUpdate, PersonnelEventOut

logger = logging.getLogger(__name__)

class PersonnelService:
    """Service pour gestion du personnel et reconnaissance faciale"""
    
    KNOWN_FACES_DIR = Path("data/known_faces")
    PERSONNEL_ENCODINGS_FILE = KNOWN_FACES_DIR / "personnel_encodings.pkl"
    LBPH_THRESHOLD = 100  # Distance maximale pour match LBPH (0-255)
    CONFIDENCE_MIN = 0.7  # Confiance minimale acceptée
    
    def __init__(self):
        # Initialize FaceRecognizer only if available
        if HAS_FACE_RECOGNIZER and FaceRecognizer is not None:
            try:
                self.recognizer = FaceRecognizer()
            except Exception as e:
                logger.warning(f"Failed to initialize FaceRecognizer: {e}")
                self.recognizer = None
        else:
            self.recognizer = None
            logger.warning("FaceRecognizer not available - facial recognition disabled")
        
        self.known_encodings: Dict[int, np.ndarray if HAS_NUMPY else None] = {}  # {personnel_id: encoding}
        self.load_all_personnel_encodings()
    
    # ========== CHARGEMENT ENCODAGES ==========
    
    def load_all_personnel_encodings(self):
        """Charger tous les encodages du personnel depuis cache"""
        try:
            self.KNOWN_FACES_DIR.mkdir(parents=True, exist_ok=True)
            
            if self.PERSONNEL_ENCODINGS_FILE.exists():
                with open(self.PERSONNEL_ENCODINGS_FILE, "rb") as f:
                    data = pickle.load(f)
                    # Convertir listes en numpy arrays
                    self.known_encodings = {
                        pid: np.array(enc) if isinstance(enc, list) else enc
                        for pid, enc in data.items()
                    }
                    logger.info(f"✓ Chargé {len(self.known_encodings)} encodages personnel")
        except Exception as e:
            logger.error(f"Erreur chargement encodages: {e}")
    
    def save_personnel_encodings(self):
        """Sauvegarder encodages en cache pickle"""
        try:
            self.KNOWN_FACES_DIR.mkdir(parents=True, exist_ok=True)
            
            # Convertir numpy arrays en listes pour pickle
            data_to_save = {
                pid: enc.tolist() if isinstance(enc, np.ndarray) else enc
                for pid, enc in self.known_encodings.items()
            }
            
            with open(self.PERSONNEL_ENCODINGS_FILE, "wb") as f:
                pickle.dump(data_to_save, f)
            logger.info("✓ Encodages personnel sauvegardés")
        except Exception as e:
            logger.error(f"Erreur sauvegarde encodages: {e}")
    
    # ========== RECONNAISSANCE FACIALE ==========
    
    def recognize_face(self, frame: np.ndarray) -> Tuple[Optional[int], float]:
        """
        Reconnaître un visage dans le frame
        Retour: (personnel_id, confidence) ou (None, 0.0)
        """
        if not self.known_encodings:
            return None, 0.0
        
        try:
            # Détecter et encoder le visage
            face_encoding = self.recognizer.encode_face(frame)
            if face_encoding is None:
                return None, 0.0
            
            # Comparer avec encodages connus
            best_match_id = None
            best_confidence = 0.0
            
            for personnel_id, known_encoding in self.known_encodings.items():
                # Calcul distance LBPH (0-255)
                distance = self.recognizer.compare_faces(face_encoding, known_encoding)
                
                # Normaliser distance en confiance (0-1)
                confidence = max(0, 1.0 - (distance / 255.0))
                
                if distance < self.LBPH_THRESHOLD and confidence > best_confidence:
                    best_match_id = personnel_id
                    best_confidence = confidence
            
            # Retourner si confiance suffisante
            if best_confidence >= self.CONFIDENCE_MIN:
                return best_match_id, best_confidence
            
            return None, 0.0
        
        except Exception as e:
            logger.error(f"Erreur reconnaissance faciale: {e}")
            return None, 0.0
    
    # ========== CRUD PERSONNEL ==========
    
    def create_personnel(self, db: Session, personnel_data: PersonnelCreate) -> Personnel:
        """Créer nouvelle personne"""
        personnel = Personnel(
            full_name=personnel_data.full_name,
            recruitment_id=personnel_data.recruitment_id,
            category=personnel_data.category,
            gender=personnel_data.gender,
            cin=personnel_data.cin,
            photo_path=personnel_data.photo_path,
            allowed_camera_ids=personnel_data.allowed_camera_ids,
            authorized_hours_start=personnel_data.authorized_hours_start,
            authorized_hours_end=personnel_data.authorized_hours_end,
        )
        db.add(personnel)
        db.commit()
        db.refresh(personnel)
        logger.info(f"✓ Personnel créé: {personnel.full_name} (ID: {personnel.id})")
        return personnel
    
    def update_personnel(self, db: Session, personnel_id: int, 
                        personnel_data: PersonnelUpdate) -> Optional[Personnel]:
        """Mettre à jour personnel"""
        personnel = db.query(Personnel).filter_by(id=personnel_id).first()
        
        if personnel:
            for field, value in personnel_data.model_dump(exclude_unset=True).items():
                setattr(personnel, field, value)
            
            db.commit()
            db.refresh(personnel)
            logger.info(f"✓ Personnel mis à jour: {personnel.full_name}")
        
        return personnel
    
    def get_personnel(self, db: Session, personnel_id: int) -> Optional[Personnel]:
        """Récupérer personnel par ID"""
        return db.query(Personnel).filter_by(id=personnel_id).first()
    
    def get_personnel_by_cin(self, db: Session, cin: str) -> Optional[Personnel]:
        """Récupérer personnel par CIN"""
        return db.query(Personnel).filter_by(cin=cin).first()
    
    def get_personnel_by_recruitment_id(self, db: Session, recruitment_id: str) -> Optional[Personnel]:
        """Récupérer personnel par ID recrutement"""
        return db.query(Personnel).filter_by(recruitment_id=recruitment_id).first()
    
    def list_personnel(self, db: Session, category: Optional[str] = None,
                      is_active: Optional[bool] = True,
                      limit: int = 100) -> List[Personnel]:
        """Lister le personnel avec filtres optionnels"""
        query = db.query(Personnel)
        
        if category:
            query = query.filter_by(category=category)
        if is_active is not None:
            query = query.filter_by(is_active=is_active)
        
        return query.limit(limit).all()
    
    # ========== ENCODAGES FACIAUX ==========
    
    def load_face_encoding(self, db: Session, personnel_id: int, image_path: str) -> bool:
        """
        Charger encodage facial pour un personnel depuis une image
        Nécessite: image PNG/JPG du visage clairs
        """
        try:
            if not os.path.exists(image_path):
                logger.error(f"Image pas trouvée: {image_path}")
                return False
            
            # Lire image et encoder
            image = cv2.imread(image_path)
            if image is None:
                logger.error(f"Impossible de lire image: {image_path}")
                return False
            
            encoding = self.recognizer.encode_face(image)
            
            if encoding is None:
                logger.warning(f"Pas de visage détecté dans {image_path}")
                return False
            
            # Sauvegarder encodage en cache
            self.known_encodings[personnel_id] = encoding
            self.save_personnel_encodings()
            
            # Sauvegarder aussi en DB (encodage compressé)
            personnel = self.get_personnel(db, personnel_id)
            if personnel:
                personnel.face_encodings = encoding.tolist()  # Convertir en liste
                db.commit()
                logger.info(f"✓ Encodage chargé: {personnel.full_name}")
                return True
        
        except Exception as e:
            logger.error(f"Erreur chargement encodage: {e}")
        
        return False
    
    def has_face_encoding(self, personnel_id: int) -> bool:
        """Vérifier si personnel a encodage facial"""
        return personnel_id in self.known_encodings
    
    # ========== ÉVÉNEMENTS PERSONNEL ==========
    
    def log_personnel_event(self, db: Session, personnel_id: int, camera_id: int,
                           direction: str, confidence: float,
                           method: str = "lbph", notes: Optional[str] = None) -> PersonnelEvent:
        """
        Enregistrer événement entrée/sortie personnel
        
        Args:
            direction: "entrée", "sortie" ou "passage"
            confidence: Score de reconnaissance (0-1)
            method: "lbph", "face_recognition", "manual"
        """
        personnel = self.get_personnel(db, personnel_id)
        
        # Vérifier blacklist
        if personnel and personnel.is_blacklisted:
            logger.warning(f"⚠ Tentative accès personnel liste noire: {personnel.full_name}")
        
        # Créer événement
        event = PersonnelEvent(
            personnel_id=personnel_id,
            camera_id=camera_id,
            direction=direction,
            confidence=confidence,
            method=method,
            detected_at=datetime.utcnow(),
            notes=notes,
        )
        
        db.add(event)
        
        # Mettre à jour tracking personnel
        if personnel:
            if direction == "entrée":
                personnel.last_entry = datetime.utcnow()
                personnel.total_entries_today += 1
            elif direction == "sortie":
                personnel.last_exit = datetime.utcnow()
        
        db.commit()
        db.refresh(event)
        logger.info(f"✓ Événement personnel: {personnel.full_name} - {direction} (confiance: {confidence:.2f})")
        
        return event
    
    def get_personnel_events(self, db: Session, personnel_id: int,
                            limit: int = 50) -> List[PersonnelEvent]:
        """Récupérer événements récents du personnel"""
        return (db.query(PersonnelEvent)
                .filter_by(personnel_id=personnel_id)
                .order_by(desc(PersonnelEvent.detected_at))
                .limit(limit)
                .all())
    
    # ========== STATISTIQUES ==========
    
    def get_daily_summary(self, db: Session, camera_id: Optional[int] = None) -> Dict:
        """Résumé quotidien des entrée/sortie"""
        today = date.today()
        
        query = db.query(PersonnelEvent).filter(
            func.date(PersonnelEvent.detected_at) == today
        )
        
        if camera_id:
            query = query.filter_by(camera_id=camera_id)
        
        events = query.all()
        
        entries = sum(1 for e in events if e.direction == "entrée")
        exits = sum(1 for e in events if e.direction == "sortie")
        
        # Catégories
        by_category = {}
        for event in events:
            if event.personnel:
                cat = event.personnel.category
                by_category[cat] = by_category.get(cat, 0) + 1
        
        return {
            "date": today.isoformat(),
            "total_events": len(events),
            "entries": entries,
            "exits": exits,
            "unique_personnel": len(set(e.personnel_id for e in events)),
            "by_category": by_category,
        }
    
    def get_personnel_analytics(self, db: Session, personnel_id: int,
                               days: int = 30) -> Dict:
        """Analytics pour une personne"""
        threshold_date = datetime.utcnow() - timedelta(days=days)
        
        events = (db.query(PersonnelEvent)
                 .filter_by(personnel_id=personnel_id)
                 .filter(PersonnelEvent.detected_at >= threshold_date)
                 .order_by(PersonnelEvent.detected_at)
                 .all())
        
        entries = [e for e in events if e.direction == "entrée"]
        exits = [e for e in events if e.direction == "sortie"]
        
        return {
            "personnel_id": personnel_id,
            "days": days,
            "total_events": len(events),
            "entries": len(entries),
            "exits": len(exits),
            "avg_confidence": np.mean([e.confidence for e in events]) if events else 0.0,
            "first_detection": events[0].detected_at if events else None,
            "last_detection": events[-1].detected_at if events else None,
        }
