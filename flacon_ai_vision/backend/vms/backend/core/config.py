# vms/backend/core/config.py - Configuration centralisée

import os
import sys
from pathlib import Path
from typing import Optional

# Resolve a stable writable root for both source and packaged (PyInstaller) modes.
if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    BACKEND_DIR = PROJECT_ROOT
else:
    # New platform layout:
    # falcon-ai-vision-platform/backend/vms/backend/core/config.py
    PROJECT_ROOT = Path(__file__).resolve().parents[4]
    BACKEND_DIR = PROJECT_ROOT / "backend"
DB_DIR = BACKEND_DIR / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_DATA_DIR = PROJECT_ROOT / "data"
LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_SQLITE_DB_PATH = LOCAL_DATA_DIR / "falcon.db"

class Settings:
    """Configuration globale de l'application"""

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() == "true"

    # API
    API_TITLE: str = "FALCON AI VISION"
    API_DESCRIPTION: str = "Backend API + Frontend Statique FALCON AI VISION"
    API_VERSION: str = "2.0.0"
    
    # Database - defaults to project-local SQLite for local/demo workflows.
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{DEFAULT_SQLITE_DB_PATH.as_posix()}",
    )

    # Admin bootstrap user (used on startup if no admin exists)
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")
    
    # Security
    _DEFAULT_DEV_SECRET = "dev-secret-change-me"
    _RAW_SECRET = os.getenv("SECRET_KEY", "").strip()
    SECRET_KEY: str = _RAW_SECRET or _DEFAULT_DEV_SECRET
    SECRET_KEY_PREVIOUS: str = os.getenv("SECRET_KEY_PREVIOUS", "").strip()
    _RAW_SECRET_FALLBACKS = os.getenv("SECRET_KEY_FALLBACKS", "").strip()
    SECRET_KEY_FALLBACKS: list[str] = []
    if SECRET_KEY_PREVIOUS:
        SECRET_KEY_FALLBACKS.append(SECRET_KEY_PREVIOUS)
    if _RAW_SECRET_FALLBACKS:
        for item in _RAW_SECRET_FALLBACKS.split(","):
            key = item.strip()
            if key and key not in SECRET_KEY_FALLBACKS and key != SECRET_KEY:
                SECRET_KEY_FALLBACKS.append(key)
    SECRET_KEYS: list[str] = [SECRET_KEY] + [
        key for key in SECRET_KEY_FALLBACKS if key and key != SECRET_KEY
    ]
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    REFRESH_TOKEN_ROTATE: bool = os.getenv("REFRESH_TOKEN_ROTATE", "true").lower() == "true"

    # CORS - Environment-based allowlist for security
    _ALLOWED_ORIGINS_RAW = os.getenv("ALLOWED_ORIGINS", "").strip()
    if _ALLOWED_ORIGINS_RAW:
        ALLOWED_ORIGINS: list[str] = [
            item.strip() for item in _ALLOWED_ORIGINS_RAW.split(",") if item.strip()
        ]
    else:
        # Default to localhost for development (includes common dev ports)
        ALLOWED_ORIGINS: list[str] = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173"
        ]

    # HTTP security headers + host/https enforcement
    _ALLOWED_HOSTS_RAW = os.getenv("ALLOWED_HOSTS", "").strip()
    if _ALLOWED_HOSTS_RAW:
        ALLOWED_HOSTS: list[str] = [
            item.strip().lower() for item in _ALLOWED_HOSTS_RAW.split(",") if item.strip()
        ]
    else:
        ALLOWED_HOSTS: list[str] = []
    SECURITY_HEADERS_ENABLED: bool = _env_bool("SECURITY_HEADERS_ENABLED", True)
    HSTS_MAX_AGE: int = int(os.getenv("HSTS_MAX_AGE", "31536000"))
    HSTS_INCLUDE_SUBDOMAINS: bool = _env_bool("HSTS_INCLUDE_SUBDOMAINS", True)
    
    # Server
    HOST: str = os.getenv("HOST", "127.0.0.1")
    # Prefer explicit BACKEND_PORT; fallback to PORT then default 5003
    PORT: int = int(os.getenv("BACKEND_PORT", os.getenv("PORT", 5003)))
    ENVIRONMENT: str = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower()
    IS_PROD: bool = ENVIRONMENT in {"production", "prod"}
    _REQUIRE_HTTPS_RAW = os.getenv("REQUIRE_HTTPS")
    if _REQUIRE_HTTPS_RAW is None:
        REQUIRE_HTTPS: bool = IS_PROD
    else:
        REQUIRE_HTTPS: bool = _env_bool("REQUIRE_HTTPS", IS_PROD)
    DEBUG: bool = _env_bool("DEBUG", not IS_PROD)
    RELOAD: bool = _env_bool("RELOAD", not IS_PROD)

    _serve_frontend_from_backend_raw: str = os.getenv("SERVE_FRONTEND_FROM_BACKEND", "").strip().lower()
    if _serve_frontend_from_backend_raw:
        SERVE_FRONTEND_FROM_BACKEND: bool = _serve_frontend_from_backend_raw in {"1", "true", "yes", "on"}
    else:
        SERVE_FRONTEND_FROM_BACKEND: bool = getattr(sys, "frozen", False) or ENVIRONMENT in {"production", "prod"}

    # Frontend
    FRONTEND_MODE: str = os.getenv("FRONTEND_MODE", "website").strip().lower()

    # Runtime
    HEALTH_READY_TIMEOUT_MS: int = int(os.getenv("HEALTH_READY_TIMEOUT_MS", "1200"))
    REQUEST_LOGGING_ENABLED: bool = os.getenv("REQUEST_LOGGING_ENABLED", "true").lower() == "true"
    LOG_JSON: bool = os.getenv("LOG_JSON", "true").lower() == "true"
    LOG_FILE_PATH: str = os.getenv("LOG_FILE_PATH", str(PROJECT_ROOT / "logs" / "backend.log"))

    # AI runtime controls
    TIMEOUT_IA: float = float(os.getenv("TIMEOUT_IA", os.getenv("AI_TIMEOUT_SEC", "4.0")))
    AI_OBJECT_TIMEOUT_SEC: float = float(os.getenv("AI_OBJECT_TIMEOUT_SEC", str(TIMEOUT_IA)))
    AI_MOTION_TIMEOUT_SEC: float = float(os.getenv("AI_MOTION_TIMEOUT_SEC", str(TIMEOUT_IA)))
    AI_OBJECT_RETRY: int = int(os.getenv("AI_OBJECT_RETRY", "1"))
    AI_MOTION_RETRY: int = int(os.getenv("AI_MOTION_RETRY", "1"))
    MAX_GPU_JOBS: int = int(os.getenv("MAX_GPU_JOBS", os.getenv("AI_MAX_CONCURRENT_JOBS", "2")))

    # Stream/watchdog controls
    STREAM_RETRY: int = int(os.getenv("STREAM_RETRY", os.getenv("CAMERA_REOPEN_AFTER_FAILURES", "3")))
    CAMERA_STREAM_STALE_SEC: float = float(os.getenv("CAMERA_STREAM_STALE_SEC", "6.0"))
    CAMERA_REOPEN_COOLDOWN_SEC: float = float(os.getenv("CAMERA_REOPEN_COOLDOWN_SEC", "1.0"))
    FPS_TARGET: int = int(os.getenv("FPS_TARGET", "30"))

    # Rate limiting
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
    RATE_LIMIT_WINDOW_SECONDS: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
    RATE_LIMIT_STORAGE_URI: str = os.getenv("RATE_LIMIT_STORAGE_URI", os.getenv("REDIS_URL", "memory://"))
    
    # Paths - Frontend is in falcon-ai-vision-platform/frontend (built version in dist/)
    # For production: serve from dist/ (compiled)
    # For development: serve from source files
    FRONTEND_PATH: str = str(PROJECT_ROOT / "frontend")
    FRONTEND_DIST_PATH: str = str(Path(FRONTEND_PATH) / "dist")
    TEMPLATES_PATH: str = str(Path(FRONTEND_PATH) / "legacy" / "templates")
    STATIC_PATH: str = str(Path(FRONTEND_PATH) / "legacy" / "static")
    STORAGE_PATH: str = str(BACKEND_DIR / "storage")

    # Video recording / retention
    VIDEO_RETENTION_DAYS: int = int(os.getenv("VIDEO_RETENTION_DAYS", "30"))
    VIDEO_AUTO_PURGE_ENABLED: bool = os.getenv("VIDEO_AUTO_PURGE_ENABLED", "true").lower() == "true"
    VIDEO_PURGE_INTERVAL_SECONDS: int = int(os.getenv("VIDEO_PURGE_INTERVAL_SECONDS", "3600"))
    VIDEO_ORPHAN_FILE_GRACE_SECONDS: int = int(os.getenv("VIDEO_ORPHAN_FILE_GRACE_SECONDS", "300"))
    VIDEO_START_MAX_RETRIES: int = int(os.getenv("VIDEO_START_MAX_RETRIES", "3"))
    VIDEO_START_RETRY_DELAY_SECONDS: float = float(os.getenv("VIDEO_START_RETRY_DELAY_SECONDS", "0.35"))

    # Alert retention
    ALERT_RETENTION_DAYS: int = int(os.getenv("ALERT_RETENTION_DAYS", "90"))

# Instance globale des settings
settings = Settings()

if settings.IS_PROD:
    insecure_defaults = {
        Settings._DEFAULT_DEV_SECRET,
        "your-secret-key-change-in-production-12345",
        "your-super-secret-key-change-me-in-production",
    }
    for key in settings.SECRET_KEYS:
        if key and key in insecure_defaults:
            raise ValueError(
                "SECRET_KEY/SECRET_KEY_PREVIOUS must be set to strong values in production. "
                "Update your environment configuration."
            )
