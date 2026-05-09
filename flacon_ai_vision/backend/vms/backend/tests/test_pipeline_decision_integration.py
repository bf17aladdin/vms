from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vms.backend.models import (
    Base,
    Camera,
    Personnel,
    PersonnelCategoryEnum,
)
from vms.backend.services.face_ai.face_detector import FaceDetection
from vms.backend.services.face_ai.face_pipeline import FaceRecognitionPipeline
from vms.backend.services.vehicle_ai.vehicle_pipeline import VehicleRecognitionPipeline


@pytest.fixture()
def db_session(tmp_path: Path):
    db_path = tmp_path / "pipeline_decision_integration.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_face_pipeline_calls_decision_service_and_action_engine(db_session, monkeypatch) -> None:
    person = Personnel(
        nom="Diallo",
        prenom="Awa",
        full_name="Awa Diallo",
        cin="CIN-PIPELINE-001",
        num_recrutement="REC-PIPELINE-001",
        categorie=PersonnelCategoryEnum.CIVIL,
        grade="Agent",
        allowed_camera_ids=[1],
        authorized_hours_start="00:00",
        authorized_hours_end="23:59",
        is_active=True,
        is_blacklisted=False,
    )
    db_session.add(person)
    db_session.commit()
    db_session.refresh(person)

    camera = Camera(
        name="Test Camera",
        owner_id=1,
        camera_type="face",
        is_active=True,
    )
    db_session.add(camera)
    db_session.commit()
    db_session.refresh(camera)

    pipeline = FaceRecognitionPipeline(db_session)
    monkeypatch.setattr(FaceRecognitionPipeline, "_save_image", lambda self, *args, **kwargs: "fake/path.jpg")
    monkeypatch.setattr(FaceRecognitionPipeline, "_frame_to_jpeg_bytes", lambda self, frame: b"\xff\xd8\xff")
    monkeypatch.setattr(FaceRecognitionPipeline, "_bbox_to_dict", lambda self, detection: {"x": int(detection.bbox[0]), "y": int(detection.bbox[1]), "width": int(detection.bbox[2]), "height": int(detection.bbox[3])})
    monkeypatch.setattr(FaceRecognitionPipeline, "_extract_history_crop", lambda self, frame_bgr, detection: None)
    monkeypatch.setattr(FaceRecognitionPipeline, "_save_track_identity", lambda self, *args, **kwargs: None)

    monkeypatch.setattr(pipeline, "detector", SimpleNamespace(detect=lambda frame_bgr, max_faces: [
        FaceDetection(bbox=(10, 20, 90, 110), score=0.96, landmarks=None, source="test", raw=None)
    ], backend="mock"))
    monkeypatch.setattr(pipeline, "aligner", SimpleNamespace(align=lambda frame_bgr, det: SimpleNamespace(
        aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
        yaw=0.0,
        pitch=0.0,
        roll=0.0,
        source="aligned",
    )))
    monkeypatch.setattr(pipeline, "embedder", SimpleNamespace(embed=lambda aligned_face, detection=None: (
        np.ones((128,), dtype=np.float32),
        "embedder",
    ), backend="mock"))
    monkeypatch.setattr(pipeline, "matcher", SimpleNamespace(match=lambda embedding, top_k, threshold_override=None: {
        "matched": True,
        "best_score": 0.95,
        "best": {
            "personnel_id": int(person.id),
            "full_name": person.full_name,
            "is_blacklisted": False,
            "is_active": True,
        },
    }, backend="mock"))

    monkeypatch.setattr(
        "vms.backend.services.face_ai.face_pipeline.extract_person_appearance",
        lambda image_path, face_bbox: SimpleNamespace(
            person_bbox={},
            top_color="red",
            bottom_color="blue",
            has_backpack=False,
            has_hat=False,
            embedding=None,
        ),
    )

    action_called: dict[str, object] = {}

    def fake_handle_decision(*, request, result, camera_id, zone_id, frame_bgr, bbox, confidence, snapshot_path, source_table, source_detection_id, label, extra_data, detected_at):
        action_called["decision"] = result.decision
        action_called["reason_code"] = result.reason_code
        return {"event_id": 123, "unknown_detection_id": None}

    monkeypatch.setattr(pipeline.action_engine, "handle_decision", fake_handle_decision)

    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    response = pipeline.recognize_from_frame(
        frame_bgr=frame,
        camera_id=int(camera.id),
        zone_id=None,
        persist=True,
        top_k=1,
        image_bytes=b"fake",
    )

    assert response["status"] == "matched"
    assert response["decision"] == "allow"
    assert response["reason_code"] == "personnel_authorized"
    assert response["access_decision"]["decision"] == "allow"
    assert action_called["decision"] == "allow"
    assert action_called["reason_code"] == "personnel_authorized"


def test_face_pipeline_unknown_detection_triggers_unknown_queue(db_session, monkeypatch) -> None:
    camera = Camera(
        name="Test Camera",
        owner_id=1,
        camera_type="face",
        is_active=True,
    )
    db_session.add(camera)
    db_session.commit()
    db_session.refresh(camera)

    pipeline = FaceRecognitionPipeline(db_session)
    monkeypatch.setattr(FaceRecognitionPipeline, "_save_image", lambda self, *args, **kwargs: "fake/path.jpg")
    monkeypatch.setattr(FaceRecognitionPipeline, "_frame_to_jpeg_bytes", lambda self, frame: b"\xff\xd8\xff")
    monkeypatch.setattr(FaceRecognitionPipeline, "_bbox_to_dict", lambda self, detection: {"x": int(detection.bbox[0]), "y": int(detection.bbox[1]), "width": int(detection.bbox[2]), "height": int(detection.bbox[3])})
    monkeypatch.setattr(FaceRecognitionPipeline, "_extract_history_crop", lambda self, frame_bgr, detection: None)
    monkeypatch.setattr(FaceRecognitionPipeline, "_save_track_identity", lambda self, *args, **kwargs: None)

    monkeypatch.setattr(pipeline, "detector", SimpleNamespace(detect=lambda frame_bgr, max_faces: [
        FaceDetection(bbox=(10, 20, 90, 110), score=0.88, landmarks=None, source="test", raw=None)
    ], backend="mock"))
    monkeypatch.setattr(pipeline, "aligner", SimpleNamespace(align=lambda frame_bgr, det: SimpleNamespace(
        aligned_face=np.zeros((112, 112, 3), dtype=np.uint8),
        yaw=0.0,
        pitch=0.0,
        roll=0.0,
        source="aligned",
    )))
    monkeypatch.setattr(pipeline, "embedder", SimpleNamespace(embed=lambda aligned_face, detection=None: (
        np.ones((128,), dtype=np.float32),
        "embedder",
    ), backend="mock"))
    monkeypatch.setattr(pipeline, "matcher", SimpleNamespace(match=lambda embedding, top_k, threshold_override=None: {
        "matched": False,
        "best_score": 0.40,
        "best": None,
    }, backend="mock"))

    monkeypatch.setattr(
        "vms.backend.services.face_ai.face_pipeline.extract_person_appearance",
        lambda image_path, face_bbox: SimpleNamespace(
            person_bbox={},
            top_color="red",
            bottom_color="blue",
            has_backpack=False,
            has_hat=False,
            embedding=None,
        ),
    )

    action_called: dict[str, object] = {}

    def fake_handle_decision(*, request, result, camera_id, zone_id, frame_bgr, bbox, confidence, snapshot_path, source_table, source_detection_id, label, extra_data, detected_at):
        action_called["decision"] = result.decision
        action_called["reason_code"] = result.reason_code
        return {"event_id": None, "unknown_detection_id": 301}

    monkeypatch.setattr(pipeline.action_engine, "handle_decision", fake_handle_decision)

    frame = np.zeros((200, 200, 3), dtype=np.uint8)
    response = pipeline.recognize_from_frame(
        frame_bgr=frame,
        camera_id=int(camera.id),
        zone_id=None,
        persist=True,
        top_k=1,
        image_bytes=b"fake",
    )

    assert response["status"] == "unknown"
    assert response["decision"] == "unknown"
    assert response["reason_code"] == "personnel_unrecognized"
    assert action_called["decision"] == "unknown"
    assert action_called["reason_code"] == "personnel_unrecognized"


def test_vehicle_pipeline_denies_mismatched_plate_and_dispatches_action(db_session, monkeypatch) -> None:
    pipeline = VehicleRecognitionPipeline(db_session)
    monkeypatch.setattr(VehicleRecognitionPipeline, "_save_snapshot", lambda self, *args, **kwargs: "fake/vehicle.jpg")
    monkeypatch.setattr(VehicleRecognitionPipeline, "_frame_to_jpeg_bytes", lambda self, frame: b"\xff\xd8\xff")
    monkeypatch.setattr(VehicleRecognitionPipeline, "_resolve_site_id", lambda self, camera_id: None)
    monkeypatch.setattr(VehicleRecognitionPipeline, "_persist_event", lambda self, **kwargs: (42, kwargs.get("detected_at") or datetime.utcnow()))
    monkeypatch.setattr(VehicleRecognitionPipeline, "_persist_event_frame", lambda self, *args, **kwargs: None)

    monkeypatch.setattr(
        pipeline,
        "detection_module",
        SimpleNamespace(
            detect_and_select_primary=lambda frame_bgr, camera_id, ocr_available: SimpleNamespace(
                vehicle_detected=True,
                primary=SimpleNamespace(
                    class_name="vehicle",
                    bbox=(0, 0, 100, 50),
                    confidence=0.82,
                    source="test_detector",
                ),
                primary_track_id=1,
                tracker_backend="test_tracker",
                plate_only_fallback_attempted=False,
                plate_only_fallback_used=False,
                plate_only_fallback_reason=None,
                early_exit_reason=None,
            )
        ),
    )

    scan_result = SimpleNamespace(
        plate_result=SimpleNamespace(source="ocr", bbox=(0, 0, 0, 0), candidates=[]),
        raw_text="999 TUNIS 0000",
        plate_confidence=0.82,
        plate_bbox=(0, 0, 100, 40),
        plate_crop=np.zeros((40, 100, 3), dtype=np.uint8),
        normalized_text="999 TUNIS 0000",
        compact_text="999 TUNIS 0000",
        plate_code="999",
        plate_city="TUNIS",
        plate_sequence="0000",
        plate_display="999 TUNIS 0000",
        plate_reliable=True,
    )
    monkeypatch.setattr(pipeline.plate_scanner_module, "scan", lambda frame_bgr, vehicle_bbox: scan_result)

    monkeypatch.setattr(
        pipeline.attributes_module,
        "resolve_plate_identity",
        lambda **kwargs: SimpleNamespace(
            plate_number="999 TUNIS 0000",
            plate_display="999 TUNIS 0000",
            plate_code="999",
            plate_city="TUNIS",
            plate_sequence="0000",
        ),
    )
    monkeypatch.setattr(
        pipeline.attributes_module,
        "classify_plate_type",
        lambda **kwargs: SimpleNamespace(
            plate_type="civil",
            confidence=0.90,
            reason="plate_recognized",
            security_tag=None,
            matched_registry=False,
            reasons=["plate_recognized"],
        ),
    )
    monkeypatch.setattr(pipeline.attributes_module, "infer_vehicle_profile", lambda **kwargs: {})

    access_decision = SimpleNamespace(
        decision="deny",
        reason="vehicle_not_in_registry",
        severity="critical",
        is_priority=False,
        requires_manual_review=False,
        alert_type="vehicle",
        registry_vehicle_id=None,
        registry_matched=False,
        security_tag=None,
        flags=[],
        visual_consistency={},
        dominant_color=None,
    )
    monkeypatch.setattr(pipeline.access_controller, "evaluate", lambda **kwargs: access_decision)
    monkeypatch.setattr(pipeline.access_controller, "persist_access_decision", lambda **kwargs: (None, []))

    action_called: dict[str, object] = {}

    def fake_handle_decision(*, request, result, camera_id, zone_id, frame_bgr, bbox, confidence, snapshot_path, source_table, source_detection_id, label, extra_data, detected_at):
        action_called["decision"] = result.decision
        action_called["reason_code"] = result.reason_code
        return {"event_id": 99, "unknown_detection_id": None}

    monkeypatch.setattr(pipeline.action_engine, "handle_decision", fake_handle_decision)

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    response = pipeline.recognize_from_frame(
        frame_bgr=frame,
        camera_id=7,
        zone_id=None,
        gate_id=None,
        direction="IN",
        persist=True,
        save_snapshot=True,
        image_bytes=b"fake",
    )

    assert response["decision"] == "deny"
    assert response["access_decision_result"]["reason_code"] == "vehicle_not_in_registry"
    assert action_called["decision"] == "deny"
    assert action_called["reason_code"] == "vehicle_not_in_registry"
