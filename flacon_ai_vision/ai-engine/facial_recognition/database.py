"""
Intégration avec la base de données Falcon AI Vision existante
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from .config import FacialRecognitionConfig

class FaceDatabase:
    def __init__(self, db_path=None):
        self.db_path = db_path or FacialRecognitionConfig.DATABASE_PATH
        self.conn = None
        self.connect()
        
        # Vérifier et créer les tables nécessaires
        self.init_tables()
    
    def connect(self):
        """Connexion à la base de données"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row  # Pour accéder aux colonnes par nom
            print(f"✓ Connecté à la base de données: {self.db_path}")
            return True
        except Exception as e:
            print(f"✗ Erreur de connexion à la base: {e}")
            return False
    
    def init_tables(self):
        """Crée les tables nécessaires si elles n'existent pas"""
        try:
            cursor = self.conn.cursor()
            
            # Table des visages connus (si elle n'existe pas déjà)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS face_persons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    role TEXT,
                    department TEXT,
                    access_level INTEGER DEFAULT 1,
                    face_encoding BLOB,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Table des événements de détection
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS face_detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_id INTEGER,
                    person_id INTEGER,
                    confidence REAL,
                    is_known INTEGER DEFAULT 0,
                    is_blacklisted INTEGER DEFAULT 0,
                    detection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    face_image_path TEXT,
                    metadata TEXT,
                    FOREIGN KEY (person_id) REFERENCES face_persons (id)
                )
            ''')
            
            # Table des alertes
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS face_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    detection_id INTEGER,
                    alert_type TEXT,
                    severity TEXT,
                    message TEXT,
                    is_resolved INTEGER DEFAULT 0,
                    resolved_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (detection_id) REFERENCES face_detections (id)
                )
            ''')
            
            # Table des caméras (pour synchronisation)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS face_cameras (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera_name TEXT,
                    camera_source TEXT,
                    location TEXT,
                    is_active INTEGER DEFAULT 1,
                    last_detection TIMESTAMP
                )
            ''')
            
            self.conn.commit()
            print("✓ Tables de reconnaissance faciale initialisées")
            
        except Exception as e:
            print(f"✗ Erreur lors de l'initialisation des tables: {e}")
    
    def log_detection(self, camera_id, detection_data):
        """
        Enregistre une détection faciale dans la base
        
        Args:
            camera_id: ID de la caméra
            detection_data: Dictionnaire avec les données de détection
        """
        try:
            cursor = self.conn.cursor()
            
            cursor.execute('''
                INSERT INTO face_detections 
                (camera_id, person_id, confidence, is_known, is_blacklisted, 
                 face_image_path, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                camera_id,
                detection_data.get('person_id'),
                detection_data.get('confidence', 0.0),
                detection_data.get('is_known', 0),
                detection_data.get('is_blacklisted', 0),
                detection_data.get('face_image_path'),
                json.dumps(detection_data.get('metadata', {}))
            ))
            
            detection_id = cursor.lastrowid
            
            # Créer une alerte si nécessaire
            if detection_data.get('is_blacklisted') or not detection_data.get('is_known'):
                alert_type = "BLACKLIST" if detection_data.get('is_blacklisted') else "UNKNOWN"
                severity = "HIGH" if detection_data.get('is_blacklisted') else "MEDIUM"
                
                cursor.execute('''
                    INSERT INTO face_alerts 
                    (detection_id, alert_type, severity, message)
                    VALUES (?, ?, ?, ?)
                ''', (
                    detection_id,
                    alert_type,
                    severity,
                    f"{alert_type} face detected on camera {camera_id}"
                ))
            
            self.conn.commit()
            return detection_id
            
        except Exception as e:
            print(f"✗ Erreur lors de l'enregistrement: {e}")
            return None
    
    def get_known_persons(self):
        """Récupère la liste des personnes connues"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM face_persons WHERE is_active = 1')
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"✗ Erreur lors de la récupération: {e}")
            return []
    
    def add_known_person(self, name, face_encoding, role=None, department=None):
        """Ajoute une personne connue"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO face_persons (name, role, department, face_encoding)
                VALUES (?, ?, ?, ?)
            ''', (name, role, department, face_encoding))
            
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            print(f"✗ Erreur lors de l'ajout: {e}")
            return None
    
    def get_recent_detections(self, limit=50):
        """Récupère les détections récentes"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT d.*, p.name as person_name, c.camera_name
                FROM face_detections d
                LEFT JOIN face_persons p ON d.person_id = p.id
                LEFT JOIN face_cameras c ON d.camera_id = c.id
                ORDER BY d.detection_time DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"✗ Erreur: {e}")
            return []
    
    def close(self):
        """Ferme la connexion"""
        if self.conn:
            self.conn.close()