# vms/backend/routers/reporting_router.py - Reporting & Analytics (Sprint 7)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import logging

from ..services.reporting_service import get_reporting_service, ReportType, ReportFormat
from ..core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reporting", tags=["Reporting"])

class GenerateReportRequest(BaseModel):
    report_type: str  # detection_log, personnel_activity, etc.
    format: str = "json"  # json, csv, excel, pdf, html
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class ScheduleExportRequest(BaseModel):
    report_type: str
    format: str
    frequency: str  # daily, weekly, monthly
    time_of_day: str = "00:00"

@router.get("/templates", summary="List available report templates")
async def list_templates(current_user: dict = Depends(get_current_user)):
    """Liste les templates de rapports disponibles"""
    try:
        service = get_reporting_service()
        templates = {}
        for report_type, template in service.templates.items():
            templates[report_type.value] = template
        
        return {
            "status": "success",
            "templates": templates
        }
    except Exception as e:
        logger.error(f"Error listing templates: {e}")
        raise HTTPException(status_code=500, detail="Failed to list templates")

@router.post("/generate", summary="Generate a report")
async def generate_report(
    request: GenerateReportRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Génère un rapport
    
    Types: detection_log, personnel_activity, vehicle_activity, anomalies,
           daily_summary, weekly_summary, system_health
    
    Formats: json, csv, excel, pdf, html
    """
    try:
        service = get_reporting_service()
        
        report_type = ReportType[request.report_type.upper()]
        report_format = ReportFormat[request.format.upper()]
        
        # Données mockées pour l'exemple
        sample_data = [
            {"timestamp": datetime.now().isoformat(), "value": "Sample 1"},
            {"timestamp": datetime.now().isoformat(), "value": "Sample 2"}
        ]
        
        # Générer
        report = service.generate_report(
            report_type=report_type,
            data=sample_data,
            start_date=request.start_date,
            end_date=request.end_date
        )
        
        # Exporter
        filepath = service.export_report(report, report_format)
        
        return {
            "status": "success",
            "report_id": report['id'],
            "type": report_type.value,
            "format": report_format.value,
            "file_path": filepath,
            "row_count": report['row_count']
        }
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid report_type or format")
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate report")

@router.post("/export/json", summary="Export recent detections as JSON")
async def export_detections_json(
    hours: int = Query(24, ge=1, le=168),
    current_user: dict = Depends(get_current_user)
):
    """Exporte les détections récentes en JSON"""
    try:
        service = get_reporting_service()
        
        # Récupérer mock detections
        data = [
            {
                "id": i,
                "timestamp": (datetime.now() - timedelta(hours=i)).isoformat(),
                "type": "person" if i % 2 == 0 else "vehicle",
                "confidence": 0.95 + (i * 0.001 % 0.05)
            }
            for i in range(min(100, hours * 10))
        ]
        
        report = service.generate_report(
            report_type=ReportType.DETECTION_LOG,
            data=data,
            start_date=datetime.now() - timedelta(hours=hours),
            end_date=datetime.now()
        )
        
        filepath = service.export_report(report, ReportFormat.JSON)
        return FileResponse(filepath, media_type="application/json", filename="detections.json")
    
    except Exception as e:
        logger.error(f"Error exporting JSON: {e}")
        raise HTTPException(status_code=500, detail="Failed to export")

@router.post("/export/csv", summary="Export report as CSV")
async def export_csv(
    report_type: str = "detection_log",
    current_user: dict = Depends(get_current_user)
):
    """Exporte un rapport en CSV"""
    try:
        service = get_reporting_service()
        
        sample_data = [
            {"timestamp": datetime.now().isoformat(), "value": f"Row {i}"}
            for i in range(50)
        ]
        
        report = service.generate_report(
            report_type=ReportType[report_type.upper()],
            data=sample_data
        )
        
        filepath = service.export_report(report, ReportFormat.CSV)
        filename = f"{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        return FileResponse(filepath, media_type="text/csv", filename=filename)
    
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        raise HTTPException(status_code=500, detail="Failed to export")

@router.post("/export/excel", summary="Export report as Excel")
async def export_excel(
    report_type: str = "detection_log",
    current_user: dict = Depends(get_current_user)
):
    """Exporte un rapport en Excel"""
    try:
        service = get_reporting_service()
        
        sample_data = [
            {"timestamp": datetime.now().isoformat(), "value": f"Row {i}"}
            for i in range(50)
        ]
        
        report = service.generate_report(
            report_type=ReportType[report_type.upper()],
            data=sample_data
        )
        
        filepath = service.export_report(report, ReportFormat.EXCEL)
        filename = f"{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return FileResponse(filepath, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=filename)
    
    except ImportError:
        raise HTTPException(status_code=400, detail="openpyxl not installed")
    except Exception as e:
        logger.error(f"Error exporting Excel: {e}")
        raise HTTPException(status_code=500, detail="Failed to export")

@router.post("/schedule", summary="Schedule automatic export")
async def schedule_export(
    request: ScheduleExportRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Programme un export automatique
    
    Frequencies: daily, weekly, monthly
    Example: daily @ 00:00, weekly @ 09:00, etc.
    """
    try:
        service = get_reporting_service()
        
        job_id = service.schedule_export(
            report_type=ReportType[request.report_type.upper()],
            format=ReportFormat[request.format.upper()],
            frequency=request.frequency,
            time_of_day=request.time_of_day
        )
        
        # Sauvegarder
        service.save_scheduled_exports()
        
        return {
            "status": "success",
            "job_id": job_id,
            "message": f"Export scheduled: {request.frequency} @ {request.time_of_day}"
        }
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid report_type or format")
    except Exception as e:
        logger.error(f"Error scheduling export: {e}")
        raise HTTPException(status_code=500, detail="Failed to schedule export")

@router.get("/scheduled", summary="List scheduled exports")
async def list_scheduled_exports(current_user: dict = Depends(get_current_user)):
    """Liste les exports programmés"""
    try:
        service = get_reporting_service()
        exports = service.get_scheduled_exports()
        
        return {
            "status": "success",
            "total": len(exports),
            "exports": exports
        }
    except Exception as e:
        logger.error(f"Error listing exports: {e}")
        raise HTTPException(status_code=500, detail="Failed to list exports")

@router.delete("/scheduled/{job_id}", summary="Cancel scheduled export")
async def cancel_scheduled_export(
    job_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Annule un export programmé"""
    try:
        service = get_reporting_service()
        
        if service.cancel_export(job_id):
            service.save_scheduled_exports()
            return {
                "status": "success",
                "message": f"Export job {job_id} cancelled"
            }
        else:
            raise HTTPException(status_code=404, detail="Export job not found")
    
    except Exception as e:
        logger.error(f"Error cancelling export: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel export")

@router.get("/health", summary="Check reporting service health")
async def reporting_health(current_user: dict = Depends(get_current_user)):
    """Vérifier l'état du service de reporting"""
    try:
        service = get_reporting_service()
        return {
            "status": "healthy",
            "templates_available": len(service.templates),
            "scheduled_exports": len(service.scheduled_exports),
            "reports_directory": str(service.data_dir)
        }
    except Exception as e:
        logger.error(f"Error checking health: {e}")
        raise HTTPException(status_code=500, detail="Reporting service not available")
