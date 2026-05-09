# vms/backend/services/event_service.py - Business layer for events

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from .. import crud, models, schemas
from ..core.media_paths import to_public_media_path


class EventService:
    """Service for event workflows."""

    @staticmethod
    def get_all_events(db: Session, skip: int = 0, limit: int = 50, tenant_id: Optional[int] = None) -> List[dict]:
        events = crud.get_all_events(db, skip=skip, limit=limit, tenant_id=tenant_id)
        return [EventService._format_event(ev) for ev in events]
    @staticmethod
    def get_recent_events(db: Session, hours: int = 24, tenant_id: Optional[int] = None) -> List[dict]:
        events = crud.get_recent_events(db, hours=hours, tenant_id=tenant_id)
        return [EventService._format_event(ev) for ev in events]
    @staticmethod
    def get_events_by_camera(db: Session, camera_id: int, skip: int = 0, limit: int = 50, tenant_id: Optional[int] = None) -> List[dict]:
        events = crud.get_events_by_camera(db, camera_id, skip=skip, limit=limit, tenant_id=tenant_id)
        return [EventService._format_event(ev) for ev in events]
    @staticmethod
    def get_events_by_site(db: Session, site_id: int, skip: int = 0, limit: int = 50, tenant_id: Optional[int] = None) -> List[dict]:
        events = crud.get_events_by_site(db, site_id, skip=skip, limit=limit, tenant_id=tenant_id)
        return [EventService._format_event(ev) for ev in events]
    @staticmethod
    def get_unacknowledged_events(db: Session, tenant_id: Optional[int] = None) -> List[dict]:
        events = crud.get_unacknowledged_events(db, tenant_id=tenant_id)
        return [EventService._format_event(ev) for ev in events]
    @staticmethod
    def get_event_by_id(db: Session, event_id: int, tenant_id: Optional[int] = None) -> Optional[dict]:
        event = crud.get_event_by_id(db, event_id, tenant_id=tenant_id)
        if not event:
            return None
        return EventService._format_event(event)
    @staticmethod
    def create_event(db: Session, event_data: schemas.EventCreate, creator_id: int, camera_id: Optional[int] = None, tenant_id: Optional[int] = None) -> dict:
        if not camera_id:
            camera_id = event_data.camera_id
        event = crud.create_event(db, event_data, creator_id=creator_id, tenant_id=tenant_id)
        return EventService._format_event(event)
    @staticmethod
    def mark_as_read(db: Session, event_id: int) -> Optional[dict]:
        event = crud.mark_event_as_read(db, event_id)
        if not event:
            return None
        return EventService._format_event(event)

    @staticmethod
    def acknowledge_event(db: Session, event_id: int, user_id: Optional[int] = None) -> Optional[dict]:
        event = crud.acknowledge_event(db, event_id, user_id=user_id)
        if not event:
            return None
        return EventService._format_event(event)

    @staticmethod
    def add_comment(
        db: Session,
        event_id: int,
        comment: str,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
    ) -> Optional[dict]:
        event = crud.add_event_comment(
            db,
            event_id=event_id,
            comment=comment,
            user_id=user_id,
            username=username,
        )
        if not event:
            return None
        return EventService._format_event(event)

    @staticmethod
    def export_events(
        db: Session,
        *,
        camera_id: Optional[int] = None,
        site_id: Optional[int] = None,
        severity: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 5000,
        tenant_id: Optional[int] = None,
    ) -> List[dict]:
        query = db.query(models.Event)

        if tenant_id is not None:
            query = query.filter(models.Event.tenant_id == tenant_id)
        if camera_id is not None:
            query = query.filter(models.Event.camera_id == int(camera_id))
        if site_id is not None:
            query = query.filter(models.Event.site_id == int(site_id))
        if severity:
            query = query.filter(models.Event.severity == str(severity).lower())

        parsed_from: Optional[datetime] = None
        parsed_to: Optional[datetime] = None
        if date_from:
            parsed_from = datetime.fromisoformat(date_from)
        if date_to:
            parsed_to = datetime.fromisoformat(date_to)
            if len(date_to) <= 10:
                parsed_to = parsed_to + timedelta(days=1)

        if parsed_from is not None:
            query = query.filter(models.Event.detected_at >= parsed_from)
        if parsed_to is not None:
            query = query.filter(models.Event.detected_at < parsed_to)

        rows = query.order_by(models.Event.detected_at.desc()).limit(max(1, min(limit, 20000))).all()
        return [EventService._format_event(row) for row in rows]
    @staticmethod
    def delete_event(db: Session, event_id: int) -> bool:
        return crud.delete_event(db, event_id)

    @staticmethod
    def _format_event(event) -> dict:
        extra_data = event.extra_data if isinstance(event.extra_data, dict) else {}
        comments = extra_data.get("comments") if isinstance(extra_data.get("comments"), list) else []
        return {
            "id": event.id,
            "tenant_id": getattr(event, "tenant_id", None),
            "camera_id": event.camera_id,
            "zone_id": event.zone_id,
            "site_id": event.site_id,
            "creator_id": event.creator_id,
            "event_type": event.event_type,
            "severity": event.severity,
            "decision": event.decision or "review",
            "description": event.description,
            "detected_objects": event.detected_objects,
            "confidence": event.confidence,
            "thumbnail_url": event.thumbnail_url,
            "video_url": event.video_url,
            "snapshot_path": to_public_media_path(event.snapshot_path),
            "latitude": event.latitude,
            "longitude": event.longitude,
            "detected_at": event.detected_at.isoformat() if event.detected_at else None,
            "is_acknowledged": event.is_acknowledged,
            "is_archived": event.is_archived,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "updated_at": event.updated_at.isoformat() if event.updated_at else None,
            "extra_data": extra_data,
            "comments_count": len(comments),
        }
