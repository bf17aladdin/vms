import cv2
import numpy as np
from pathlib import Path
import time

class FaceDetector:
    """Détecteur de visages utilisant OpenCV DNN avec SSD"""
    
    def __init__(self, model_dir=None, confidence_threshold=0.5):
        """
        Initialise le détecteur de visages
        
        Args:
            model_dir: Chemin vers les fichiers de modèle
            confidence_threshold: Seuil de confiance minimum
        """
        if model_dir is None:
            # Chemin par défaut relatif au projet
            project_root = Path(__file__).resolve().parent.parent.parent
            model_dir = project_root / "models" / "face_recognition"
        
        self.model_dir = Path(model_dir)
        self.confidence_threshold = confidence_threshold
        
        # Chemins des fichiers de modèle
        self.model_file = self.model_dir / "res10_300x300_ssd_iter_140000_fp16.caffemodel"
        self.config_file = self.model_dir / "deploy.prototxt"
        
        # Vérifier l'existence des fichiers
        if not self.model_file.exists():
            raise FileNotFoundError(f"Fichier modèle manquant: {self.model_file}")
        if not self.config_file.exists():
            raise FileNotFoundError(f"Fichier configuration manquant: {self.config_file}")
        
        # Charger le réseau de neurones
        print(f"Chargement du modèle de détection depuis: {self.model_dir}")
        self.net = cv2.dnn.readNetFromCaffe(str(self.config_file), str(self.model_file))
        
        # Paramètres du modèle
        self.input_size = (300, 300)
        self.scale_factor = 1.0
        self.mean_values = (104.0, 177.0, 123.0)
        
        # Pour les statistiques
        self.total_faces_detected = 0
        self.processing_times = []
        
        print("✓ Détecteur de visages initialisé")
    
    def detect_faces(self, image, return_image=False):
        """
        Détecte les visages dans une image
        
        Args:
            image: Image numpy array (BGR)
            return_image: Si True, retourne aussi l'image avec les boîtes
        
        Returns:
            dict: Résultats de détection
        """
        start_time = time.time()
        
        # Vérifier l'image
        if image is None or image.size == 0:
            return {"faces": [], "image": image if return_image else None}
        
        (h, w) = image.shape[:2]
        
        # Créer un blob de l'image pour le modèle
        blob = cv2.dnn.blobFromImage(
            cv2.resize(image, self.input_size),
            self.scale_factor,
            self.input_size,
            self.mean_values,
            swapRB=False,
            crop=False
        )
        
        # Passer le blob au réseau
        self.net.setInput(blob)
        detections = self.net.forward()
        
        faces = []
        output_image = image.copy() if return_image else None
        
        # Parcourir les détections
        for i in range(0, detections.shape[2]):
            confidence = detections[0, 0, i, 2]
            
            # Filtrer par seuil de confiance
            if confidence > self.confidence_threshold:
                self.total_faces_detected += 1
                
                # Calculer les coordonnées de la boîte
                box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                (startX, startY, endX, endY) = box.astype("int")
                
                # Assurer que les coordonnées sont dans l'image
                startX = max(0, startX)
                startY = max(0, startY)
                endX = min(w, endX)
                endY = min(h, endY)
                
                # Calculer la largeur et hauteur
                face_width = endX - startX
                face_height = endY - startY
                
                # Vérifier la taille minimale
                if face_width < 20 or face_height < 20:
                    continue
                
                # Extraire la région du visage
                face_region = image[startY:endY, startX:endX]
                
                # Informations du visage
                face_info = {
                    "bbox": (startX, startY, face_width, face_height),
                    "confidence": float(confidence),
                    "region": face_region,
                    "center": (startX + face_width // 2, startY + face_height // 2),
                    "area": face_width * face_height
                }
                
                faces.append(face_info)
                
                # Dessiner sur l'image si demandé
                if return_image and output_image is not None:
                    # Couleur basée sur la confiance
                    color_intensity = int(confidence * 255)
                    color = (0, color_intensity, 255 - color_intensity)
                    
                    # Dessiner le rectangle
                    cv2.rectangle(output_image, (startX, startY), (endX, endY), color, 2)
                    
                    # Ajouter le texte de confiance
                    label = f"{confidence:.1%}"
                    y = startY - 10 if startY - 10 > 10 else startY + 20
                    cv2.putText(output_image, label, (startX, y),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        # Calculer le temps de traitement
        processing_time = time.time() - start_time
        self.processing_times.append(processing_time)
        
        # Garder seulement les 100 derniers temps
        if len(self.processing_times) > 100:
            self.processing_times = self.processing_times[-100:]
        
        result = {
            "faces": faces,
            "count": len(faces),
            "processing_time": processing_time,
            "avg_confidence": np.mean([f["confidence"] for f in faces]) if faces else 0
        }
        
        if return_image:
            result["image"] = output_image
        
        return result
    
    def detect_faces_batch(self, images, batch_size=4):
        """
        Détecte les visages dans un batch d'images
        
        Args:
            images: Liste d'images
            batch_size: Taille du batch
        
        Returns:
            list: Liste des résultats pour chaque image
        """
        results = []
        
        for i in range(0, len(images), batch_size):
            batch = images[i:i + batch_size]
            batch_results = [self.detect_faces(img) for img in batch]
            results.extend(batch_results)
        
        return results
    
    def get_statistics(self):
        """Retourne les statistiques de détection"""
        if not self.processing_times:
            avg_time = 0
        else:
            avg_time = np.mean(self.processing_times)
        
        return {
            "total_faces_detected": self.total_faces_detected,
            "avg_processing_time": avg_time,
            "total_processing_time": sum(self.processing_times)
        }
    
    def draw_faces_on_image(self, image, faces, color=(0, 255, 0), thickness=2):
        """
        Dessine les visages détectés sur une image
        
        Args:
            image: Image d'origine
            faces: Liste des détections de visages
            color: Couleur des boîtes (B, G, R)
            thickness: Épaisseur des lignes
        
        Returns:
            numpy array: Image avec les boîtes
        """
        output_image = image.copy()
        
        for face in faces:
            x, y, w, h = face["bbox"]
            confidence = face["confidence"]
            
            # Dessiner le rectangle
            cv2.rectangle(output_image, (x, y), (x + w, y + h), color, thickness)
            
            # Ajouter le label de confiance
            label = f"{confidence:.1%}"
            y_text = y - 10 if y - 10 > 10 else y + 20
            cv2.putText(output_image, label, (x, y_text),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # Dessiner un point au centre
            center_x, center_y = face["center"]
            cv2.circle(output_image, (center_x, center_y), 3, color, -1)
        
        return output_image
    
    def extract_face_regions(self, image, faces, save_dir=None, prefix=""):
        """
        Extrait les régions de visage de l'image
        
        Args:
            image: Image d'origine
            faces: Liste des détections de visages
            save_dir: Dossier pour sauvegarder les extractions
            prefix: Préfixe pour les noms de fichiers
        
        Returns:
            list: Liste des images de visages extraits
        """
        face_images = []
        
        for i, face in enumerate(faces):
            x, y, w, h = face["bbox"]
            face_image = image[y:y+h, x:x+w]
            
            if face_image.size > 0:
                face_images.append(face_image)
                
                # Sauvegarder si un dossier est spécifié
                if save_dir:
                    save_dir = Path(save_dir)
                    save_dir.mkdir(parents=True, exist_ok=True)
                    
                    filename = f"{prefix}face_{i:03d}_{face['confidence']:.2f}.jpg"
                    filepath = save_dir / filename
                    cv2.imwrite(str(filepath), face_image)
        
        return face_images
    
    def set_confidence_threshold(self, threshold):
        """Modifie le seuil de confiance"""
        self.confidence_threshold = max(0.1, min(0.99, threshold))
        print(f"Seuil de confiance modifié: {self.confidence_threshold}")
    
    def release(self):
        """Libère les ressources"""
        # Pour OpenCV DNN, pas de ressources spécifiques à libérer
        print("Détecteur de visages libéré")


# Test rapide
if __name__ == "__main__":
    print("Test du détecteur de visages...")
    
    # Créer un dossier de test si nécessaire
    test_dir = Path("test_faces")
    test_dir.mkdir(exist_ok=True)
    
    # Créer un détecteur
    try:
        detector = FaceDetector()
        
        # Créer une image de test (noire avec un rectangle blanc simulant un visage)
        test_image = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.rectangle(test_image, (100, 100), (200, 200), (255, 255, 255), -1)
        
        # Détecter les visages
        result = detector.detect_faces(test_image, return_image=True)
        
        print(f"Visages détectés: {result['count']}")
        print(f"Temps de traitement: {result['processing_time']:.3f}s")
        
        # Sauvegarder le résultat
        if result['image'] is not None:
            cv2.imwrite(str(test_dir / "test_detection.jpg"), result['image'])
            print(f"Image de test sauvegardée: {test_dir}/test_detection.jpg")
        
        # Afficher les statistiques
        stats = detector.get_statistics()
        print(f"Statistiques: {stats}")
        
    except FileNotFoundError as e:
        print(f"Erreur: {e}")
        print("Téléchargez les fichiers de modèle:")
        print("1. deploy.prototxt - https://raw.githubusercontent.com/opencv/opencv/master/samples/dnn/face_detector/deploy.prototxt")
        print("2. res10_300x300_ssd_iter_140000_fp16.caffemodel - https://github.com/opencv/opencv_3rdparty/raw/dnn_samples_face_detector_20170830/res10_300x300_ssd_iter_140000_fp16.caffemodel")
    except Exception as e:
        print(f"Erreur: {e}")