#!/usr/bin/env python3
"""Capture webcam image, create personnel, upload photo, call load-face.

Usage: run with the project's venv Python:
  .venv\Scripts\python.exe scripts\capture_and_upload.py --name "Mon Nom"
"""
import os
import sys
import argparse
import tempfile
import time
import subprocess

def ensure_imports():
    try:
        import cv2  # noqa: F401
        import requests  # noqa: F401
    except Exception:
        print("Manque des paquets, installation via pip dans l'env courant...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "opencv-python", "requests"]) 


def capture_image(path: str, width: int = 1280, height: int = 720) -> bool:
    import cv2
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Erreur: impossible d'ouvrir la webcam (index 0)")
        return False
    # Try to set higher resolution
    try:
        cap.set(3, width)
        cap.set(4, height)
    except Exception:
        pass
    print("Positionnez-vous devant la webcam. Capture dans 3 secondes...")
    time.sleep(3)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        print("Erreur capture frame")
        return False
    cv2.imwrite(path, frame)
    print(f"Image capturée: {path}")
    return True


def main():
    ensure_imports()
    import requests

    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5003", help="API base URL")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--name", default="Webcam Test User")
    args = parser.parse_args()

    base = args.base.rstrip('/')

    # Auth
    print("Authentification...")
    r = requests.post(f"{base}/api/auth/login", json={"username": args.username, "password": args.password}, timeout=10)
    r.raise_for_status()
    token = r.json().get('access_token')
    headers = {"Authorization": f"Bearer {token}"}
    print("Token obtenu")

    # Create personnel
    print("Création personnel...")
    body = {"full_name": args.name, "recruitment_id": f"pc_{int(time.time())}", "category": "employee"}
    r = requests.post(f"{base}/api/personnel/", json=body, headers=headers, timeout=10)
    r.raise_for_status()
    person = r.json()
    pid = person.get('id')
    print(f"Personnel créé id={pid}")

    # Try multiple captures + upload attempts
    tries = 3
    success = False
    for attempt in range(1, tries + 1):
        print(f"--- Tentative {attempt}/{tries} ---")
        tmp = tempfile.NamedTemporaryFile(prefix=f'webcam_{attempt}_', suffix='.png', delete=False)
        tmp.close()
        img_path = tmp.name
        ok = capture_image(img_path)
        if not ok:
            print("Échec capture, prochaine tentative")
            continue

        # Upload
        print("Téléversement image...")
        with open(img_path, 'rb') as f:
            files = {'file': (os.path.basename(img_path), f, 'image/png')}
            r = requests.post(f"{base}/api/upload/person-photo", headers=headers, files=files, timeout=30)
        if r.status_code >= 400:
            print("Upload échoué:", r.status_code, r.text)
            continue
        up = r.json()
        print("Upload OK:", up.get('path'))

        # Call load-face (query param)
        print("Appel load-face...")
        params = {'image_path': up.get('path')}
        r = requests.post(f"{base}/api/personnel/{pid}/load-face", headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            print("Encodage facial OK:", r.json())
            success = True
            break
        else:
            print("Encodage facial erreur:", r.status_code, r.text)

    if not success:
        print("Toutes les tentatives ont échoué — essayez d'améliorer l'éclairage et de rapprocher votre visage.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
