from __future__ import annotations

import numpy as np
import pytest

from vms.backend.services import frame_processor
from vms.backend.services.frame_processor import FrameProcessor


def test_frame_processor_surfaces_vehicle_decision_context(monkeypatch) -> None:
    processor = FrameProcessor(camera_id=101, camera_name="TestCamera")
    processor.vehicle_detector = True
    processor.face_recognizer = None
    monkeypatch.setattr(frame_processor, "_HAS_FACE_PIPELINE", False)
    monkeypatch.setattr(
        FrameProcessor,
        "_detect_faces",
        lambda self, frame, db=None: {"faces": [], "alerts": []},
    )
    monkeypatch.setattr(
        FrameProcessor,
        "_detect_vehicles",
        lambda self, frame, db=None: {
            "vehicles": [
                {
                    "type": "vehicle",
                    "confidence": 0.92,
                    "plate_text": "ABC-123",
                    "decision": "deny",
                    "reason_code": "vehicle_not_in_registry",
                    "event_id": 42,
                    "decision_event_id": 99,
                    "unknown_detection_id": None,
                }
            ],
            "alerts": [
                {
                    "type": "vehicle_deny",
                    "camera_id": 101,
                    "vehicle_type": "vehicle",
                    "plate_text": "ABC-123",
                    "confidence": 0.92,
                    "reason_code": "vehicle_not_in_registry",
                    "event_id": 42,
                    "unknown_detection_id": None,
                    "timestamp": "2026-04-19T12:00:00Z",
                }
            ],
        },
    )
    monkeypatch.setattr(FrameProcessor, "_resolve_zone_context", lambda self, db=None: {})
    monkeypatch.setattr(FrameProcessor, "_evaluate_rules_for_detections", lambda self, faces, vehicles, db=None, zone_context=None: [])
    monkeypatch.setattr(FrameProcessor, "_save_thumbnail", lambda self, frame: None)

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    results = processor.process_frame(frame)

    assert results["camera_id"] == 101
    assert len(results["vehicles"]) == 1
    vehicle_info = results["vehicles"][0]
    assert vehicle_info["decision"] == "deny"
    assert vehicle_info["reason_code"] == "vehicle_not_in_registry"
    assert vehicle_info["event_id"] == 42
    assert vehicle_info["decision_event_id"] == 99
    assert any(alert["type"] == "vehicle_deny" for alert in results["alerts"])


def test_frame_processor_surfaces_face_decision_context(monkeypatch) -> None:
    processor = FrameProcessor(camera_id=202, camera_name="FaceCamera")
    processor.vehicle_detector = None
    processor.face_recognizer = True
    monkeypatch.setattr(frame_processor, "_HAS_FACE_PIPELINE", False)
    monkeypatch.setattr(
        FrameProcessor,
        "_detect_faces",
        lambda self, frame, db=None: {
            "faces": [
                {
                    "bbox": {"x": 10, "y": 10, "width": 80, "height": 100},
                    "name": "Awa Diallo",
                    "person_id": 123,
                    "track_id": 7,
                    "is_known": True,
                    "confidence": 0.94,
                    "timestamp": "2026-04-19T12:00:00Z",
                    "match_quality": 0.92,
                    "decision": "allow",
                    "reason_code": "personnel_authorized",
                    "event_id": 51,
                    "unknown_detection_id": None,
                }
            ],
            "alerts": [],
        },
    )
    monkeypatch.setattr(FrameProcessor, "_detect_vehicles", lambda self, frame, db=None: {"vehicles": [], "alerts": []})
    monkeypatch.setattr(FrameProcessor, "_resolve_zone_context", lambda self, db=None: {})
    monkeypatch.setattr(FrameProcessor, "_evaluate_rules_for_detections", lambda self, faces, vehicles, db=None, zone_context=None: [])
    monkeypatch.setattr(FrameProcessor, "_save_thumbnail", lambda self, frame: None)

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    results = processor.process_frame(frame)

    assert results["camera_id"] == 202
    assert len(results["faces"]) == 1
    face_info = results["faces"][0]
    assert face_info["decision"] == "allow"
    assert face_info["reason_code"] == "personnel_authorized"
    assert face_info["event_id"] == 51
    assert all(alert["type"] != "face_deny" for alert in results["alerts"])
