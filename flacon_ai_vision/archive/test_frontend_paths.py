#!/usr/bin/env python
"""
Script de diagnostic pour vérifier les chemins du frontend
"""

import os
import sys
from pathlib import Path

# Ajouter le répertoire vms au chemin Python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vms"))

# Importer les settings
from backend.core.config import settings

print("=" * 60)
print("[*] DIAGNOSTIC DE CONFIGURATION - FRONTEND PATHS")
print("=" * 60)

# Test des chemins
paths_to_test = {
    "FRONTEND_PATH": settings.FRONTEND_PATH,
    "TEMPLATES_PATH": settings.TEMPLATES_PATH,
    "STATIC_PATH": settings.STATIC_PATH,
    "STORAGE_PATH": settings.STORAGE_PATH,
}

print("\n📂 Chemins configurés:")
for name, path in paths_to_test.items():
    exists = os.path.exists(path)
    status = "✅ EXISTE" if exists else "❌ MANQUANT"
    print(f"  {name:20} : {path}")
    print(f"  {'':<20}   {status}")

# Test des fichiers spécifiques attendus
print("\n📄 Fichiers clés attendus:")
key_files = {
    "index.html (root)": os.path.join(settings.FRONTEND_PATH, "index.html"),
    "login.html": os.path.join(settings.TEMPLATES_PATH, "login.html"),
    "admin/index.html": os.path.join(settings.FRONTEND_PATH, "admin", "index.html"),
    "user/index.html": os.path.join(settings.FRONTEND_PATH, "user", "index.html"),
}

for name, path in key_files.items():
    exists = os.path.exists(path)
    status = "✅ EXISTE" if exists else "❌ MANQUANT"
    print(f"  {name:25} : {exists:5} {status}")

# Lister le contenu du répertoire FRONTEND_PATH
print(f"\n📁 Contenu de FRONTEND_PATH ({settings.FRONTEND_PATH}):")
try:
    items = sorted(os.listdir(settings.FRONTEND_PATH))
    for item in items:
        item_path = os.path.join(settings.FRONTEND_PATH, item)
        if os.path.isdir(item_path):
            print(f"  📁 {item}/")
        else:
            print(f"  📄 {item}")
except Exception as e:
    print(f"  ❌ ERREUR: {e}")

# Résumé
print("\n" + "=" * 60)
all_exist = all(os.path.exists(p) for p in paths_to_test.values())
if all_exist:
    print("✅ CONFIGURATION OK - Tous les chemins sont correctement configurés!")
else:
    print("❌ CONFIGURATION INCOMPLÈTE - Vérifiez les chemins ci-dessus")
print("=" * 60)
