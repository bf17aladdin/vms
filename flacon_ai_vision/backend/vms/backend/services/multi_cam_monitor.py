from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import mean
from typing import Optional

from sqlalchemy.orm import Session

from vms.backend.services.person_appearance import (
    appearance_similarity,
    build_appearance_embedding,
)


class MultiCamMonitorService:
    """Aggregate live person and vehicle tracks across cameras."""

    def __init__(self, db: Session):
        self.db = db

    def get_snapshot(
        self,
        minutes: int = 30,
        person_limit: int = 20,
        vehicle_limit: int = 20,
        similarity_threshold: float = 0.88,
    ) -> dict:
        person_tracks = self._build_person_tracks(
            minutes=minutes,
            limit=max(person_limit * 8, 40),
            similarity_threshold=similarity_threshold,
        )[:person_limit]
        vehicles = self._get_recent_vehicles(minutes=minutes, limit=vehicle_limit)

        timeline = sorted(
            [
                *[
                    {
                        "type": "person_track",
                        "id": track["track_id"],
                        "camera_id": track["last_camera_id"],
                        "detected_at": track["last_seen"],
                        "title": track["label"],
                        "confidence": track["track_confidence"],
                    }
                    for track in person_tracks
                ],
                *[
                    {
                        "type": "vehicle_detection",
                        "id": vehicle["detection_id"],
                        "camera_id": vehicle["camera_id"],
                        "detected_at": vehicle["detected_at"],
                        "title": vehicle["license_plate"] or "Unknown vehicle",
                        "confidence": vehicle["confidence"],
                    }
                    for vehicle in vehicles
                ],
            ],
            key=lambda item: item["detected_at"],
            reverse=True,
        )[:30]

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "summary": {
                "active_person_tracks": len(person_tracks),
                "cross_camera_tracks": len(
                    [track for track in person_tracks if len(track["camera_ids"]) > 1]
                ),
                "recent_vehicle_tracks": len(vehicles),
            },
            "persons": person_tracks,
            "vehicles": vehicles,
            "timeline": timeline,
        }

    def _build_person_tracks(
        self,
        minutes: int,
        limit: int,
        similarity_threshold: float,
    ) -> list[dict]:
        from vms.backend.models import FaceDetection

        since = datetime.utcnow() - timedelta(minutes=minutes)
        detections = (
            self.db.query(FaceDetection)
            .filter(FaceDetection.detected_at >= since)
            .order_by(FaceDetection.detected_at.desc())
            .limit(limit)
            .all()
        )

        tracks: list[dict] = []
        for detection in detections:
            embedding = self._resolve_embedding(detection)
            if not embedding:
                continue

            best_track = None
            best_score = 0.0
            for track in tracks:
                score = self._track_match_score(track, detection, embedding)
                if score > best_score:
                    best_score = score
                    best_track = track

            if best_track and (
                self._same_personnel(best_track, detection)
                or best_score >= similarity_threshold
            ):
                self._attach_detection(best_track, detection, embedding, best_score)
            else:
                tracks.append(self._create_track(detection, embedding))

        normalized_tracks = [self._finalize_track(track) for track in tracks]
        normalized_tracks.sort(
            key=lambda track: (track["track_confidence"], track["last_seen"]),
            reverse=True,
        )
        return normalized_tracks

    def _get_recent_vehicles(self, minutes: int, limit: int) -> list[dict]:
        from vms.backend.models import VehicleDetection

        since = datetime.utcnow() - timedelta(minutes=minutes)
        detections = (
            self.db.query(VehicleDetection)
            .filter(VehicleDetection.detected_at >= since)
            .order_by(VehicleDetection.detected_at.desc())
            .limit(limit)
            .all()
        )

        return [
            {
                "detection_id": detection.id,
                "license_plate": detection.license_plate,
                "camera_id": detection.camera_id,
                "detected_at": detection.detected_at.isoformat(),
                "confidence": float(detection.plate_confidence or 0.0),
                "vehicle_type": detection.vehicle_type or "unknown",
                "color": detection.color or "unknown",
                "brand": detection.vehicle_entry.brand
                if detection.vehicle_entry and detection.vehicle_entry.brand
                else "unknown",
                "model": detection.vehicle_entry.model
                if detection.vehicle_entry and detection.vehicle_entry.model
                else "unknown",
            }
            for detection in detections
        ]

    def _create_track(self, detection, embedding: list[float]) -> dict:
        score = float(detection.confidence or 0.0)
        member = self._serialize_person_detection(detection, score)
        return {
            "track_id": f"person-track-{detection.id}",
            "personnel_id": detection.personnel_id,
            "embeddings": [embedding],
            "members": [member],
            "camera_ids": {int(detection.camera_id)},
            "top_colors": Counter([detection.appearance_top_color or "unknown"]),
            "bottom_colors": Counter([detection.appearance_bottom_color or "unknown"]),
            "backpacks": Counter([self._serialize_bool(detection.has_backpack)]),
            "hats": Counter([self._serialize_bool(detection.has_hat)]),
            "scores": [score],
            "latest_detection": detection,
        }

    def _attach_detection(
        self,
        track: dict,
        detection,
        embedding: list[float],
        score: float,
    ) -> None:
        track["personnel_id"] = track["personnel_id"] or detection.personnel_id
        track["embeddings"].append(embedding)
        track["members"].append(self._serialize_person_detection(detection, score))
        track["camera_ids"].add(int(detection.camera_id))
        track["top_colors"][detection.appearance_top_color or "unknown"] += 1
        track["bottom_colors"][detection.appearance_bottom_color or "unknown"] += 1
        track["backpacks"][self._serialize_bool(detection.has_backpack)] += 1
        track["hats"][self._serialize_bool(detection.has_hat)] += 1
        track["scores"].append(score)
        if detection.detected_at > track["latest_detection"].detected_at:
            track["latest_detection"] = detection

    def _finalize_track(self, track: dict) -> dict:
        members = sorted(
            track["members"],
            key=lambda member: member["detected_at"],
            reverse=True,
        )
        latest = track["latest_detection"]
        cross_camera_matches = self._compute_cross_camera_matches(members)
        label = (
            latest.personnel.full_name
            if latest.personnel is not None
            else f"Unknown track {latest.id}"
        )

        return {
            "track_id": track["track_id"],
            "label": label,
            "personnel_id": track["personnel_id"],
            "last_seen": latest.detected_at.isoformat(),
            "last_camera_id": latest.camera_id,
            "camera_ids": sorted(track["camera_ids"]),
            "detections_count": len(members),
            "track_confidence": round(mean(track["scores"]), 4) if track["scores"] else 0.0,
            "dominant_top_color": track["top_colors"].most_common(1)[0][0],
            "dominant_bottom_color": track["bottom_colors"].most_common(1)[0][0],
            "backpack": track["backpacks"].most_common(1)[0][0],
            "hat": track["hats"].most_common(1)[0][0],
            "cross_camera_matches": cross_camera_matches,
            "members": [self._public_member_payload(member) for member in members[:6]],
        }

    def _compute_cross_camera_matches(self, members: list[dict]) -> list[dict]:
        matches: list[dict] = []
        for index, source in enumerate(members):
            source_embedding = source.get("appearance_embedding")
            if not source_embedding:
                continue

            for candidate in members[index + 1 :]:
                if candidate["camera_id"] == source["camera_id"]:
                    continue

                similarity = appearance_similarity(
                    source_embedding,
                    candidate.get("appearance_embedding"),
                )
                if similarity <= 0:
                    continue
                matches.append(
                    {
                        "source_detection_id": source["id"],
                        "match_detection_id": candidate["id"],
                        "source_camera_id": source["camera_id"],
                        "match_camera_id": candidate["camera_id"],
                        "similarity": round(similarity, 4),
                    }
                )

        matches.sort(key=lambda item: item["similarity"], reverse=True)
        return matches[:5]

    def _track_match_score(self, track: dict, detection, embedding: list[float]) -> float:
        latest_member = track["members"][0]
        latest_embedding = latest_member.get("appearance_embedding")
        if not latest_embedding:
            return 0.0

        appearance_score = appearance_similarity(latest_embedding, embedding)
        confidence_score = float(detection.confidence or 0.0)
        if self._same_personnel(track, detection):
            return max(appearance_score, 0.99)
        if detection.camera_id != latest_member["camera_id"]:
            return min(1.0, (appearance_score * 0.8) + (confidence_score * 0.2) + 0.03)
        return (appearance_score * 0.82) + (confidence_score * 0.18)

    @staticmethod
    def _same_personnel(track: dict, detection) -> bool:
        return bool(track["personnel_id"] and track["personnel_id"] == detection.personnel_id)

    @staticmethod
    def _serialize_bool(value: Optional[bool]) -> str:
        if value is None:
            return "unknown"
        return "yes" if value else "no"

    def _serialize_person_detection(self, detection, track_score: float) -> dict:
        embedding = self._resolve_embedding(detection)
        return {
            "id": detection.id,
            "camera_id": detection.camera_id,
            "personnel_id": detection.personnel_id,
            "personnel_name": detection.personnel.full_name
            if detection.personnel is not None
            else "Unknown",
            "detected_at": detection.detected_at.isoformat(),
            "confidence": float(detection.confidence or 0.0),
            "match_quality": detection.match_quality or "low",
            "top_color": detection.appearance_top_color or "unknown",
            "bottom_color": detection.appearance_bottom_color or "unknown",
            "backpack": self._serialize_bool(detection.has_backpack),
            "hat": self._serialize_bool(detection.has_hat),
            "notes": detection.notes,
            "appearance_embedding": embedding,
            "has_appearance_embedding": bool(embedding),
            "track_score": round(track_score, 4),
        }

    @staticmethod
    def _public_member_payload(member: dict) -> dict:
        return {
            key: value for key, value in member.items() if key != "appearance_embedding"
        }

    @staticmethod
    def _resolve_embedding(detection) -> Optional[list[float]]:
        if detection.appearance_embedding:
            return detection.appearance_embedding
        if (
            detection.appearance_top_color
            or detection.appearance_bottom_color
            or detection.has_backpack is not None
            or detection.has_hat is not None
        ):
            return build_appearance_embedding(
                top_color=detection.appearance_top_color,
                bottom_color=detection.appearance_bottom_color,
                has_backpack=detection.has_backpack,
                has_hat=detection.has_hat,
            )
        return None
