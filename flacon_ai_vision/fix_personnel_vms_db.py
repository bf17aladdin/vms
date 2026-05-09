#!/usr/bin/env python3
"""Fix Personnel table schema in vms.db"""

import sqlite3
from pathlib import Path

# Use the correct database path
db_file = Path("c:\\Users\\boufm\\Desktop\\eye_of_falcon\\falcon-ai-vision\\vms\\backend\\data\\vms.db")
print(f"Using database: {db_file}")

# Ensure directory exists
db_file.parent.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(str(db_file))
cursor = conn.cursor()

# Check if personnel table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personnel'")
table_exists = cursor.fetchone()

print("\n" + "="*60)
print("PERSONNEL TABLE")
print("="*60)

if table_exists:
    print("✓ Table 'personnel' exists")
    
    # Get table schema
    cursor.execute("PRAGMA table_info(personnel)")
    columns = cursor.fetchall()
    
    print("\nCurrent columns:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    col_names = [col[1] for col in columns]
    
    # Check for required columns
    required_cols = ['nom', 'prenom', 'cin', 'num_recrutement', 'categorie', 'grade']
    missing_cols = [col for col in required_cols if col not in col_names]
    
    if missing_cols:
        print(f"\n⚠️  Missing columns: {missing_cols}")
        print("\nRecreating personnel table...")
        
        # Drop old table
        cursor.execute("DROP TABLE IF EXISTS personnel")
        print("  - Old table dropped")
        
        # Create new table with correct schema
        cursor.execute("""
        CREATE TABLE personnel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom VARCHAR(50) NOT NULL,
            prenom VARCHAR(50) NOT NULL,
            full_name VARCHAR(100) NOT NULL,
            cin VARCHAR(20) UNIQUE NOT NULL,
            cin_expiry TIMESTAMP,
            num_recrutement VARCHAR(20) UNIQUE NOT NULL,
            categorie VARCHAR(50) NOT NULL DEFAULT 'soldat',
            grade VARCHAR(50) NOT NULL,
            "unité" VARCHAR(100),
            gender VARCHAR(20),
            email VARCHAR(100) UNIQUE,
            telephone VARCHAR(20),
            photo_path VARCHAR(255),
            face_encodings JSON,
            allowed_camera_ids JSON,
            authorized_hours_start VARCHAR(5) DEFAULT '06:00',
            authorized_hours_end VARCHAR(5) DEFAULT '22:00',
            is_active BOOLEAN DEFAULT 1,
            is_blacklisted BOOLEAN DEFAULT 0,
            blacklist_reason VARCHAR(255),
            last_entry TIMESTAMP,
            last_exit TIMESTAMP,
            total_entries_today INTEGER DEFAULT 0,
            date_enregistrement TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            date_modification TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            notes TEXT
        )
        """)
        print("  - New table created with correct schema")
        
        # Create indexes
        cursor.execute("CREATE INDEX idx_personnel_nom ON personnel(nom)")
        cursor.execute("CREATE INDEX idx_personnel_cin ON personnel(cin)")
        cursor.execute("CREATE INDEX idx_personnel_num_recrutement ON personnel(num_recrutement)")
        cursor.execute("CREATE INDEX idx_personnel_categorie ON personnel(categorie)")
        cursor.execute("CREATE INDEX idx_personnel_is_active ON personnel(is_active)")
        cursor.execute("CREATE INDEX idx_personnel_is_blacklisted ON personnel(is_blacklisted)")
        print("  - Indexes created")
        
        conn.commit()
        print("\n✅ Personnel table recreated successfully!")
    else:
        print("\n✅ All required columns present!")
else:
    print("✗ Table 'personnel' does not exist - creating...")
    
    cursor.execute("""
    CREATE TABLE personnel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom VARCHAR(50) NOT NULL,
        prenom VARCHAR(50) NOT NULL,
        full_name VARCHAR(100) NOT NULL,
        cin VARCHAR(20) UNIQUE NOT NULL,
        cin_expiry TIMESTAMP,
        num_recrutement VARCHAR(20) UNIQUE NOT NULL,
        categorie VARCHAR(50) NOT NULL DEFAULT 'soldat',
        grade VARCHAR(50) NOT NULL,
        "unité" VARCHAR(100),
        gender VARCHAR(20),
        email VARCHAR(100) UNIQUE,
        telephone VARCHAR(20),
        photo_path VARCHAR(255),
        face_encodings JSON,
        allowed_camera_ids JSON,
        authorized_hours_start VARCHAR(5) DEFAULT '06:00',
        authorized_hours_end VARCHAR(5) DEFAULT '22:00',
        is_active BOOLEAN DEFAULT 1,
        is_blacklisted BOOLEAN DEFAULT 0,
        blacklist_reason VARCHAR(255),
        last_entry TIMESTAMP,
        last_exit TIMESTAMP,
        total_entries_today INTEGER DEFAULT 0,
        date_enregistrement TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        date_modification TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP,
        notes TEXT
    )
    """)
    print("✓ personnel table created")
    
    # Create indexes
    cursor.execute("CREATE INDEX idx_personnel_nom ON personnel(nom)")
    cursor.execute("CREATE INDEX idx_personnel_cin ON personnel(cin)")
    cursor.execute("CREATE INDEX idx_personnel_num_recrutement ON personnel(num_recrutement)")
    cursor.execute("CREATE INDEX idx_personnel_categorie ON personnel(categorie)")
    cursor.execute("CREATE INDEX idx_personnel_is_active ON personnel(is_active)")
    cursor.execute("CREATE INDEX idx_personnel_is_blacklisted ON personnel(is_blacklisted)")
    print("✓ Indexes created")
    
    conn.commit()
    print("\n✅ Personnel table created successfully!")

# Check vehicle_registry table
print("\n" + "="*60)
print("VEHICLE_REGISTRY TABLE")
print("="*60)

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_registry'")
table_exists = cursor.fetchone()

if table_exists:
    print("✓ Table 'vehicle_registry' exists")
else:
    print("✗ Table 'vehicle_registry' does not exist - creating...")
    
    cursor.execute("""
    CREATE TABLE vehicle_registry (
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
    
    # Create indexes
    cursor.execute("CREATE INDEX idx_vehicle_registry_immatriculation ON vehicle_registry(immatriculation)")
    cursor.execute("CREATE INDEX idx_vehicle_registry_type ON vehicle_registry(type_vehicule)")
    cursor.execute("CREATE INDEX idx_vehicle_registry_etat ON vehicle_registry(etat)")
    print("✓ Indexes created")
    
    conn.commit()
    print("\n✅ Vehicle_registry table created successfully!")

# Check vehicle_entries table
print("\n" + "="*60)
print("VEHICLE_ENTRIES TABLE")
print("="*60)

cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_entries'")
table_exists = cursor.fetchone()

if table_exists:
    print("✓ Table 'vehicle_entries' exists")
else:
    print("✗ Table 'vehicle_entries' does not exist - creating...")
    
    cursor.execute("""
    CREATE TABLE vehicle_entries (
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
    cursor.execute("CREATE INDEX idx_vehicle_entries_license_plate ON vehicle_entries(license_plate)")
    cursor.execute("CREATE INDEX idx_vehicle_entries_status ON vehicle_entries(status)")
    print("✓ Indexes created")
    
    conn.commit()
    print("\n✅ Vehicle_entries table created successfully!")

conn.close()
print("\n" + "="*60)
print("✅ DATABASE INITIALIZATION COMPLETE!")
print("="*60 + "\n")
