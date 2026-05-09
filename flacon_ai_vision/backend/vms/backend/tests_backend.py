#!/usr/bin/env python3
"""
Scripts de test automatisés pour validation backend
Priorité 4: Tests backend avec pytest
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from datetime import datetime
import sys
from pathlib import Path

# Ajouter le chemin au path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vms.backend.models import Base, Personnel, PersonnelCategoryEnum, FaceEncoding, VehicleEntry, VehicleDetection, Zone, ZoneOccupancy
from vms.backend.core.database import get_db, SESSION_LOCAL
from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline
from vms.backend.services.vehicle_service import VehicleService
from vms.backend.services.zone_service import ZoneService


# Fixture: DB session test
@pytest.fixture(scope="session")
def db_session():
    """Créer une session DB de test"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class _DummyDetector:
    backend = "stub_detector"


class _DummyAligner:
    backend = "stub_aligner"


class _DummyEmbedder:
    backend = "stub_embedder"


@pytest.fixture()
def pipeline_factory(monkeypatch):
    """Créer une instance pipeline sans charger les modèles IA réels."""

    def _build(db_session: Session) -> FaceRecognitionPipeline:
        def _stub_get_shared_components(cls):
            return _DummyDetector(), _DummyAligner(), _DummyEmbedder()

        monkeypatch.setattr(
            FaceRecognitionPipeline,
            "_get_shared_components",
            classmethod(_stub_get_shared_components),
        )
        return FaceRecognitionPipeline(db_session)

    return _build


# Tests Face Recognition Pipeline
class TestFaceRecognitionPipeline:
    """Tests pour le pipeline unique de reconnaissance faciale"""

    def test_face_pipeline_init(self, db_session, pipeline_factory):
        """Test initialisation du pipeline"""
        pipeline = pipeline_factory(db_session)
        assert pipeline.db is not None
        assert pipeline.matcher is not None
        assert pipeline.detector.backend == "stub_detector"

    def test_face_pipeline_statistics_empty(self, db_session, pipeline_factory):
        """Test statistiques faciales vides"""
        pipeline = pipeline_factory(db_session)
        stats = pipeline.get_statistics()

        assert stats["total_detections"] == 0
        assert stats["recognized"] == 0
        assert stats["unknown"] == 0
        assert stats["registered_personnel"] == 0

    def test_face_pipeline_history_empty(self, db_session, pipeline_factory):
        """Test historique détections vide"""
        pipeline = pipeline_factory(db_session)
        history = pipeline.get_history()

        assert history == []


# Tests Vehicle Service
class TestVehicleService:
    """Tests pour la détection véhicules"""
    
    def test_vehicle_service_init(self, db_session):
        """Test initialisation du service"""
        service = VehicleService(db_session)
        assert service.db is not None
    
    def test_vehicle_statistics_empty(self, db_session):
        """Test statistiques véhicules vides"""
        service = VehicleService(db_session)
        stats = service.get_statistics()
        
        assert stats["total_detections"] == 0
        assert stats["unique_vehicles"] == 0
        assert stats["avg_duration_minutes"] == 0
    
    def test_record_detection(self, db_session):
        """Test enregistrement détection"""
        service = VehicleService(db_session)
        
        result = service.record_detection(
            license_plate="ABC-123",
            confidence=0.95,
            camera_id=1,
            vehicle_type="car",
            color="red"
        )
        
        assert result["success"] == True
        assert result["license_plate"] == "ABC-123"
        assert result["vehicle_entry_id"] is not None
    
    def test_record_exit(self, db_session):
        """Test enregistrement sortie"""
        service = VehicleService(db_session)
        
        # D'abord enregistrer une détection
        det_result = service.record_detection(
            license_plate="XYZ-789",
            confidence=0.9,
            camera_id=1
        )
        
        # Puis enregistrer la sortie
        exit_result = service.record_exit(
            license_plate="XYZ-789",
            camera_id=2
        )
        
        assert exit_result["success"] == True
        assert exit_result["duration_minutes"] >= 0


# Tests Zone Service
class TestZoneService:
    """Tests pour la gestion des zones"""
    
    def test_zone_service_init(self, db_session):
        """Test initialisation du service"""
        service = ZoneService(db_session)
        assert service.db is not None
    
    def test_point_in_polygon(self, db_session):
        """Test algorithme point dans polygone"""
        service = ZoneService(db_session)
        
        # Carré: (0,0), (10,0), (10,10), (0,10)
        polygon = [(0, 0), (10, 0), (10, 10), (0, 10)]
        
        # Intérieur
        assert service.point_in_polygon((5, 5), polygon) == True
        
        # Extérieur
        assert service.point_in_polygon((15, 15), polygon) == False
        assert service.point_in_polygon((-5, 5), polygon) == False
    
    def test_create_zone_valid(self, db_session):
        """Test création zone valide"""
        service = ZoneService(db_session)
        
        coords = [(0, 0), (10, 0), (10, 10)]
        result = service.create_zone(
            name="Test Zone",
            description="Zone de test",
            camera_id=1,
            polygon_coords=coords,
            sensitivity=5
        )
        
        assert result["success"] == True
        assert result["zone_id"] is not None
        assert result["points"] == 3
    
    def test_create_zone_invalid(self, db_session):
        """Test création zone invalide (pas assez de points)"""
        service = ZoneService(db_session)
        
        coords = [(0, 0), (10, 0)]  # Seulement 2 points
        result = service.create_zone(
            name="Invalid Zone",
            description="Should fail",
            camera_id=1,
            polygon_coords=coords
        )
        
        assert result["success"] == False
        assert "at least 3 points" in result["message"]


# Tests intégration
class TestIntegration:
    """Tests d'intégration complets"""
    
    def test_complete_facial_workflow(self, db_session, pipeline_factory):
        """Test workflow complet reconnaissance faciale"""
        # 1. Créer un personnel
        personnel = Personnel(
            nom="John",
            prenom="Doe",
            full_name="John Doe",
            cin="CIN001",
            num_recrutement="REC001",
            categorie=PersonnelCategoryEnum.OFFICIER,
            grade="Lieutenant",
        )
        db_session.add(personnel)
        db_session.commit()
        
        # 2. Vérifier qu'il existe
        found = db_session.query(Personnel).filter(
            Personnel.num_recrutement == "REC001"
        ).first()
        assert found is not None
        
        # 3. Service facial peut le référencer
        pipeline = pipeline_factory(db_session)
        stats = pipeline.get_statistics()
        assert stats is not None
    
    def test_complete_vehicle_workflow(self, db_session):
        """Test workflow complet détection véhicules"""
        service = VehicleService(db_session)
        
        # 1. Enregistrer 3 entrées de même voiture
        for i in range(3):
            result = service.record_detection(
                license_plate="AUTO-001",
                confidence=0.85 + (i * 0.02),
                camera_id=1,
                vehicle_type="sedan"
            )
            assert result["success"] == True
        
        # 2. Vérifier qu'il y a une seule entrée
        entries = db_session.query(VehicleEntry).filter(
            VehicleEntry.license_plate == "AUTO-001",
            VehicleEntry.status == "active"
        ).all()
        assert len(entries) == 1
        
        # 3. Vérifier 3 détections
        detections = db_session.query(VehicleDetection).filter(
            VehicleDetection.license_plate == "AUTO-001"
        ).all()
        assert len(detections) == 3
    
    def test_complete_zone_workflow(self, db_session):
        """Test workflow complet zones"""
        service = ZoneService(db_session)
        
        # 1. Créer une zone
        coords = [(0, 0), (100, 0), (100, 100), (0, 100)]
        result = service.create_zone(
            name="Security Zone",
            camera_id=1,
            polygon_coords=coords
        )
        assert result["success"] == True
        zone_id = result["zone_id"]
        
        # 2. Enregistrer une entrée personnel
        entry_result = service.record_entry(
            zone_id=zone_id,
            personnel_id=1,
            vehicle_entry_id=None
        )
        assert entry_result["success"] == True
        occupancy_id = entry_result["occupancy_id"]
        
        # 3. Vérifier l'occupance
        occupancy = service.get_zone_occupancy(zone_id)
        assert occupancy["success"] == True
        assert occupancy["current_occupancy"] == 1
        
        # 4. Enregistrer la sortie
        exit_result = service.record_exit(occupancy_id)
        assert exit_result["success"] == True
        
        # 5. Vérifier occupance 0
        occupancy = service.get_zone_occupancy(zone_id)
        assert occupancy["current_occupancy"] == 0


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
