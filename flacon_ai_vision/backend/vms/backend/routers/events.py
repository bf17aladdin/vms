# vms/backend/routers/events.py - Event routes

from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import schemas
from ..core.database import get_db
from ..core.security import get_current_user, require_viewer, require_operator, require_supervisor
from ..services.event_service import EventService

router = APIRouter(prefix="/api/events", tags=["events"])


class EventCommentRequest(BaseModel):
    comment: str = Field(..., min_length=1, max_length=1000)


@router.get("", response_model=dict)
def list_events(
    skip: int = 0,
    limit: int = 50,
    site_id: Optional[int] = Query(None),
    camera_id: Optional[int] = Query(None),
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List events."""
    try:
        tenant_id = current_user.get("tenant_id")
        if camera_id is not None:
            events = EventService.get_events_by_camera(db, camera_id=camera_id, skip=skip, limit=limit, tenant_id=tenant_id)
        elif site_id is not None:
            events = EventService.get_events_by_site(db, site_id=site_id, skip=skip, limit=limit, tenant_id=tenant_id)
        else:
            events = EventService.get_all_events(db, skip=skip, limit=limit, tenant_id=tenant_id)
        return {
            "count": len(events),
            "events": events,
            "message": "Events retrieved successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/recent", response_model=dict)
def list_recent_events(
    hours: int = 24,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List recent events."""
    try:
        tenant_id = current_user.get("tenant_id")
        events = EventService.get_recent_events(db, hours=hours, tenant_id=tenant_id)
        return {
            "count": len(events),
            "events": events,
            "message": f"Recent events (last {hours} hours) retrieved successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/unacknowledged", response_model=dict)
def list_unacknowledged_events(
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """List unacknowledged events."""
    try:
        tenant_id = current_user.get("tenant_id")
        events = EventService.get_unacknowledged_events(db, tenant_id=tenant_id)
        return {
            "count": len(events),
            "events": events,
            "message": "Unacknowledged events retrieved successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("", response_model=dict)
def create_event(
    payload: schemas.EventCreate,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Create an event."""
    try:
        creator_id = current_user.get("user_id", 1)
        tenant_id = current_user.get("tenant_id")
        event = EventService.create_event(db, payload, creator_id=creator_id, camera_id=payload.camera_id, tenant_id=tenant_id)
        return {
            "id": event["id"],
            "event": event,
            "message": "Event created successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/export")
def export_events(
    camera_id: Optional[int] = Query(None),
    site_id: Optional[int] = Query(None),
    severity: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    format: str = Query("csv", pattern="^(csv|json)$"),
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Export events with camera/date/severity filters."""
    try:
        tenant_id = current_user.get("tenant_id")
        rows = EventService.export_events(
            db,
            camera_id=camera_id,
            site_id=site_id,
            severity=severity,
            date_from=date_from,
            date_to=date_to,
            tenant_id=tenant_id,
        )

        if format == "json":
            return {
                "count": len(rows),
                "events": rows,
                "message": "Events exported successfully",
            }

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "id",
                "event_type",
                "severity",
                "camera_id",
                "zone_id",
                "site_id",
                "decision",
                "description",
                "is_acknowledged",
                "detected_at",
                "created_at",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "id": row.get("id"),
                    "event_type": row.get("event_type"),
                    "severity": row.get("severity"),
                    "camera_id": row.get("camera_id"),
                    "zone_id": row.get("zone_id"),
                    "site_id": row.get("site_id"),
                    "decision": row.get("decision"),
                    "description": row.get("description"),
                    "is_acknowledged": row.get("is_acknowledged"),
                    "detected_at": row.get("detected_at"),
                    "created_at": row.get("created_at"),
                }
            )

        body = output.getvalue().encode("utf-8")
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=events_export.csv"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/{event_id}", response_model=dict)
def get_event(
    event_id: int,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Get one event by id."""
    try:
        tenant_id = current_user.get("tenant_id")
        event = EventService.get_event_by_id(db, event_id, tenant_id=tenant_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        return {
            "event": event,
            "message": "Event retrieved successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/{event_id}/read", response_model=dict)
def mark_event_read(
    event_id: int,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Mark event as read."""
    try:
        tenant_id = current_user.get("tenant_id")
        event = EventService.get_event_by_id(db, event_id, tenant_id=tenant_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        event = EventService.mark_as_read(db, event_id)
        return {
            "event": event,
            "message": "Event marked as read",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/{event_id}/acknowledge", response_model=dict)
def acknowledge_event(
    event_id: int,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Acknowledge event."""
    try:
        tenant_id = current_user.get("tenant_id")
        event = EventService.get_event_by_id(db, event_id, tenant_id=tenant_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        user_id = current_user.get("user_id", None)
        event = EventService.acknowledge_event(db, event_id, user_id=user_id)
        return {
            "event": event,
            "message": "Event acknowledged successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/{event_id}/comment", response_model=dict)
def add_event_comment(
    event_id: int,
    payload: EventCommentRequest,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Add operator comment to an event."""
    try:
        tenant_id = current_user.get("tenant_id")
        event = EventService.get_event_by_id(db, event_id, tenant_id=tenant_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        event = EventService.add_comment(
            db,
            event_id=event_id,
            comment=payload.comment,
            user_id=current_user.get("user_id"),
            username=current_user.get("sub"),
        )
        return {
            "event": event,
            "message": "Comment added successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.delete("/{event_id}", response_model=dict)
def delete_event(
    event_id: int,
    current_user: dict = Depends(require_supervisor),
    db: Session = Depends(get_db),
):
    """Delete event."""
    try:
        tenant_id = current_user.get("tenant_id")
        event = EventService.get_event_by_id(db, event_id, tenant_id=tenant_id)
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        success = EventService.delete_event(db, event_id)
        if not success:
            raise HTTPException(status_code=404, detail="Event not found")
        return {
            "id": event_id,
            "message": "Event deleted successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/camera/{camera_id}", response_model=dict)
def get_events_by_camera(
    camera_id: int,
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Get events for one camera."""
    try:
        tenant_id = current_user.get("tenant_id")
        events = EventService.get_events_by_camera(db, camera_id, skip=skip, limit=limit, tenant_id=tenant_id)
        return {
            "count": len(events),
            "camera_id": camera_id,
            "events": events,
            "message": "Camera events retrieved successfully",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
