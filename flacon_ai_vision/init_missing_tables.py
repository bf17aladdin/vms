#!/usr/bin/env python3
"""Initialize database tables"""

import sqlite3
from pathlib import Path

# Find the database file
db_file = Path("c:\\Users\\boufm\\Desktop\\eye_of_falcon\\falcon-ai-vision\\falcon_ai_vision.db")
print(f"Using database: {db_file}")

conn = sqlite3.connect(str(db_file))
cursor = conn.cursor()

# Create vehicle_registry table if not exists
print("\nCreating vehicle_registry table...")
cursor.execute("""
CREATE TABLE IF NOT EXISTS vehicle_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_vehicule VARCHAR(50) NOT NULL DEFAULT 'inconnu',
    marque_modele VARCHAR(50) NOT NULL,
    immatriculation VARCHAR(20) UNIQUE NOT NULL,
    numero_serie VARCHAR(50) UNIQUE,
    couleur VARCHAR(30),
    proprietaire VARCHAR(100) NOT NULL,
    nom_conducteur VARCHAR(100),
    etat VARCHAR(50) NOT NULL DEFAULT 'actif',
    photo_path VARCHAR(255),
    allowed_zones JSON,
    authorized_hours_start VARCHAR(5) DEFAULT '06:00',
    authorized_hours_end VARCHAR(5) DEFAULT '22:00',
    is_flagged BOOLEAN DEFAULT 0,
    flag_reason VARCHAR(255),
    date_enregistrement TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    date_modification TIMESTAMP,
    notes TEXT,
    last_entry TIMESTAMP,
    last_exit TIMESTAMP,
    total_entries_today INTEGER DEFAULT 0
)
""")
print("✓ vehicle_registry table created")

# Create vehicle_entries table if not exists
print("\nCreating vehicle_entries table...")
cursor.execute("""
CREATE TABLE IF NOT EXISTS vehicle_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_registry_id INTEGER,
    license_plate VARCHAR(50) NOT NULL,
    vehicle_type VARCHAR(50),
    brand VARCHAR(100),
    model VARCHAR(100),
    color VARCHAR(50),
    entry_camera_id INTEGER NOT NULL,
    exit_camera_id INTEGER,
    entry_time TIMESTAMP NOT NULL,
    exit_time TIMESTAMP,
    entry_confidence FLOAT DEFAULT 0.0,
    exit_confidence FLOAT,
    duration_minutes INTEGER,
    status VARCHAR(20) DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY(vehicle_registry_id) REFERENCES vehicle_registry(id)
)
""")
print("✓ vehicle_entries table created")

# Create indexes
print("\nCreating indexes...")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_registry_immatriculation ON vehicle_registry(immatriculation)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_registry_type ON vehicle_registry(type_vehicule)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_registry_etat ON vehicle_registry(etat)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_entries_license_plate ON vehicle_entries(license_plate)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_vehicle_entries_status ON vehicle_entries(status)")
print("✓ Indexes created")

conn.commit()
conn.close()

print("\n✅ Database tables initialized successfully!")
