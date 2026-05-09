#!/usr/bin/env python3
# vms/backend/database_info.py - Information et statistiques BD

from sqlalchemy import inspect, text
from core.database import engine, SessionLocal
import models
import json

def get_table_info():
    """Obtenir les infos sur toutes les tables"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    info = {}
    for table_name in tables:
        columns = inspector.get_columns(table_name)
        primary_keys = inspector.get_pk_constraint(table_name)
        foreign_keys = inspector.get_foreign_keys(table_name)
        indexes = inspector.get_indexes(table_name)
        
        info[table_name] = {
            "columns": [col["name"] for col in columns],
            "primary_key": primary_keys.get("constrained_columns", []),
            "foreign_keys": foreign_keys,
            "indexes": [idx["name"] for idx in indexes],
            "column_count": len(columns),
            "column_details": [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col["nullable"],
                    "default": str(col.get("default", "None"))
                }
                for col in columns
            ]
        }
    
    return info

def get_row_counts():
    """Obtenir le nombre de lignes dans chaque table"""
    db = SessionLocal()
    counts = {}
    
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    for table_name in tables:
        try:
            result = db.execute(text(f"SELECT COUNT(*) as count FROM {table_name}"))
            count = result.scalar()
            counts[table_name] = count
        except Exception as e:
            counts[table_name] = f"Error: {str(e)}"
    
    db.close()
    return counts

def print_database_summary():
    """Afficher un résumé de la base de données"""
    print("\n" + "="*80)
    print(" DATABASE SUMMARY - Falcon AI Vision")
    print("="*80 + "\n")
    
    # Tables
    info = get_table_info()
    print(f"[*] Tables: {len(info)}\n")
    
    for table_name, details in info.items():
        print(f"  📋 {table_name.upper()}")
        print(f"     Columns: {details['column_count']}")
        print(f"     Fields: {', '.join(details['columns'][:4])}...")
        if details['foreign_keys']:
            print(f"     Foreign Keys: {len(details['foreign_keys'])}")
        print()
    
    # Row counts
    counts = get_row_counts()
    print("\n[*] Row Counts:\n")
    
    total_rows = 0
    for table_name, count in counts.items():
        print(f"  {table_name:<20} : {count} rows")
        if isinstance(count, int):
            total_rows += count
    
    print(f"\n  {'TOTAL':<20} : {total_rows} rows")
    
    # Stats
    print("\n[*] Statistics:\n")
    print(f"  Database Type    : SQLite")
    print(f"  File             : vms/backend/falcon_ai_vision.db")
    print(f"  Total Tables     : {len(info)}")
    print(f"  Total Records    : {total_rows}")
    print(f"  Average Records  : {total_rows // len(info)}")
    
    print("\n" + "="*80 + "\n")

def export_schema_info():
    """Exporter les infos de schéma en JSON"""
    info = get_table_info()
    counts = get_row_counts()
    
    schema_info = {
        "database": "Falcon AI Vision",
        "type": "SQLite",
        "tables": info,
        "row_counts": counts,
        "total_tables": len(info),
        "total_rows": sum([c for c in counts.values() if isinstance(c, int)])
    }
    
    return schema_info

if __name__ == "__main__":
    print_database_summary()
    
    # Optionally export as JSON
    import os
    json_path = os.path.join(os.path.dirname(__file__), "database_schema.json")
    with open(json_path, "w") as f:
        json.dump(export_schema_info(), f, indent=2, default=str)
    print(f"[✓] Schema exported to: {json_path}\n")
