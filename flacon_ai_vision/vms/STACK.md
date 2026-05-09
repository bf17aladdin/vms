# Stack technique (vms)

Ce document liste la stack exacte utilisée par le dossier `vms/` et les dépendances recommandées, y compris les options ia.

## Dépendances principales (déjà dans `requirements.txt`)
- fastapi==0.104.1
- uvicorn[standard]==0.24.0
- sqlalchemy==2.0.23
- pydantic==2.5.0
- python-jose[cryptography]==3.3.0
- passlib[bcrypt]==1.7.4
- bcrypt==4.1.1
- websockets==12.0
- requests==2.31.0
- python-multipart==0.0.6

## Dépendances optionnelles pour AI/ML
Ces paquets ne sont pas obligatoires pour exécuter l'API, mais nécessaires pour activer la détection et la reconnaissance réelles.

- numpy (requis par OpenCV/face libs)
- opencv-python==4.8.1.78  # lecture et traitement images/vidéo
- face-recognition (dépend de dlib) -> pour encodages et matching de visages
- dlib (compilation lourde, préférer wheels précompilés selon plateforme)
- ultralytics==8.0.207  # YOLOv8 pour détection d'objets/vehicules

## Commandes d'installation recommandées
1. Environnement virtuel (Windows PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

2. Installer les dépendances AI (optionnel, Linux/Win/Mac diffèrent):
- Option A (face_recognition via wheel / conda):
  - Recommandé: utiliser conda pour `dlib` et `face_recognition` :
```bash
conda create -n vms python=3.9 -y
conda activate vms
conda install -c conda-forge dlib opencv numpy -y
pip install face-recognition
pip install ultralytics
```

- Option B (pip, Windows):
  - Installer wheels précompilés pour `dlib` (si disponible) puis:
```bash
pip install opencv-python numpy
pip install dlib-<version>-cpXX‑win_amd64.whl
pip install face_recognition
pip install ultralytics
```

3. Vérifier l'installation AI minimale (exécuter en Python):
```python
import cv2
import numpy as np
try:
    import face_recognition
    print('face_recognition OK')
except Exception as e:
    print('face_recognition missing or failed:', e)

try:
    import ultralytics
    print('ultralytics OK')
except Exception as e:
    print('ultralytics missing or failed:', e)
```

## Notes d'intégration
- `face_recognition` fournit `face_locations`, `face_encodings`, `face_distance` et `compare_faces`.
- Le module `vms/facial_recognition/face_recognizer.py` bascule vers `face_recognition` si disponible, sinon fonctionne en mode dégradé (placeholders).
- Pour la production, préférez installer `dlib` via conda ou wheel afin d'éviter compilation longue.
- `ultralytics` (YOLOv8) nécessite des ressources GPU pour de bonnes performances ; en CPU la détection reste possible mais plus lente.

## Versions recommandées (compatibilité testée lors de la session)
- Python: 3.8 - 3.11 (préférer 3.10)
- fastapi 0.104.x
- uvicorn[standard] 0.24.x
- sqlalchemy 2.0.x
- face_recognition: dernière stable compatible avec dlib wheel
- ultralytics: 8.x

## Emplacement des fichiers importants
- `vms/backend/main.py` - point d'entrée FastAPI
- `vms/backend/services/face_ai/face_pipeline.py` - pipeline facial unifié utilisé par les routes backend
- `vms/frontend/src/services/api.ts` - client API unifié utilisé par le frontend React
- `vms/facial_recognition/face_recognizer.py` - implémentation (face_recognition si disponible)
- `vms/facial_recognition/face_detector.py` - détection (OpenCV)
- Dossiers de données: `data/known_faces`, `data/unknown_faces`

---

Si vous voulez, je peux :
- ajouter un `requirements-ia.txt` avec les versions recommandées pour l'IA,
- ou tenter une installation automatique (conda/pip) sur votre machine.
