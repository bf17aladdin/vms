"""
Video Recording Router
Endpoints for managing video recordings, playback, and storage
"""

from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from vms.backend.core.security import get_current_user
from vms.backend.services.video_recorder import get_video_recorder

router = APIRouter(prefix="/api/video", tags=["Video Recording"])


@router.post("/start")
async def start_recording(
    camera_id: int,
    camera_name: str,
    zone_id: Optional[int] = None,
    quality: str = "1080p",
    current_user=Depends(get_current_user),
) -> Dict:
    """Start recording for a camera."""
    try:
        recorder = get_video_recorder()
        result = recorder.start_recording(camera_id, camera_name, zone_id, quality)
        if result.get("status") == "success":
            return result
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to start recording"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/stop/{camera_id}")
async def stop_recording(camera_id: int, current_user=Depends(get_current_user)) -> Dict:
    """Stop recording for a camera."""
    try:
        recorder = get_video_recorder()
        result = recorder.stop_recording(camera_id)
        if result.get("status") == "success":
            return result
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to stop recording"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/pause/{camera_id}")
async def pause_recording(camera_id: int, current_user=Depends(get_current_user)) -> Dict:
    """Pause recording for a camera."""
    try:
        recorder = get_video_recorder()
        result = recorder.pause_recording(camera_id)
        if result.get("status") == "success":
            return result
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to pause recording"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/resume/{camera_id}")
async def resume_recording(camera_id: int, current_user=Depends(get_current_user)) -> Dict:
    """Resume recording for a camera."""
    try:
        recorder = get_video_recorder()
        result = recorder.resume_recording(camera_id)
        if result.get("status") == "success":
            return result
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to resume recording"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/active")
async def get_active_recordings(current_user=Depends(get_current_user)) -> Dict:
    """Get all currently active recordings."""
    try:
        recorder = get_video_recorder()
        active = recorder.get_active_recordings()
        return {
            "status": "success",
            "active_count": len(active),
            "recordings": active,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history/{camera_id}")
async def get_recording_history(
    camera_id: int,
    limit: int = 50,
    current_user=Depends(get_current_user),
) -> Dict:
    """Get recording history for a camera."""
    try:
        recorder = get_video_recorder()
        history = recorder.get_recording_history(camera_id, limit)
        return {
            "status": "success",
            "camera_id": camera_id,
            "count": len(history),
            "recordings": history,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/storage/stats")
async def get_storage_stats(current_user=Depends(get_current_user)) -> Dict:
    """Get storage usage statistics."""
    try:
        recorder = get_video_recorder()
        stats = recorder.get_storage_stats()
        return {
            "status": "success",
            "stats": stats,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/monitoring/metrics")
async def get_recording_metrics(current_user=Depends(get_current_user)) -> Dict:
    """Get recording performance metrics."""
    try:
        recorder = get_video_recorder()
        metrics = recorder.get_recording_metrics()
        return {
            "status": "success",
            "metrics": metrics,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/maintenance/run")
async def run_video_maintenance(current_user=Depends(get_current_user)) -> Dict:
    """Run retention/orphan cleanup immediately."""
    try:
        recorder = get_video_recorder()
        report = recorder.run_maintenance_cycle(trigger="api")
        return {
            "status": "success",
            "report": report,
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/search")
async def search_recordings(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    camera_id: Optional[int] = None,
    zone_id: Optional[int] = None,
    current_user=Depends(get_current_user),
) -> Dict:
    """Search recordings by date range, camera, or zone."""
    try:
        recorder = get_video_recorder()
        all_recordings = recorder.get_recording_history(camera_id or 0, limit=10000)

        filtered = []
        for rec in all_recordings:
            start_time = str(rec.get("start_time") or "")
            if start_date and start_time < start_date:
                continue
            if end_date and start_time > end_date:
                continue
            if zone_id is not None and rec.get("zone_id") != zone_id:
                continue
            filtered.append(rec)

        return {
            "status": "success",
            "total_found": len(filtered),
            "recordings": filtered[:100],
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/playback/{recording_id}")
async def prepare_playback(recording_id: str, current_user=Depends(get_current_user)) -> Dict:
    """Prepare recording for playback."""
    try:
        recorder = get_video_recorder()
        recording = recorder.get_recording_by_id(recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")
        return {
            "status": "success",
            "recording_id": recording_id,
            "playback_url": f"/api/video/stream/{recording_id}",
            "thumbnail": f"/api/video/thumbnail/{recording_id}",
            "duration_seconds": recording.get("duration_seconds", 0),
            "quality": recording.get("quality", "1080p"),
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stream/{recording_id}")
async def stream_recording(recording_id: str, current_user=Depends(get_current_user)) -> Dict:
    """Stream recording metadata (in production this would return HLS/DASH)."""
    try:
        recorder = get_video_recorder()
        recording = recorder.get_recording_by_id(recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")
        return {
            "status": "success",
            "stream_url": f"/media/recordings/{recording_id}.mp4",
            "format": "mp4",
            "metadata": recording,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/export/{recording_id}")
async def export_recording(
    recording_id: str,
    format: str = "mp4",
    current_user=Depends(get_current_user),
) -> Dict:
    """Export recording in various formats."""
    try:
        recorder = get_video_recorder()
        recording = recorder.get_recording_by_id(recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")
        return {
            "status": "success",
            "recording_id": recording_id,
            "format": format,
            "download_url": f"/api/video/download/{recording_id}?format={format}",
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{recording_id}")
async def get_recording(recording_id: str, current_user=Depends(get_current_user)) -> Dict:
    """Get details for a specific recording."""
    try:
        recorder = get_video_recorder()
        recording = recorder.get_recording_by_id(recording_id)
        if recording:
            return {
                "status": "success",
                "recording": recording,
                "timestamp": datetime.now().isoformat(),
            }
        raise HTTPException(status_code=404, detail=f"Recording {recording_id} not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{recording_id}")
async def delete_recording(recording_id: str, current_user=Depends(get_current_user)) -> Dict:
    """Delete a recording."""
    try:
        recorder = get_video_recorder()
        result = recorder.delete_recording(recording_id)
        if result.get("status") == "success":
            return result
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to delete recording"))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
