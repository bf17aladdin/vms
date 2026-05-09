import cv2
import numpy as np
import os
import pickle
import time
from pathlib import Path
from datetime import datetime
import hashlib
import logging

logger = logging.getLogger(__name__)

class FaceRecognizer:
    """Système de reconnaissance faciale LBPH"""
    
    def __init__(self, model_path=None, recognition_threshold=0.3):
        """
        Initialise le système de reconnaissance
        
        Args:
            model_path: Chemin vers le fichier de modèle sauvegardé
            recognition_threshold: Seuil de confiance pour la reconnaissance
        """
        self.recognition_threshold = recognition_threshold
        
        # Déterminer le chemin du modèle
        if model_path is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.model_path = project_root / "models" / "face_recognition" / "face_recognizer.yml"
            self.metadata_path = project_root / "models" / "face_recognition" / "face_metadata.pkl"
        else:
            logger.info("Aucun modèle trouvé, initialisation d'un nouveau modèle")
            self._reset_metadata()
            return False
            self.model_path = Path(model_path)
            self.metadata_path = self.model_path.with_suffix('.pkl')
        
        # Initialiser le reconnaisseur LBPH
        self.recognizer = cv2.face.LBPHFaceRecognizer_create()
        
        # Détecteur Haar pour l'alignement
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        # Base de données des personnes connues
        self.persons = {}  # {person_id: {"name": "...", "images": [...], "encodings": [...]}}
        self.label_to_person = {}  # {label_id: person_id}
        self.person_to_label = {}  # {person_id: label_id}
        
        # Statistiques
        self.recognitions_count = 0
        self.unknown_count = 0
        
        # Charger le modèle s'il existe
        self.load_model()
        
        logger.info("FaceRecognizer initialized")

    def _reset_metadata(self):
        self.persons = {}
        self.label_to_person = {}
        self.person_to_label = {}

    def _backup_incompatible_metadata(self):
        if not self.metadata_path.exists():
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.metadata_path.with_suffix(f".invalid_{timestamp}.pkl")
        try:
            self.metadata_path.replace(backup_path)
            logger.warning("Incompatible face metadata moved to %s", backup_path)
        except Exception as e:
            logger.warning("Failed to back up incompatible face metadata %s: %s", self.metadata_path, e)
    
    def load_model(self):
        """Charge le modèle entraîné depuis le disque"""
        if self.model_path.exists():
            try:
                self.recognizer.read(str(self.model_path))
                
                # Charger les métadonnées
                if self.metadata_path.exists():
                    with open(self.metadata_path, 'rb') as f:
                        metadata = pickle.load(f)
                        self.persons = metadata.get('persons', {})
                        self.label_to_person = metadata.get('label_to_person', {})
                        self.person_to_label = metadata.get('person_to_label', {})
                
                logger.info(
                    "Face model loaded: %s persons, %s labels",
                    len(self.persons),
                    len(self.label_to_person),
                )
                return True
            except Exception as e:
                if isinstance(e, ModuleNotFoundError):
                    self._backup_incompatible_metadata()
                logger.warning("Failed to load face model metadata: %s", e)
                self._reset_metadata()
                return False
                print(f"Erreur lors du chargement du modèle: {e}")
                self.persons = {}
                self.label_to_person = {}
                self.person_to_label = {}
                return False
        else:
            print("Aucun modèle trouvé, initialisation d'un nouveau modèle")
            self.persons = {}
            self.label_to_person = {}
            self.person_to_label = {}
            return False
    
    def save_model(self):
        """Sauvegarde le modèle sur le disque"""
        try:
            # Sauvegarder le modèle LBPH
            model_dir = self.model_path.parent
            model_dir.mkdir(parents=True, exist_ok=True)
            self.recognizer.write(str(self.model_path))
            
            # Sauvegarder les métadonnées
            metadata = {
                'persons': self.persons,
                'label_to_person': self.label_to_person,
                'person_to_label': self.person_to_label,
                'saved_at': datetime.now().isoformat(),
                'version': '1.0'
            }
            
            with open(self.metadata_path, 'wb') as f:
                pickle.dump(metadata, f)
            
            print(f"Model saved: {self.model_path}")
            print(f"  - Personnes: {len(self.persons)}")
            print(f"  - Labels: {len(self.label_to_person)}")
            return True
        except Exception as e:
            print(f"Erreur lors de la sauvegarde du modèle: {e}")
            return False
    
    def preprocess_face(self, face_image):
        """
        Prétraite une image de visage pour la reconnaissance
        
        Args:
            face_image: Image du visage (BGR)
        
        Returns:
            numpy array: Visage prétraité (niveaux de gris, normalisé)
        """
        if face_image is None or face_image.size == 0:
            return None
        
        # Convertir en niveaux de gris
        if len(face_image.shape) == 3:
            gray = cv2.cvtColor(face_image, cv2.COLOR_BGR2GRAY)
        else:
            gray = face_image
        
        # Redimensionner à une taille standard
        target_size = (100, 100)
        resized = cv2.resize(gray, target_size)
        
        # Égalisation d'histogramme pour améliorer le contraste
        equalized = cv2.equalizeHist(resized)
        
        # Lissage pour réduire le bruit
        smoothed = cv2.GaussianBlur(equalized, (3, 3), 0)
        
        return smoothed
    
    def detect_and_align_face(self, image):
        """
        Détecte et aligne un visage dans une image
        
        Args:
            image: Image complète (BGR)
        
        Returns:
            list: Liste des visages détectés et alignés
        """
        faces = []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Détecter les visages
        detected_faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30)
        )
        
        for (x, y, w, h) in detected_faces:
            # Extraire le visage
            face_roi = gray[y:y+h, x:x+w]
            
            # Redimensionner pour uniformité
            face_resized = cv2.resize(face_roi, (100, 100))
            
            faces.append({
                "bbox": (x, y, w, h),
                "image": face_resized,
                "original_region": image[y:y+h, x:x+w]
            })
        
        return faces
    
    def add_person(self, person_name, face_images):
        """
        Ajoute une nouvelle personne au système
        
        Args:
            person_name: Nom de la personne
            face_images: Liste d'images de visage de la personne
        
        Returns:
            str: ID de la personne ajoutée
        """
        if not face_images:
            print(f"Aucune image fournie pour {person_name}")
            return None
        
        # Générer un ID unique pour la personne
        person_id = hashlib.md5(f"{person_name}_{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        
        # Prétraiter les images
        processed_faces = []
        valid_images = 0
        
        for img in face_images:
            processed = self.preprocess_face(img)
            if processed is not None:
                processed_faces.append(processed)
                valid_images += 1
        
        if not processed_faces:
            print(f"Aucune image valide pour {person_name}")
            return None
        
        # Stocker les informations de la personne
        self.persons[person_id] = {
            "name": person_name,
            "id": person_id,
            "added_at": datetime.now().isoformat(),
            "image_count": valid_images,
            "sample_images": face_images[:min(3, len(face_images))]  # Garder quelques échantillons
        }
        
        # Assigner un label d'entraînement
        if person_id not in self.person_to_label:
            new_label = len(self.person_to_label)
            self.person_to_label[person_id] = new_label
            self.label_to_person[new_label] = person_id
        
        # Réentraîner le modèle
        self.retrain_model()
        
        print(f"Personne ajoutée: {person_name} (ID: {person_id}) avec {valid_images} images")
        return person_id
    
    def retrain_model(self):
        """Réentraîne le modèle avec toutes les personnes connues"""
        if not self.persons:
            print("Aucune personne à entraîner")
            return False
        
        faces = []
        labels = []
        
        # Pour chaque personne, collecter toutes ses images d'entraînement
        for person_id, person_info in self.persons.items():
            label = self.person_to_label[person_id]
            
            # Ici, vous devriez avoir un dossier d'images pour chaque personne
            # Pour l'exemple, nous créons des données factices
            # En production, chargez les images depuis le disque
            
            # Pour le moment, créons une image factice
            dummy_face = np.random.randint(0, 255, (100, 100), dtype=np.uint8)
            faces.append(dummy_face)
            labels.append(label)
        
        if faces:
            self.recognizer.train(faces, np.array(labels))
            self.save_model()
            print(f"Modèle réentraîné avec {len(faces)} images de {len(self.persons)} personnes")
            return True
        
        return False
    
    def recognize_face(self, face_image):
        """
        Reconnaît un visage
        
        Args:
            face_image: Image du visage (BGR ou niveaux de gris)
        
        Returns:
            dict: Résultat de la reconnaissance
        """
        start_time = time.time()
        
        # Prétraiter le visage
        processed_face = self.preprocess_face(face_image)
        
        if processed_face is None:
            return {
                "is_known": False,
                "name": "Inconnu",
                "person_id": None,
                "confidence": 0.0,
                "processing_time": time.time() - start_time
            }
        
        # Prédire avec le modèle
        try:
            label, confidence = self.recognizer.predict(processed_face)
            
            # Pour LBPH, une confiance basse est meilleure
            # Normaliser entre 0 et 1 (0 = meilleur, 1 = pire)
            normalized_confidence = max(0, 1 - (confidence / 100))
            
            if label in self.label_to_person and normalized_confidence > self.recognition_threshold:
                person_id = self.label_to_person[label]
                person_info = self.persons.get(person_id, {"name": f"Personne_{label}"})
                
                self.recognitions_count += 1
                
                return {
                    "is_known": True,
                    "name": person_info["name"],
                    "person_id": person_id,
                    "label": label,
                    "confidence": normalized_confidence,
                    "raw_confidence": confidence,
                    "processing_time": time.time() - start_time
                }
            else:
                self.unknown_count += 1
                
                return {
                    "is_known": False,
                    "name": "Inconnu",
                    "person_id": None,
                    "confidence": normalized_confidence,
                    "raw_confidence": confidence,
                    "processing_time": time.time() - start_time
                }
                
        except Exception as e:
            print(f"Erreur lors de la reconnaissance: {e}")
            
            return {
                "is_known": False,
                "name": "Inconnu",
                "person_id": None,
                "confidence": 0.0,
                "error": str(e),
                "processing_time": time.time() - start_time
            }
    
    def recognize_from_image(self, image_path):
        """
        Reconnaît les visages dans une image fichier
        
        Args:
            image_path: Chemin vers l'image
        
        Returns:
            list: Résultats de reconnaissance pour chaque visage
        """
        image = cv2.imread(str(image_path))
        if image is None:
            return []
        
        # Détecter et aligner les visages
        detected_faces = self.detect_and_align_face(image)
        
        results = []
        for face_info in detected_faces:
            recognition_result = self.recognize_face(face_info["image"])
            recognition_result["bbox"] = face_info["bbox"]
            results.append(recognition_result)
        
        return results
    
    def get_person_info(self, person_id):
        """Récupère les informations d'une personne"""
        return self.persons.get(person_id)
    
    def list_persons(self):
        """Liste toutes les personnes connues"""
        return list(self.persons.values())
    
    def remove_person(self, person_id):
        """Supprime une personne du système"""
        if person_id in self.persons:
            # Supprimer de la base de données
            del self.persons[person_id]
            
            # Supprimer des mappings label-personne
            if person_id in self.person_to_label:
                label = self.person_to_label[person_id]
                del self.person_to_label[person_id]
                if label in self.label_to_person:
                    del self.label_to_person[label]
            
            # Réentraîner le modèle
            self.retrain_model()
            
            print(f"Personne supprimée: {person_id}")
            return True
        
        return False
    
    def get_statistics(self):
        """Retourne les statistiques de reconnaissance"""
        return {
            "total_persons": len(self.persons),
            "total_recognitions": self.recognitions_count,
            "unknown_count": self.unknown_count,
            "recognition_threshold": self.recognition_threshold
        }
    
    def batch_recognize(self, face_images):
        """
        Reconnaît un batch de visages
        
        Args:
            face_images: Liste d'images de visage
        
        Returns:
            list: Résultats pour chaque visage
        """
        return [self.recognize_face(img) for img in face_images]


# Test rapide
if __name__ == "__main__":
    print("Test du reconnaisseur facial...")
    
    recognizer = FaceRecognizer()
    
    # Afficher les statistiques
    stats = recognizer.get_statistics()
    print(f"Statistiques: {stats}")
    
    # Créer une image de test
    test_image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    
    # Tester la reconnaissance
    result = recognizer.recognize_face(test_image)
    print(f"Résultat de reconnaissance: {result}")
    
    # Tester l'ajout d'une personne
    test_person_images = [test_image, test_image.copy()]
    person_id = recognizer.add_person("Test Person", test_person_images)
    
    if person_id:
        print(f"Personne de test ajoutée avec ID: {person_id}")
        
        # Tester la reconnaissance après ajout
        result = recognizer.recognize_face(test_image)
        print(f"Résultat après ajout: {result}")
    
    # Sauvegarder le modèle
    recognizer.save_model()
