# vms/backend/routers/cameras.py - Routes caméras

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from ..core.database import get_db
from ..core.security import get_current_user, require_viewer, require_operator, require_supervisor
from ..services.camera_service import CameraService
from ..services.stream_service import StreamService
from .. import schemas
from .. import models
from ..services.setup_config_service import get_setup_config_service
from ..services.subscription_service import resolve_subscription_for_tenant, get_tenant_plan_limits
import io
import asyncio
from datetime import datetime

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

# Routes
@router.get("", response_model=dict)
def list_cameras(
    skip: int = 0,
    limit: int = 100,
    site_id: Optional[int] = None,
    active_only: bool = False,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db)
):
    """Lister toutes les cam?ras"""
    try:
        tenant_id = current_user.get("tenant_id")
        if site_id is not None:
            cameras = CameraService.get_cameras_by_site(db, site_id=site_id, active_only=active_only, tenant_id=tenant_id)
            cameras = cameras[skip : skip + limit]
        elif active_only:
            cameras = CameraService.get_active_cameras(db, tenant_id=tenant_id)[skip : skip + limit]
        else:
            cameras = CameraService.get_all_cameras(db, skip=skip, limit=limit, tenant_id=tenant_id)
        return {
            "status": "success",
            "count": len(cameras),
            "cameras": cameras,
            "message": "Cameras retrieved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/active", response_model=dict)
def list_active_cameras(
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db)
):
    """Lister les cam?ras actives"""
    try:
        tenant_id = current_user.get("tenant_id")
        cameras = CameraService.get_active_cameras(db, tenant_id=tenant_id)
        return {
            "status": "success",
            "count": len(cameras),
            "cameras": cameras,
            "message": "Active cameras retrieved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("", response_model=dict)
def create_camera(
    payload: schemas.CameraCreate,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Cr?er une nouvelle cam?ra"""
    try:
        tenant_id = current_user.get("tenant_id")
        subscription = resolve_subscription_for_tenant(db, tenant_id)
        plan_limits = get_tenant_plan_limits(subscription.get("tier") or "starter")
        limit = plan_limits.get("camera_limit")

        if isinstance(limit, int) and limit > 0:
            query = db.query(models.Camera)
            if tenant_id is not None:
                query = query.filter(models.Camera.tenant_id == tenant_id)
            current_count = int(query.count())
            if current_count >= limit:
                raise HTTPException(
                    status_code=400,
                    detail=f"Camera limit reached for current plan ({limit}).",
                )
        else:
            setup_config = get_setup_config_service().get_config()
            fallback_limit = setup_config.get("camera_limit")
            if isinstance(fallback_limit, int) and fallback_limit > 0:
                query = db.query(models.Camera)
                if tenant_id is not None:
                    query = query.filter(models.Camera.tenant_id == tenant_id)
                current_count = int(query.count())
                if current_count >= fallback_limit:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Camera limit reached for current profile ({fallback_limit}).",
                    )

        owner_id = current_user.get("user_id") or current_user.get("id", 1)
        camera = CameraService.create_camera(db, payload, owner_id, tenant_id=tenant_id)
        return {
            "status": "success",
            "id": camera["id"],
            "camera": camera,
            "message": "Camera created successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/{camera_id}", response_model=dict)
def get_camera(
    camera_id: int,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db)
):
    """R?cup?rer une cam?ra sp?cifique"""
    try:
        tenant_id = current_user.get("tenant_id")
        camera = CameraService.get_camera(db, camera_id, tenant_id=tenant_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
        return {
            "status": "success",
            "camera": camera,
            "message": "Camera retrieved successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.put("/{camera_id}", response_model=dict)
def update_camera(
    camera_id: int,
    payload: schemas.CameraUpdate,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Mettre ? jour une cam?ra"""
    try:
        tenant_id = current_user.get("tenant_id")
        camera = CameraService.update_camera(db, camera_id, payload, tenant_id=tenant_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
        return {
            "status": "success",
            "camera": camera,
            "message": "Camera updated successfully"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.delete("/{camera_id}", response_model=dict)
def delete_camera(
    camera_id: int,
    current_user: dict = Depends(require_supervisor),
    db: Session = Depends(get_db)
):
    """Supprimer une cam?ra"""
    try:
        tenant_id = current_user.get("tenant_id")
        success = CameraService.delete_camera(db, camera_id, tenant_id=tenant_id)
        if not success:
            raise HTTPException(status_code=404, detail="Camera not found")
        return {
            "status": "success",
            "id": camera_id,
            "message": "Camera deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/{camera_id}/activity", response_model=dict)
def update_camera_activity(
    camera_id: int,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Mettre ? jour l'activit? de la cam?ra"""
    try:
        tenant_id = current_user.get("tenant_id")
        camera = CameraService.update_camera_activity(db, camera_id, tenant_id=tenant_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
        return {
            "status": "success",
            "camera": camera,
            "message": "Camera activity updated successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/{camera_id}/test-connection", response_model=dict)
def test_camera_connection(
    camera_id: int,
    test_data: schemas.CameraTestConnectionRequest = None,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Tester la connexion ? une cam?ra
    
    Peut utiliser :
    - Les param?tres fournis dans le body (pour tester avec d'autres credentials)
    - Ou les param?tres existants de la cam?ra
    """
    try:
        if test_data is None:
            test_data = schemas.CameraTestConnectionRequest()
        tenant_id = current_user.get("tenant_id")
        result = CameraService.test_camera_connection(db, camera_id, test_data, tenant_id=tenant_id)
        return {
            "camera_id": camera_id,
            "status": result.get("status"),
            "message": result.get("message"),
            "latency_ms": result.get("latency_ms"),
            "camera_info": result.get("camera_info"),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/discovery/scan", response_model=dict)
def discover_cameras(
    payload: Optional[schemas.CameraDiscoveryRequest] = None,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Scanner le reseau pour detecter les cameras RTSP candidates."""
    try:
        discovery_payload = payload or schemas.CameraDiscoveryRequest()
        tenant_id = current_user.get("tenant_id")
        result = CameraService.discover_cameras(db, discovery_payload, tenant_id=tenant_id)
        return {
            **result,
            "status": result.get("status", "success"),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/discovery/analyze", response_model=dict)
def analyze_discovered_cameras(
    payload: schemas.CameraDiscoveryAnalyzeRequest,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db),
):
    """Return preview and health metrics for discovered devices."""
    try:
        tenant_id = current_user.get("tenant_id")
        result = CameraService.analyze_discovered_cameras(
            db,
            payload,
            tenant_id=tenant_id,
        )
        return {
            **result,
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/discovery/connect", response_model=dict)
def connect_discovered_cameras(
    payload: schemas.CameraDiscoveryConnectRequest,
    current_user: dict = Depends(require_operator),
    db: Session = Depends(get_db),
):
    """Creer ou mettre a jour des cameras depuis les resultats de decouverte reseau."""
    try:
        tenant_id = current_user.get("tenant_id")
        owner_id = current_user.get("user_id") or current_user.get("id", 1)
        result = CameraService.connect_discovered_cameras(
            db,
            payload,
            owner_id=owner_id,
            tenant_id=tenant_id,
        )
        return {
            **result,
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{camera_id}/thumbnail")
def get_camera_thumbnail(
    camera_id: int,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db)
):
    """
    R?cup?rer une image de la cam?ra (thumbnail)
    Retourne une image JPEG g?n?r?e ou un placeholder
    """
    try:
        tenant_id = current_user.get("tenant_id")
        camera = CameraService.get_camera(db, camera_id, tenant_id=tenant_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        stream_source = CameraService.resolve_camera_stream_source(db, camera_id, tenant_id=tenant_id)
        image_data = StreamService.get_camera_thumbnail(camera_id, stream_source)

        return StreamingResponse(
            io.BytesIO(image_data),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/{camera_id}/snapshot")
def get_camera_snapshot(
    camera_id: int,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db)
):
    """Alias snapshot camera pour tests admin/panel."""
    try:
        tenant_id = current_user.get("tenant_id")
        camera = CameraService.get_camera(db, camera_id, tenant_id=tenant_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        stream_source = CameraService.resolve_camera_stream_source(db, camera_id, tenant_id=tenant_id)
        image_data = StreamService.get_camera_thumbnail(camera_id, stream_source)
        return StreamingResponse(
            io.BytesIO(image_data),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/{camera_id}/stream")
async def stream_camera(
    camera_id: int,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db)
):
    """
    Stream vid?o MJPEG de la cam?ra
    Envoie une s?quence d'images JPEG s?par?es par des limites MJPEG
    """
    try:
        tenant_id = current_user.get("tenant_id")
        camera = CameraService.get_camera(db, camera_id, tenant_id=tenant_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
        stream_source = CameraService.resolve_camera_stream_source(db, camera_id, tenant_id=tenant_id)
        if not stream_source:
            raise HTTPException(status_code=400, detail="No RTSP source configured")

        async def mjpeg_stream():
            """G?n?rateur pour le stream MJPEG"""
            while True:
                try:
                    image_data = StreamService.get_camera_thumbnail(camera_id, stream_source)

                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-length: " + str(len(image_data)).encode() + b"\r\n\r\n"
                        + image_data + b"\r\n"
                    )

                    await asyncio.sleep(0.5)
                except Exception as e:
                    print(f"Erreur dans le stream: {e}")
                    break

        return StreamingResponse(
            mjpeg_stream(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/{camera_id}/info")
def get_camera_info(
    camera_id: int,
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db)
):
    """R?cup?rer les informations d?taill?es de la cam?ra"""
    try:
        tenant_id = current_user.get("tenant_id")
        camera = CameraService.get_camera(db, camera_id, tenant_id=tenant_id)
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        return {
            "status": "success",
            "camera": camera,
            "stream_url": f"/api/cameras/{camera_id}/stream",
            "thumbnail_url": f"/api/cameras/{camera_id}/thumbnail",
            "timestamp": datetime.now().isoformat(),
            "message": "Camera information retrieved successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.get("/stream/all")
def stream_all_cameras(
    current_user: dict = Depends(require_viewer),
    db: Session = Depends(get_db)
):
    """R?cup?rer les URLs de streaming pour toutes les cam?ras"""
    try:
        tenant_id = current_user.get("tenant_id")
        cameras = CameraService.get_active_cameras(db, tenant_id=tenant_id)
        return {
            "status": "success",
            "count": len(cameras),
            "streams": [
                {
                    "id": camera["id"],
                    "name": camera["name"],
                    "stream_url": f"/api/cameras/{camera['id']}/stream",
                    "thumbnail_url": f"/api/cameras/{camera['id']}/thumbnail"
                }
                for camera in cameras
            ],
            "message": "Stream URLs retrieved successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
