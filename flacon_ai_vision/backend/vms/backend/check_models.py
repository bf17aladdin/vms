# vms/backend/check_models.py - Vérifier les modèles SQLAlchemy

import sys
import os

# Ajouter le chemin du backend
sys.path.insert(0, os.path.dirname(__file__))

try:
    print("[*] Checking SQLAlchemy models...\n")
    
    # Importer les modèles
    from . import models
    from .core.database import Base
    
    print("[✓] Models imported successfully\n")
    
    # Lister les modèles
    print("[*] Available models:")
    print("=" * 60)
    
    for name in dir(models):
        obj = getattr(models, name)
        # Vérifier si c'est une classe et pas une importation
        if isinstance(obj, type) and hasattr(obj, '__tablename__'):
            print(f"  ✓ {name:<20} (table: {obj.__tablename__})")
            
            # Afficher les colonnes
            if hasattr(obj, '__table__'):
                columns = [col.name for col in obj.__table__.columns]
                print(f"    Columns: {', '.join(columns[:3])}...")
    
    print("\n" + "=" * 60)
    print("[✓] All models loaded successfully!")
    
except ImportError as e:
    print(f"[!] Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[!] Error: {e}")
    sys.exit(1)
