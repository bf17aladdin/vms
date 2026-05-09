# vms/backend/routers/soc_dashboard_router.py - SOC Dashboard API Endpoints

import logging
import asyncio
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from datetime import datetime, timedelta
from dataclasses import asdict

from ..core.security import authenticate_websocket, get_current_user
from ..services.alert_config_service import AlertThreshold, get_alert_config_service
from ..services.soc_dashboard_service import get_soc_dashboard_service, OpsMetrics, AlertData, CameraActivity, CrossCameraRoute
from ..services.reporting_service import get_reporting_service, ReportFormat, ReportType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/soc", tags=["SOC Dashboard"])

# Pydantic models for API responses
class OpsMetricsResponse(BaseModel):
    cameras_active: int
    cameras_total: int
    cameras_degraded: int
    cameras_down: int
    faces_detected: int
    vehicles_detected: int
    alerts_triggered: int
    avg_latency_ms: float
    avg_fps: float
    unknown_rate: float
    false_positive_rate: float
    pending_unknowns: int
    processing_queue_size: int
    last_update: str

class AlertDataResponse(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    description: str
    camera_id: int
    camera_name: str
    timestamp: str
    acknowledged: bool
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[str]

class CameraActivityResponse(BaseModel):
    camera_id: int
    camera_name: str
    detections: int
    avg_latency: float
    fps: float
    alerts: int

class CrossCameraRouteResponse(BaseModel):
    from_camera: int
    to_camera: int
    transitions: int
    avg_time: float

class AcknowledgeAlertRequest(BaseModel):
    alert_id: str

# REST API Endpoints

@router.get("/metrics", response_model=OpsMetricsResponse, summary="Get current operational metrics")
async def get_operational_metrics(current_user: dict = Depends(get_current_user)):
    """Get current SOC operational metrics"""
    try:
        service = get_soc_dashboard_service()
        metrics = service.get_current_metrics()
        return OpsMetricsResponse(**metrics.__dict__)
    except Exception as e:
        logger.error(f"Error getting operational metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get operational metrics")

@router.get("/alerts", response_model=List[AlertDataResponse], summary="Get recent alerts")
async def get_recent_alerts(
    limit: int = Query(50, ge=1, le=100),
    acknowledged: Optional[bool] = None,
    severity: Optional[str] = Query(None, pattern="^(low|medium|high|critical)$"),
    current_user: dict = Depends(get_current_user)
):
    """Get recent alerts with optional filtering"""
    try:
        service = get_soc_dashboard_service()
        alerts = service.get_recent_alerts(limit)

        # Apply filters
        if acknowledged is not None:
            alerts = [a for a in alerts if a.acknowledged == acknowledged]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        return [AlertDataResponse(**alert.__dict__) for alert in alerts]
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        raise HTTPException(status_code=500, detail="Failed to get alerts")

@router.post("/alerts/acknowledge", summary="Acknowledge an alert")
async def acknowledge_alert(
    request: AcknowledgeAlertRequest,
    current_user: dict = Depends(get_current_user)
):
    """Acknowledge an alert"""
    try:
        service = get_soc_dashboard_service()
        success = service.acknowledge_alert(request.alert_id, current_user.get('username', 'unknown'))

        if not success:
            raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")

        return {"status": "success", "message": "Alert acknowledged"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error acknowledging alert: {e}")
        raise HTTPException(status_code=500, detail="Failed to acknowledge alert")

@router.get("/analytics/camera-activity", response_model=List[CameraActivityResponse], summary="Get camera activity analytics")
async def get_camera_activity_analytics(
    hours: int = Query(24, ge=1, le=168),
    current_user: dict = Depends(get_current_user)
):
    """Get camera activity analytics for the specified time period"""
    try:
        service = get_soc_dashboard_service()
        activities = service.get_camera_activities()
        return [CameraActivityResponse(**activity.__dict__) for activity in activities]
    except Exception as e:
        logger.error(f"Error getting camera activity analytics: {e}")
        raise HTTPException(status_code=500, detail="Failed to get camera activity analytics")

@router.get("/analytics/cross-camera-routes", response_model=List[CrossCameraRouteResponse], summary="Get cross-camera movement routes")
async def get_cross_camera_routes(
    hours: int = Query(24, ge=1, le=168),
    current_user: dict = Depends(get_current_user)
):
    """Get cross-camera movement route analytics"""
    try:
        service = get_soc_dashboard_service()
        routes = service.get_cross_camera_routes()
        return [CrossCameraRouteResponse(**route.__dict__) for route in routes]
    except Exception as e:
        logger.error(f"Error getting cross-camera routes: {e}")
        raise HTTPException(status_code=500, detail="Failed to get cross-camera routes")

# Alert Configuration Endpoints

@router.get("/config/thresholds", summary="Get all alert thresholds")
async def get_alert_thresholds(current_user: dict = Depends(get_current_user)):
    """Get all alert threshold configurations"""
    try:
        service = get_alert_config_service()
        thresholds = service.get_all_thresholds()
        return {"thresholds": [asdict(t) for t in thresholds]}
    except Exception as e:
        logger.error(f"Error getting alert thresholds: {e}")
        raise HTTPException(status_code=500, detail="Failed to get alert thresholds")

@router.get("/config/thresholds/{threshold_id}", summary="Get specific alert threshold")
async def get_alert_threshold(
    threshold_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific alert threshold configuration"""
    try:
        service = get_alert_config_service()
        threshold = service.get_threshold(threshold_id)
        if not threshold:
            raise HTTPException(status_code=404, detail="Threshold not found")
        return {"threshold": asdict(threshold)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting alert threshold: {e}")
        raise HTTPException(status_code=500, detail="Failed to get alert threshold")

@router.post("/config/thresholds", summary="Create new alert threshold")
async def create_alert_threshold(
    threshold_data: Dict[str, Any],
    current_user: dict = Depends(get_current_user)
):
    """Create a new alert threshold configuration"""
    try:
        service = get_alert_config_service()

        # Create threshold object
        threshold = AlertThreshold(
            **threshold_data,
            created_by=current_user.get('username', 'unknown')
        )

        # Validate
        errors = service.validate_threshold(threshold)
        if errors:
            raise HTTPException(status_code=400, detail={"errors": errors})

        # Create
        created = service.create_threshold(threshold)
        return {"threshold": asdict(created), "message": "Threshold created successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating alert threshold: {e}")
        raise HTTPException(status_code=500, detail="Failed to create alert threshold")

@router.put("/config/thresholds/{threshold_id}", summary="Update alert threshold")
async def update_alert_threshold(
    threshold_id: str,
    updates: Dict[str, Any],
    current_user: dict = Depends(get_current_user)
):
    """Update an existing alert threshold configuration"""
    try:
        service = get_alert_config_service()
        updated = service.update_threshold(threshold_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail="Threshold not found")
        return {"threshold": asdict(updated), "message": "Threshold updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating alert threshold: {e}")
        raise HTTPException(status_code=500, detail="Failed to update alert threshold")

@router.delete("/config/thresholds/{threshold_id}", summary="Delete alert threshold")
async def delete_alert_threshold(
    threshold_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete an alert threshold configuration"""
    try:
        service = get_alert_config_service()
        success = service.delete_threshold(threshold_id)
        if not success:
            raise HTTPException(status_code=404, detail="Threshold not found")
        return {"message": "Threshold deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting alert threshold: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete alert threshold")

@router.get("/config/settings", summary="Get global alert settings")
async def get_global_alert_settings(current_user: dict = Depends(get_current_user)):
    """Get global alert configuration settings"""
    try:
        service = get_alert_config_service()
        settings = service.get_global_settings()
        return {"settings": settings}
    except Exception as e:
        logger.error(f"Error getting global alert settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to get global alert settings")

@router.put("/config/settings", summary="Update global alert settings")
async def update_global_alert_settings(
    settings: Dict[str, Any],
    current_user: dict = Depends(get_current_user)
):
    """Update global alert configuration settings"""
    try:
        service = get_alert_config_service()
        updated = service.update_global_settings(settings)
        return {"settings": updated, "message": "Global settings updated successfully"}
    except Exception as e:
        logger.error(f"Error updating global alert settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to update global alert settings")

# Export Endpoints

@router.get("/export/metrics", summary="Export SOC metrics report")
async def export_soc_metrics(
    format: str = Query("pdf", pattern="^(pdf|excel|json|csv|html)$"),
    days: int = Query(7, ge=1, le=90),
    current_user: dict = Depends(get_current_user)
):
    """Export SOC operational metrics report"""
    try:
        soc_service = get_soc_dashboard_service()
        reporting_service = get_reporting_service()

        # Collect metrics data over the specified period
        metrics_data = []
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        current = start_date
        while current <= end_date:
            # Get metrics for this day (simplified - in real implementation would aggregate historical data)
            daily_metrics = soc_service.get_current_metrics()
            metrics_data.append({
                "date": current.strftime("%Y-%m-%d"),
                "cameras_active": daily_metrics.cameras_active,
                "cameras_total": daily_metrics.cameras_total,
                "faces_detected": daily_metrics.faces_detected,
                "vehicles_detected": daily_metrics.vehicles_detected,
                "alerts_triggered": daily_metrics.alerts_triggered,
                "avg_latency_ms": daily_metrics.avg_latency_ms,
                "avg_fps": daily_metrics.avg_fps,
                "unknown_rate": daily_metrics.unknown_rate,
                "false_positive_rate": daily_metrics.false_positive_rate
            })
            current += timedelta(days=1)

        # Generate report
        report = reporting_service.generate_report(
            ReportType.SYSTEM_HEALTH,
            metrics_data,
            start_date,
            end_date
        )

        # Export report
        format_enum = ReportFormat(format)
        filepath = reporting_service.export_report(report, format_enum)

        return {
            "message": "SOC metrics report exported successfully",
            "filepath": filepath,
            "format": format,
            "report_id": report["id"]
        }
    except Exception as e:
        logger.error(f"Error exporting SOC metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to export SOC metrics")

@router.get("/export/alerts", summary="Export alerts report")
async def export_alerts_report(
    format: str = Query("pdf", pattern="^(pdf|excel|json|csv|html)$"),
    days: int = Query(7, ge=1, le=90),
    severity: Optional[str] = Query(None, pattern="^(low|medium|high|critical)$"),
    current_user: dict = Depends(get_current_user)
):
    """Export alerts report with optional filtering"""
    try:
        soc_service = get_soc_dashboard_service()
        reporting_service = get_reporting_service()

        # Get alerts data
        alerts = soc_service.get_recent_alerts(1000)  # Get more alerts for reporting

        # Filter by date and severity
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        filtered_alerts = []
        for alert in alerts:
            alert_datetime = datetime.fromisoformat(alert.timestamp.replace('Z', '+00:00'))
            if alert_datetime < start_date or alert_datetime > end_date:
                continue
            if severity and alert.severity != severity:
                continue

            filtered_alerts.append({
                "timestamp": alert.timestamp,
                "type": alert.type,
                "severity": alert.severity,
                "title": alert.title,
                "description": alert.description,
                "camera_id": alert.camera_id,
                "camera_name": alert.camera_name,
                "acknowledged": alert.acknowledged,
                "acknowledged_by": alert.acknowledged_by or "",
                "acknowledged_at": alert.acknowledged_at or ""
            })

        # Generate report
        report = reporting_service.generate_report(
            ReportType.ANOMALIES,
            filtered_alerts,
            start_date,
            end_date
        )

        # Export report
        format_enum = ReportFormat(format)
        filepath = reporting_service.export_report(report, format_enum)

        return {
            "message": "Alerts report exported successfully",
            "filepath": filepath,
            "format": format,
            "report_id": report["id"],
            "alert_count": len(filtered_alerts)
        }
    except Exception as e:
        logger.error(f"Error exporting alerts report: {e}")
        raise HTTPException(status_code=500, detail="Failed to export alerts report")

@router.get("/export/analytics", summary="Export analytics report")
async def export_analytics_report(
    format: str = Query("pdf", pattern="^(pdf|excel|json|csv|html)$"),
    days: int = Query(7, ge=1, le=90),
    current_user: dict = Depends(get_current_user)
):
    """Export comprehensive analytics report"""
    try:
        soc_service = get_soc_dashboard_service()
        reporting_service = get_reporting_service()

        # Collect comprehensive analytics data
        analytics_data = []

        # Camera activity data
        camera_activities = soc_service.get_camera_activities()
        for activity in camera_activities:
            analytics_data.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "metric_type": "camera_activity",
                "camera_id": activity.camera_id,
                "camera_name": activity.camera_name,
                "detections": activity.detections,
                "avg_latency": activity.avg_latency,
                "fps": activity.fps,
                "alerts": activity.alerts
            })

        # Cross-camera routes
        routes = soc_service.get_cross_camera_routes()
        for route in routes:
            analytics_data.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "metric_type": "cross_camera_route",
                "from_camera": route.from_camera,
                "to_camera": route.to_camera,
                "transitions": route.transitions,
                "avg_time": route.avg_time
            })

        # Generate report
        report = reporting_service.generate_report(
            ReportType.DAILY_SUMMARY,
            analytics_data,
            datetime.now() - timedelta(days=days),
            datetime.now()
        )

        # Export report
        format_enum = ReportFormat(format)
        filepath = reporting_service.export_report(report, format_enum)

        return {
            "message": "Analytics report exported successfully",
            "filepath": filepath,
            "format": format,
            "report_id": report["id"],
            "data_points": len(analytics_data)
        }
    except Exception as e:
        logger.error(f"Error exporting analytics report: {e}")
        raise HTTPException(status_code=500, detail="Failed to export analytics report")

# WebSocket endpoint for real-time updates
@router.websocket("/ws")
async def soc_dashboard_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time SOC dashboard updates"""
    current_user = await authenticate_websocket(websocket)
    if current_user is None:
        return

    await websocket.accept()

    try:
        # Send initial data
        service = get_soc_dashboard_service()
        metrics = service.get_current_metrics()
        alerts = service.get_recent_alerts(10)

        await websocket.send_json({
            "type": "initial_data",
            "user": current_user.get("sub") or current_user.get("username") or current_user.get("user_id"),
            "metrics": asdict(metrics),
            "alerts": [asdict(alert) for alert in alerts]
        })

        # Keep connection alive and send periodic updates
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
                if message.strip().lower() == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})
                    continue
            except asyncio.TimeoutError:
                pass

            metrics = service.get_current_metrics()
            alerts = service.get_recent_alerts(10)
            await websocket.send_json({
                "type": "metrics_update",
                "metrics": asdict(metrics),
                "alerts": [asdict(alert) for alert in alerts]
            })

    except WebSocketDisconnect:
        logger.info("SOC Dashboard WebSocket client disconnected")
    except Exception as e:
        logger.error(f"SOC Dashboard WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass
