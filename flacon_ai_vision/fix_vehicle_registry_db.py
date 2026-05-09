#!/usr/bin/env python3
"""
Script pour corriger le schéma de la table vehicle_registry
avec les nouveaux attributs harmonisés en français:
- matricule: plaque d'immatriculation unique
- marque, modele: marque et modèle du véhicule
- couleur: couleur du véhicule
- categorie: "civil" ou "militaire"
- unite: unité militaire (optionnelle, pour militaire seulement)
- statut: "actif", "hors_service", "maintenance"
- date_enregistrement, date_modification: timestamps
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# Ajouter le chemin backend
sys.path.insert(0, str(Path(__file__).parent / "vms" / "backend"))

from sqlalchemy import create_engine, text
from core.config import settings

print("=" * 80)
print("CORRECTION SCHÉMA VEHICLE_REGISTRY")
print("=" * 80)

# Créer le moteur de base de données
engine = create_engine(settings.DATABASE_URL, echo=False)

try:
    with engine.connect() as connection:
        # Vérifier la base de données existante
        print("\n1. Vérification de la table existante...")
        try:
            result = connection.execute(text("PRAGMA table_info(vehicle_registry)"))
            columns = result.fetchall()
            print(f"   ✓ Table vehicle_registry trouvée avec {len(columns)} colonnes")
            print("   Colonnes actuelles:")
            for col in columns:
                print(f"      - {col[1]}: {col[2]}")
        except Exception as e:
            print(f"   ✗ Erreur: {e}")

        # Supprimer la table existante
        print("\n2. Suppression de la table existante...")
        try:
            connection.execute(text("DROP TABLE IF EXISTS vehicle_registry"))
            connection.commit()
            print("   ✓ Table supprimée avec succès")
        except Exception as e:
            print(f"   ✗ Erreur: {e}")
            raise

        # Créer la nouvelle table avec le nouveau schéma
        print("\n3. Création de la nouvelle table...")
        create_table_sql = """
        CREATE TABLE vehicle_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matricule VARCHAR(20) UNIQUE NOT NULL,
            marque VARCHAR(50) NOT NULL,
            modele VARCHAR(50) NOT NULL,
            couleur VARCHAR(30),
            categorie VARCHAR(50) DEFAULT 'civil' NOT NULL,
            unite VARCHAR(100),
            statut VARCHAR(50) DEFAULT 'actif' NOT NULL,
            date_enregistrement DATETIME DEFAULT CURRENT_TIMESTAMP,
            date_modification DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
        
        try:
            connection.execute(text(create_table_sql))
            connection.commit()
            print("   ✓ Nouvelle table créée avec succès")
        except Exception as e:
            print(f"   ✗ Erreur création: {e}")
            raise

        # Créer les index pour ameliorer les performances
        print("\n4. Création des index...")
        index_sqls = [
            "CREATE INDEX idx_vehicle_matricule ON vehicle_registry(matricule)",
            "CREATE INDEX idx_vehicle_categorie ON vehicle_registry(categorie)",
            "CREATE INDEX idx_vehicle_statut ON vehicle_registry(statut)",
            "CREATE INDEX idx_vehicle_date_enregistrement ON vehicle_registry(date_enregistrement)",
        ]
        
        for idx_sql in index_sqls:
            try:
                connection.execute(text(idx_sql))
                connection.commit()
            except Exception as e:
                if "already exists" in str(e):
                    print(f"   ℹ Index already exists: {idx_sql.split('ON')[0].strip()}")
                else:
                    print(f"   ✗ Index error: {e}")

        # Insérer quelques données de test
        print("\n5. Insertion de données de test...")
        test_vehicles = [
            ("MB2024001", "Mercedes", "G-Class", "Vert militaire", "militaire", "Base Navale", "actif"),
            ("BM2024001", "BMW", "X5", "Noir", "civil", None, "actif"),
            ("TOY2024001", "Toyota", "Land Cruiser", "Blanc", "militaire", "Commando", "actif"),
            ("NO2024001", "Nissan", "Patrol", "Gris", "militaire", "Base Navale", "maintenance"),
        ]
        
        for vehicle in test_vehicles:
            try:
                sql = """
                INSERT INTO vehicle_registry 
                (matricule, marque, modele, couleur, categorie, unite, statut)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                connection.execute(text(sql), [vehicle])
                connection.commit()
                print(f"   ✓ Véhicule inséré: {vehicle[0]} ({vehicle[4]})")
            except Exception as e:
                print(f"   ✗ Erreur insertion {vehicle[0]}: {e}")

        # Afficher les données
        print("\n6. Vérification des données...")
        result = connection.execute(text("SELECT * FROM vehicle_registry"))
        vehicles = result.fetchall()
        print(f"   Total de véhicules: {len(vehicles)}")
        for v in vehicles:
            print(f"   - {v[1]} ({v[5]}): {v[2]} {v[3]}")

        # Afficher le schéma final
        print("\n7. Schéma final de la table...")
        result = connection.execute(text("PRAGMA table_info(vehicle_registry)"))
        columns = result.fetchall()
        for col in columns:
            col_id, col_name, col_type, notnull, dflt_value, pk = col
            print(f"   [{col_id}] {col_name}: {col_type}" + 
                  (f" NOT NULL" if notnull else "") +
                  (f" PK" if pk else "") +
                  (f" DEFAULT {dflt_value}" if dflt_value else ""))

        print("\n" + "=" * 80)
        print("✓ CORRECTION SCHÉMA TERMINÉE AVEC SUCCÈS")
        print("=" * 80)

except Exception as e:
    print(f"\n❌ ERREUR FATALE: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    engine.dispose()
