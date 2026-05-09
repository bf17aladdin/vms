# vms/backend/seed_db.py - Initialiser la base de données avec des données de test

from sqlalchemy.orm import Session
from .core.database import SessionLocal, engine
from . import models, crud, schemas
from .core.security import hash_password
from datetime import datetime, timedelta
import json

def seed_database():
    """Initialiser la base de données avec des données de test"""
    
    # Créer les tables
    models.Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    try:
        # Vérifier si les données existent déjà
        existing_user = db.query(models.User).filter(models.User.username == "admin").first()
        if existing_user:
            print("✓ Database already seeded. Skipping...")
            return
        
        print("[*] Seeding database...")
        
        # ============= CRÉER LES UTILISATEURS =============
        print("\n[*] Creating admin user...")
        admin_user = models.User(
            username="admin",
            email="admin@falcon-aivision.local",
            full_name="Administrator",
            hashed_password=hash_password("admin123"),
            is_active=True,
            is_admin=True
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)
        print(f"  ✓ Admin user created (ID: {admin_user.id})")
        
        print("[*] Creating test user...")
        test_user = models.User(
            username="testuser",
            email="test@falcon-aivision.local",
            full_name="Test User",
            hashed_password=hash_password("test1234"),
            is_active=True,
            is_admin=False
        )
        db.add(test_user)
        db.commit()
        db.refresh(test_user)
        print(f"  ✓ Test user created (ID: {test_user.id})")
        
        # ============= CRÉER LES CAMÉRAS =============
        print("\n[*] Creating cameras...")
        
        cameras_data = [
            {
                "name": "Main Entrance",
                "description": "Front door monitoring",
                "location": "Building A - Entrance",
                "zone_name": "Building A",
                "ip_address": "192.168.1.100",
                "rtsp_url": "rtsp://192.168.1.100:554/stream1",
                "latitude": 48.8566,
                "longitude": 2.3522,
                "is_active": True,
                "ai_model": "yolov8",
                "ai_enabled": True,
                "owner_id": admin_user.id
            },
            {
                "name": "Back Door",
                "description": "Back exit monitoring",
                "location": "Building A - Back",
                "zone_name": "Building A",
                "ip_address": "192.168.1.101",
                "rtsp_url": "rtsp://192.168.1.101:554/stream1",
                "latitude": 48.8550,
                "longitude": 2.3500,
                "is_active": True,
                "ai_model": "yolov8",
                "ai_enabled": True,
                "owner_id": admin_user.id
            },
            {
                "name": "Parking Lot",
                "description": "Vehicle monitoring",
                "location": "Parking Area",
                "zone_name": "Parking",
                "ip_address": "192.168.1.102",
                "rtsp_url": "rtsp://192.168.1.102:554/stream1",
                "latitude": 48.8580,
                "longitude": 2.3540,
                "is_active": True,
                "ai_model": "yolov8",
                "ai_enabled": True,
                "owner_id": admin_user.id
            },
            {
                "name": "Reception Area",
                "description": "Reception room monitoring",
                "location": "Building B - Reception",
                "zone_name": "Building B",
                "ip_address": "192.168.1.103",
                "rtsp_url": "rtsp://192.168.1.103:554/stream1",
                "latitude": 48.8570,
                "longitude": 2.3510,
                "is_active": True,
                "ai_model": "yolov8",
                "ai_enabled": False,
                "owner_id": test_user.id
            }
        ]
        
        cameras = []
        for cam_data in cameras_data:
            camera = models.Camera(**cam_data)
            db.add(camera)
            db.commit()
            db.refresh(camera)
            cameras.append(camera)
            print(f"  ✓ Camera created: {camera.name} (ID: {camera.id})")
        
        # ============= CRÉER LES ZONES =============
        print("\n[*] Creating detection zones...")
        
        zones_data = [
            {
                "camera_id": cameras[0].id,
                "name": "Main Door Zone",
                "description": "Zone around main door",
                "points": [[0, 0], [100, 0], [100, 100], [0, 100]],
                "is_active": True,
                "sensitivity": 60
            },
            {
                "camera_id": cameras[1].id,
                "name": "Back Door Zone",
                "description": "Zone around back door",
                "points": [[0, 0], [50, 0], [50, 50], [0, 50]],
                "is_active": True,
                "sensitivity": 70
            },
            {
                "camera_id": cameras[2].id,
                "name": "Parking Zone",
                "description": "Entire parking area",
                "points": [[0, 0], [200, 0], [200, 150], [0, 150]],
                "is_active": True,
                "sensitivity": 50
            }
        ]
        
        zones = []
        for zone_data in zones_data:
            zone = models.Zone(**zone_data)
            db.add(zone)
            db.commit()
            db.refresh(zone)
            zones.append(zone)
            print(f"  ✓ Zone created: {zone.name} (ID: {zone.id})")
        
        # ============= CRÉER DES ÉVÉNEMENTS TEST =============
        print("\n[*] Creating test events...")
        
        events_data = [
            {
                "camera_id": cameras[0].id,
                "zone_id": zones[0].id,
                "creator_id": admin_user.id,
                "event_type": "motion",
                "severity": "info",
                "description": "Motion detected at main entrance",
                "confidence": 0.92,
                "detected_objects": {"person": 2, "backpack": 1},
                "detected_at": datetime.now() - timedelta(hours=2),
                "extra_data": None
            },
            {
                "camera_id": cameras[0].id,
                "zone_id": zones[0].id,
                "creator_id": admin_user.id,
                "event_type": "object",
                "severity": "warning",
                "description": "Person detected with suspicious object",
                "confidence": 0.85,
                "detected_objects": {"person": 1, "gun": 0},
                "detected_at": datetime.now() - timedelta(hours=1)
            },
            {
                "camera_id": cameras[2].id,
                "zone_id": zones[2].id,
                "creator_id": admin_user.id,
                "event_type": "vehicle",
                "severity": "info",
                "description": "Vehicle detected in parking",
                "confidence": 0.95,
                "detected_objects": {"car": 1},
                "detected_at": datetime.now() - timedelta(minutes=30)
            },
            {
                "camera_id": cameras[1].id,
                "zone_id": zones[1].id,
                "creator_id": test_user.id,
                "event_type": "motion",
                "severity": "critical",
                "description": "Unusual motion at back door",
                "confidence": 0.78,
                "detected_objects": {"person": 1},
                "detected_at": datetime.now() - timedelta(minutes=5),
                "is_acknowledged": False
            }
        ]
        
        events = []
        for event_data in events_data:
            event = models.Event(**event_data)
            db.add(event)
            db.commit()
            db.refresh(event)
            events.append(event)
            print(f"  ✓ Event created: {event.event_type} (ID: {event.id})")
        
        # ============= CRÉER DES RÈGLES D'ALERTE =============
        print("\n[*] Creating alert rules...")
        
        alert_rules = [
            {
                "name": "Person Detected Alert",
                "description": "Alert when person is detected",
                "event_type": "person",
                "camera_id": None,
                "min_confidence": 0.8,
                "enable_notification": True,
                "enable_recording": True,
                "is_active": True
            },
            {
                "name": "Vehicle Motion Alert",
                "description": "Alert for vehicles in parking",
                "event_type": "vehicle",
                "camera_id": cameras[2].id,
                "min_confidence": 0.85,
                "enable_notification": True,
                "enable_recording": True,
                "enable_alert_sound": True,
                "is_active": True
            }
        ]
        
        for rule_data in alert_rules:
            rule = models.AlertRule(**rule_data)
            db.add(rule)
            db.commit()
            db.refresh(rule)
            print(f"  ✓ Alert rule created: {rule.name} (ID: {rule.id})")
        
        # ============= CRÉER DES VÉHICULES =============
        print("\n[*] Creating vehicle records...")
        
        if events:
            vehicle = models.Vehicle(
                event_id=events[2].id,
                camera_id=cameras[2].id,
                license_plate="ABC123DE",
                vehicle_type="car",
                color="silver",
                brand="Toyota",
                model="Prius",
                confidence=0.95,
                direction="north",
                speed=25.5,
                detected_at=events[2].detected_at,
                bounding_box={"x": 50, "y": 60, "width": 80, "height": 120}
            )
            db.add(vehicle)
            db.commit()
            db.refresh(vehicle)
            print(f"  ✓ Vehicle record created: {vehicle.license_plate} (ID: {vehicle.id})")
        
        print("\n[✓] Database seeding completed successfully!")
        print(f"\n[*] Created:")
        print(f"  - 2 Users")
        print(f"  - 4 Cameras")
        print(f"  - 3 Detection Zones")
        print(f"  - 4 Events")
        print(f"  - 2 Alert Rules")
        print(f"  - 1 Vehicle Record")
        
    except Exception as e:
        print(f"\n[!] Error seeding database: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
