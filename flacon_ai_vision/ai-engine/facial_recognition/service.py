"""
Service de reconnaissance faciale principal
"""
import cv2
import numpy as np
import time
import threading
from datetime import datetime
from queue import Queue
import signal
import sys

from .config import FacialRecognitionConfig
from .face_detector import FaceDetector
from .face_recognizer import FaceRecognizer
from .database import FaceDatabase

class FacialRecognitionService:
    """Service principal de reconnaissance faciale"""
    
    def __init__(self):
        # Initialiser la configuration
        FacialRecognitionConfig.init_directories()
        
        # Initialiser les composants
        self.detector = FaceDetector()
        self.recognizer = FaceRecognizer()
        self.database = FaceDatabase()
        
        # État du service
        self.is_running = False
        self.camera_threads = {}
        self.event_queue = Queue()
        
        # Configuration
        self.config = FacialRecognitionConfig
        
        # Gestion des signaux
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        print("✓ Service de reconnaissance faciale initialisé")
    
    def start(self):
        """Démarre le service"""
        if self.is_running:
            print("⚠ Service déjà en cours d'exécution")
            return
        
        print("🚀 Démarrage du service de reconnaissance faciale...")
        self.is_running = True
        
        # Démarrer le traitement des événements
        self.event_processor_thread = threading.Thread(
            target=self._process_events,
            daemon=True
        )
        self.event_processor_thread.start()
        
        # Démarrer les caméras
        self._start_all_cameras()
        
        print("✅ Service démarré avec succès")
        
        # Boucle principale
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
    
    def _start_all_cameras(self):
        """Démarre toutes les caméras configurées"""
        for cam_name, cam_config in self.config.CAMERAS.items():
            if cam_config.get("is_active", False):
                self._start_camera(cam_name, cam_config)
    
    def _start_camera(self, camera_name, camera_config):
        """Démarre une caméra spécifique"""
        thread = threading.Thread(
            target=self._camera_processing_loop,
            args=(camera_name, camera_config),
            daemon=True
        )
        thread.start()
        self.camera_threads[camera_name] = thread
        print(f"📹 Caméra '{camera_name}' démarrée")
    
    def _camera_processing_loop(self, camera_name, camera_config):
        """Boucle de traitement pour une caméra"""
        camera_id = camera_config["id"]
        source = camera_config["source"]
        
        # Ouvrir le flux vidéo
        cap = cv2.VideoCapture(source)
        
        if not cap.isOpened():
            print(f"✗ Impossible d'ouvrir la caméra {camera_name} ({source})")
            return
        
        print(f"🎥 Flux vidéo ouvert pour {camera_name}")
        
        frame_count = 0
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        
        while self.is_running and cap.isOpened():
            ret, frame = cap.read()
            
            if not ret:
                print(f"✗ Erreur de lecture sur {camera_name}")
                time.sleep(1)
                continue
            
            # Traiter une frame sur N pour réduire la charge
            frame_count += 1
            if frame_count % self.config.FRAME_SKIP != 0:
                continue
            
            # Détecter et reconnaître les visages
            detections = self.process_frame(frame, camera_id, camera_name)
            
            # Ajouter les détections à la file d'attente
            for detection in detections:
                self.event_queue.put(detection)
            
            # Affichage en temps réel (optionnel)
            if self.config.DEBUG_MODE:
                self.display_frame(frame, detections, camera_name)
            
            # Contrôler le FPS
            time.sleep(1 / fps)
        
        cap.release()
        print(f"📹 Caméra '{camera_name}' arrêtée")
    
    def process_frame(self, frame, camera_id, camera_name):
        """Traite une frame et retourne les détections"""
        detections = []
        
        # Détection des visages
        faces = self.detector.detect_faces(frame)
        
        for face in faces:
            # Extraire la région du visage
            x, y, w, h = face["bbox"]
            face_roi = frame[y:y+h, x:x+w]
            
            if face_roi.size == 0:
                continue
            
            # Reconnaissance faciale
            recognition_result = self.recognizer.recognize_face(face_roi)
            
            # Préparer les données de détection
            detection_data = {
                "camera_id": camera_id,
                "camera_name": camera_name,
                "bbox": face["bbox"],
                "confidence": face["confidence"],
                "recognition_result": recognition_result,
                "timestamp": datetime.now().isoformat(),
                "is_known": recognition_result["is_known"],
                "person_id": recognition_result.get("person_id"),
                "person_name": recognition_result.get("name", "Inconnu"),
                "recognition_confidence": recognition_result.get("confidence", 0.0)
            }
            
            # Sauvegarder l'image si visage inconnu
            if not recognition_result["is_known"]:
                img_path = self.save_unknown_face(face_roi, camera_id)
                detection_data["face_image_path"] = img_path
            
            detections.append(detection_data)
        
        return detections
    
    def save_unknown_face(self, face_image, camera_id):
        """Sauvegarde un visage inconnu"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"unknown_cam{camera_id}_{timestamp}.jpg"
        filepath = self.config.UNKNOWN_FACES_DIR / filename
        
        try:
            cv2.imwrite(str(filepath), face_image)
            return str(filepath)
        except Exception as e:
            print(f"✗ Erreur lors de la sauvegarde: {e}")
            return None
    
    def display_frame(self, frame, detections, camera_name):
        """Affiche la frame avec les détections (mode debug)"""
        display_frame = frame.copy()
        
        for detection in detections:
            x, y, w, h = detection["bbox"]
            
            # Couleur selon le statut
            if detection["is_known"]:
                color = (0, 255, 0)  # Vert pour connu
                label = f"{detection['person_name']}: {detection['recognition_confidence']:.1%}"
            else:
                color = (0, 0, 255)  # Rouge pour inconnu
                label = f"Inconnu: {detection['confidence']:.1%}"
            
            # Dessiner la boîte
            cv2.rectangle(display_frame, (x, y), (x+w, y+h), color, 2)
            
            # Ajouter le texte
            y_text = y - 10 if y - 10 > 10 else y + 20
            cv2.putText(
                display_frame, label, (x, y_text),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2
            )
        
        # Afficher la frame
        cv2.imshow(f"Caméra: {camera_name}", display_frame)
        
        # Attendre 1ms pour l'affichage
        cv2.waitKey(1)
    
    def _process_events(self):
        """Traite les événements de la file d'attente"""
        while self.is_running:
            try:
                detection = self.event_queue.get(timeout=1)
                
                # Enregistrer dans la base de données
                if self.config.ENABLE_DB_LOGGING:
                    self.database.log_detection(
                        detection["camera_id"],
                        {
                            "person_id": detection.get("person_id"),
                            "confidence": detection["recognition_confidence"],
                            "is_known": detection["is_known"],
                            "is_blacklisted": False,  # À implémenter
                            "face_image_path": detection.get("face_image_path"),
                            "metadata": {
                                "bbox": detection["bbox"],
                                "detection_confidence": detection["confidence"],
                                "camera_name": detection["camera_name"]
                            }
                        }
                    )
                
                # Envoyer une alerte si nécessaire
                if not detection["is_known"] and self.config.ALERT_UNKNOWN_FACES:
                    self.send_alert(detection)
                
                self.event_queue.task_done()
                
            except Exception as e:
                # File d'attente vide, continuer
                continue
    
    def send_alert(self, detection):
        """Envoie une alerte"""
        alert_message = (
            f"🚨 Visage inconnu détecté!\n"
            f"📹 Caméra: {detection['camera_name']}\n"
            f"⏰ Heure: {detection['timestamp']}\n"
            f"🎯 Confiance: {detection['confidence']:.1%}"
        )
        
        print(f"\n{'='*50}")
        print(alert_message)
        print(f"{'='*50}\n")
        
        # Ici, vous pouvez ajouter l'envoi d'email, webhook, etc.
    
    def signal_handler(self, signum, frame):
        """Gère les signaux d'arrêt"""
        print(f"\n⚠ Signal {signum} reçu, arrêt en cours...")
        self.stop()
    
    def stop(self):
        """Arrête le service"""
        print("🛑 Arrêt du service de reconnaissance faciale...")
        self.is_running = False
        
        # Attendre que les threads se terminent
        for cam_name, thread in self.camera_threads.items():
            if thread.is_alive():
                thread.join(timeout=2)
        
        # Fermer la base de données
        self.database.close()
        
        # Fermer les fenêtres OpenCV
        cv2.destroyAllWindows()
        
        print("✅ Service arrêté avec succès")
        sys.exit(0)

# Interface de ligne de commande
def main():
    """Point d'entrée principal"""
    print("=" * 60)
    print("FALCON AI VISION - Système de Reconnaissance Faciale")
    print("=" * 60)
    
    service = FacialRecognitionService()
    
    print("\nCommandes disponibles:")
    print("  CTRL+C - Arrêter le service")
    print("  s      - Afficher les statistiques")
    print("  l      - Lister les caméras")
    print("  q      - Quitter")
    
    service.start()

if __name__ == "__main__":
    main()