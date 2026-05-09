# vms/backend/main.py - Version avec imports corrigÃ©s

import sys
import os
import json
import logging
import time
from uuid import uuid4
import warnings

# Suppress pkg_resources deprecation warning (will be removed in Setuptools 85)
# This comes from external dependencies like face_recognition_models
warnings.filterwarnings("ignore", category=UserWarning, module=".*pkg_resources.*")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")

from vms.backend.core.logging_setup import configure_logging

configure_logging()
logger = logging.getLogger("falcon_ai_vision")

from fastapi import FastAPI, WebSocket, Request, Depends
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import importlib
import pkgutil
from vms.backend.core.rate_limiting import setup_rate_limiting, limiter
from vms.backend.core.monitoring import setup_monitoring
from vms.backend.core.security import get_current_user, hash_password, verify_token
from vms.backend.core.http_security import apply_security_headers, is_https_request, validate_request_headers
from vms.backend.core.health import live_health, ready_health
from vms.backend.core.audit import write_audit_log
from vms.backend.bootstrap import seed_admin_user as bootstrap_seed_admin_user
from vms.backend.core.config import settings
from vms.backend.core.database import SessionLocal
from vms.backend import crud, models
from vms.backend.services.metrics_service import start_metrics_loop, stop_metrics_loop
from vms.backend.services.camera_health_service import start_camera_health_monitor, stop_camera_health_monitor
# Importer le package routers via le package complet pour prÃ©server les imports relatifs internes
from vms.backend import routers as routers_pkg

def seed_admin_user() -> None:
    admin_username = settings.ADMIN_USERNAME
    admin_password = settings.ADMIN_PASSWORD or "admin123"
    if not admin_password.strip():
        raise ValueError("ADMIN_PASSWORD cannot be empty when seeding admin user")

    db = SessionLocal()
    try:
        existing_admin = crud.get_user_by_username(db, admin_username)
        if existing_admin:
            updated = False
            if not existing_admin.is_admin:
                existing_admin.is_admin = True
                updated = True
            if existing_admin.role != "admin":
                existing_admin.role = "admin"
                updated = True
            if not existing_admin.is_active:
                existing_admin.is_active = True
                updated = True
            if updated:
                db.commit()
                logger.info(f"âœ… Admin user '{admin_username}' verified and updated")
            else:
                logger.info(f"âœ… Admin user '{admin_username}' already exists")
            return

        tenant = crud.ensure_default_tenant(db)
        admin_user = models.User(
            username=admin_username,
            email=os.getenv("ADMIN_EMAIL", "admin@falcon.local").strip() or None,
            hashed_password=hash_password(admin_password),
            role="admin",
            is_active=True,
            is_admin=True,
            tenant_id=int(tenant.id),
        )
        db.add(admin_user)
        db.commit()
        logger.info(f"âœ… Admin user '{admin_username}' created on startup")
    except Exception as e:
        logger.warning(f"âš ï¸ Admin user seed failed: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("ðŸš€ SERVER STARTING")
    logger.info(f"ðŸ“‚ Current dir: {os.getcwd()}")
    logger.info(f"ðŸ“‚ Python path: {sys.path[0]}")
    try:
        from vms.backend.core.database import init_db
        init_report = init_db()
        logger.info("Database startup report: %s", init_report)
        logger.info("âœ… Database initialized (tables created if needed)")
        admin_report = bootstrap_seed_admin_user()
        logger.info("Admin bootstrap report: %s", admin_report)
    except Exception as e:
        logger.warning(f"âš ï¸ Database init skipped or failed: {e}")

    try:
        interval_sec = int(os.getenv("METRICS_BROADCAST_INTERVAL_SEC", "5"))
    except Exception:
        interval_sec = 5
    try:
        await start_metrics_loop(interval_sec=interval_sec)
    except Exception as e:
        logger.warning(f"âš ï¸ Metrics loop not started: {e}")
    try:
        start_camera_health_monitor()
    except Exception as e:
        logger.warning(f"âš ï¸ Camera health monitor not started: {e}")
    yield
    try:
        await stop_metrics_loop()
    except Exception:
        pass
    try:
        stop_camera_health_monitor()
    except Exception:
        pass
    logger.info("ðŸš€ SERVER SHUTTING DOWN")


app = FastAPI(
    title=settings.API_TITLE,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Normalize legacy malformed frontend URLs such as /api/api/*.
@app.middleware("http")
async def normalize_legacy_api_prefix(request: Request, call_next):
    path = request.scope.get("path", "")
    if path.startswith("/api/api/"):
        from fastapi.responses import RedirectResponse

        normalized_path = path[4:]
        query = request.scope.get("query_string", b"")
        if query:
            return RedirectResponse(url=f"{normalized_path}?{query.decode()}", status_code=307)
        return RedirectResponse(url=normalized_path, status_code=307)
    return await call_next(request)


def _extract_auth_payload(request: Request) -> dict | None:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    return verify_token(token)


@app.middleware("http")
async def request_context_and_audit(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()

    response = None
    status_code = 500
    payload = _extract_auth_payload(request)
    user_id = payload.get("user_id") if payload else None
    username = payload.get("sub") if payload else None

    try:
        is_valid, error_message = validate_request_headers(request)
        if not is_valid:
            response = JSONResponse(status_code=400, content={"detail": error_message})
            status_code = int(response.status_code)
            return response

        response = await call_next(request)
        status_code = int(response.status_code)
        return response
    finally:
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        if response is not None:
            response.headers["x-request-id"] = request_id
            apply_security_headers(response, is_https=is_https_request(request))

        if settings.REQUEST_LOGGING_ENABLED:
            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "user_id": user_id,
                },
            )

        if request.url.path.startswith("/api/"):
            # Exclude super-noisy non-business endpoints.
            if request.url.path not in {"/api", "/api/health", "/api/health/live", "/api/health/ready"}:
                write_audit_log(
                    event_type="api",
                    action="request",
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    user_id=user_id,
                    username=username,
                    ip_address=(request.client.host if request.client else None),
                    user_agent=request.headers.get("user-agent"),
                    request_id=request_id,
                    details={"latency_ms": latency_ms},
                )

# Global exception handler for consistent error responses.
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception",
        extra={"request_id": request_id, "path": request.url.path},
    )
    payload = {"detail": "Internal Server Error"}
    if request_id:
        payload["request_id"] = request_id
    if getattr(settings, "DEBUG", False):
        payload["error"] = str(exc)
    return JSONResponse(status_code=500, content=payload)

# Eager DB init for scripts/tests that instantiate app without lifespan context.
try:
    from vms.backend.core.database import init_db
    init_db()
except Exception as e:
    logger.warning(f"âš ï¸ Early database init skipped or failed: {e}")

# ============= RATE LIMITING & MONITORING =============
# Initialize rate limiting (slowapi)
app = setup_rate_limiting(app, enabled=True)

# Initialize monitoring (Prometheus metrics)
setup_monitoring(app, enabled=True)

# Use ALLOWED_ORIGINS from settings (environment-based configuration)
cors_origins = settings.ALLOWED_ORIGINS
if settings.IS_PROD and cors_origins == ["*"]:
    raise ValueError("ALLOWED_ORIGINS must be set to explicit origins in production (not '*').")
cors_allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() == "true"

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============= ENDPOINTS DE BASE =============
@app.get("/health")
async def health():
    return live_health()


@app.get("/health/live")
async def health_live():
    return live_health()


@app.get("/health/ready")
async def health_ready():
    return ready_health(timeout_ms=settings.HEALTH_READY_TIMEOUT_MS)


@app.get("/api/health/live")
async def api_health_live():
    return live_health()


@app.get("/api/health/ready")
async def api_health_ready():
    return ready_health(timeout_ms=settings.HEALTH_READY_TIMEOUT_MS)

@app.get("/api")
async def api_info():
    return {
        "name": "FALCON AI VISION",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/api/videos/recorded", include_in_schema=False)
async def legacy_recorded_videos(
    request: Request,
    current_user=Depends(get_current_user),
):
    """
    Legacy compatibility endpoint for older frontend bundles.
    Supports both query styles:
    - ?limit=10&skip=0
    - ?params[limit]=10&params[skip]=0
    """
    from vms.backend.services.video_recorder import get_video_recorder

    def pick(name: str, default: str | None = None) -> str | None:
        value = request.query_params.get(name)
        if value is None:
            value = request.query_params.get(f"params[{name}]")
        return value if value is not None else default

    try:
        limit = max(1, min(int(pick("limit", "10") or "10"), 500))
    except Exception:
        limit = 10
    try:
        skip = max(0, int(pick("skip", "0") or "0"))
    except Exception:
        skip = 0

    status_filter = (pick("status", "all") or "all").lower()
    date_from = pick("date_from")
    date_to = pick("date_to")
    sort_by = (pick("sort_by", "date") or "date").lower()

    recorder = get_video_recorder()
    rows = recorder.get_recording_history(camera_id=0, limit=10000)

    videos = []
    for rec in rows:
        rec_status = str(rec.get("status", "completed")).lower()
        if status_filter != "all" and rec_status != status_filter:
            continue

        recorded_at = rec.get("start_time") or rec.get("recorded_at") or ""
        rec_date = str(recorded_at)[:10] if recorded_at else ""
        if date_from and rec_date and rec_date < date_from:
            continue
        if date_to and rec_date and rec_date > date_to:
            continue

        videos.append(
            {
                "id": rec.get("recording_id"),
                "recording_id": rec.get("recording_id"),
                "camera_id": rec.get("camera_id", 0),
                "camera_name": rec.get("camera_name") or f"Camera {rec.get('camera_id', 'N/A')}",
                "file_path": rec.get("filepath") or rec.get("file_path"),
                "duration": rec.get("duration_seconds", 0),
                "file_size": int(float(rec.get("file_size_mb", 0) or 0) * 1024 * 1024),
                "recorded_at": recorded_at,
                "status": rec_status,
            }
        )

    if sort_by == "size":
        videos.sort(key=lambda v: v.get("file_size", 0), reverse=True)
    elif sort_by == "duration":
        videos.sort(key=lambda v: v.get("duration", 0), reverse=True)
    else:
        videos.sort(key=lambda v: v.get("recorded_at") or "", reverse=True)

    total = len(videos)
    paginated = videos[skip : skip + limit]

    return {
        "success": True,
        "count": total,
        "videos": paginated,
    }

# ============= IMPORTS DES ROUTERS =============
# Importer dynamiquement tous les modules du package routers et inclure leurs `router`
try:
    for finder, name, ispkg in pkgutil.iter_modules(routers_pkg.__path__):
        if name in {"vehicle", "websocket_ai_handler"}:
            logger.info(f"â„¹ï¸ Skipping deprecated router alias: {name}")
            continue
        try:
            module = importlib.import_module(f"vms.backend.routers.{name}")
            router = getattr(module, "router", None)
            if router:
                app.include_router(router)
                logger.info(f"âœ… Router {name}")
        except Exception as e:
            logger.warning(f"âš ï¸ Erreur inclusion router {name}: {e}")
except Exception as e:
    logger.error(f"âŒ Impossible d'Ã©numÃ©rer les routers: {e}")

# ============= WEB SOCKET =============
# NOTE: WebSocket endpoint /api/ws is provided by routers/ws.py
# (removed duplicate endpoint here to avoid conflicts)

# ============= SERVE FRONTEND SPA (PORT 5003) =============
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pathlib import Path

# Chemin vers le build frontend
FRONTEND_BUILD_DIR = Path(settings.FRONTEND_DIST_PATH)
if getattr(sys, "frozen", False):
    # In packaged mode, keep captures persistent next to the executable.
    DATA_DIR = Path(sys.executable).resolve().parent / "data"
else:
    DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_MEDIA_DIR = Path(settings.STORAGE_PATH)
STORAGE_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

# Serve captured snapshots and gallery media files.
app.mount("/media", StaticFiles(directory=DATA_DIR), name="media")
app.mount("/media-storage", StaticFiles(directory=STORAGE_MEDIA_DIR), name="media-storage")

# Public marketing website (static)
frontend_mode = (settings.FRONTEND_MODE or "website").strip().lower()
WEBSITE_DIR = Path(settings.FRONTEND_PATH) / "website"
if WEBSITE_DIR.exists():
    app.mount("/website", StaticFiles(directory=WEBSITE_DIR, html=True), name="website")

    @app.get("/website")
    async def serve_public_site_index():
        return FileResponse(WEBSITE_DIR / "index.html")

# Admin console (static)
ADMIN_DIR = Path(settings.FRONTEND_PATH) / "admin"
if ADMIN_DIR.exists():
    app.mount("/admin", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")

    @app.get("/admin")
    async def serve_admin_index():
        return FileResponse(ADMIN_DIR / "subscriptions.html")


if frontend_mode == "website" and WEBSITE_DIR.exists():
    app.mount("/", StaticFiles(directory=WEBSITE_DIR, html=True), name="website-root")


@app.api_route("/data/{legacy_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def redirect_legacy_data_path(legacy_path: str):
    return RedirectResponse(url=f"/media/{legacy_path}", status_code=307)

# VÃ©rifier que le frontend est compilÃ© et explicitement servi par le backend
if settings.SERVE_FRONTEND_FROM_BACKEND and frontend_mode == "spa" and FRONTEND_BUILD_DIR.exists() and (FRONTEND_BUILD_DIR / "index.html").exists():
    logger.info(f"âœ… Frontend SPA ready: {FRONTEND_BUILD_DIR}")

    # Mount static assets (JS, CSS, images, etc.)
    app.mount("/assets", StaticFiles(directory=FRONTEND_BUILD_DIR / "assets"), name="assets")

    # Serve index.html for root path
    @app.get("/")
    async def serve_index():
        return FileResponse(FRONTEND_BUILD_DIR / "index.html")

    # Catch-all SPA route: serve index.html for all non-API paths
    # NOTE: This MUST be the last route to avoid capturing /api/* requests
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Skip API routes and documentation routes (should not reach here due to route order)
        if full_path.startswith(("api/", "docs", "redoc", ".well-known")):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        
        # Serve index.html for all other routes (SPA routing)
        index_path = FRONTEND_BUILD_DIR / "index.html"
        return FileResponse(index_path) if index_path.exists() else JSONResponse(status_code=404, content={"detail": "Frontend not found"})

    # Handle non-GET requests on unknown SPA paths.
    # This avoids confusing 405 responses caused by the GET SPA catch-all route.
    @app.api_route(
        "/{full_path:path}",
        methods=["POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def spa_non_get_fallback(full_path: str, request: Request):
        cleaned_path = full_path.rstrip("/")
        legacy_auth_paths = {
            "login": "/api/auth/login",
            "register": "/api/auth/register",
            "logout": "/api/auth/logout",
        }

        if cleaned_path in legacy_auth_paths and request.method == "POST":
            return RedirectResponse(url=legacy_auth_paths[cleaned_path], status_code=307)

        if cleaned_path.startswith(("api", "docs", "redoc", ".well-known", "metrics")):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        return JSONResponse(
            status_code=404,
            content={"detail": "Not Found. Use /api/* endpoints for API requests."},
        )
elif settings.SERVE_FRONTEND_FROM_BACKEND and frontend_mode == "spa":
    logger.warning(
        f"âš ï¸ Frontend build not found: {FRONTEND_BUILD_DIR}. "
        "Run: cd falcon-ai-vision-platform/frontend && npm run build"
    )
else:
    logger.info(
        "â„¹ï¸ Frontend SPA serving disabled on backend "
        f"(environment={settings.ENVIRONMENT}, SERVE_FRONTEND_FROM_BACKEND={settings.SERVE_FRONTEND_FROM_BACKEND})"
    )

# Startup handled by lifespan

# ============= MAIN =============
if __name__ == "__main__":
    import uvicorn
    # DÃ©marrer l'app directement sur 0.0.0.0:5003 (conforme Ã  la demande)
    uvicorn.run(app, host="0.0.0.0", port=5003, reload=False, log_level="info")
