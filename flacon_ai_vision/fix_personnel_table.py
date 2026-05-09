#!/usr/bin/env python3
"""Fix Personnel table schema"""

import sqlite3
from pathlib import Path

# Find the database file
db_paths = list(Path("c:\\Users\\boufm\\Desktop\\eye_of_falcon\\falcon-ai-vision").glob("*.db"))
print(f"Found {len(db_paths)} database files:")
for db_path in db_paths:
    print(f"  - {db_path.name}")

if not db_paths:
    print("No database files found!")
    exit(1)

# Use the first one (usually falcon_ai_vision.db)
db_file = db_paths[0]
print(f"\nUsing database: {db_file}")

conn = sqlite3.connect(str(db_file))
cursor = conn.cursor()

# Check if personnel table exists
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='personnel'")
table_exists = cursor.fetchone()

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
    print("✗ Table 'personnel' does not exist")

# Check vehicle_registry table
print("\n" + "="*60)
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicle_registry'")
table_exists = cursor.fetchone()

if table_exists:
    print("✓ Table 'vehicle_registry' exists")
    cursor.execute("PRAGMA table_info(vehicle_registry)")
    columns = cursor.fetchall()
    print(f"  Columns: {len(columns)}")
else:
    print("✗ Table 'vehicle_registry' does not exist")

conn.close()
print("\n✅ Database check complete!")
