# vms/backend/core/database.py - SQLAlchemy and database helpers

import json
import os
import logging
import re
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

try:
    from pgvector.sqlalchemy import Vector as _PGVector  # noqa: F401

    _HAS_PGVECTOR_PY = True
except Exception:
    _HAS_PGVECTOR_PY = False

# Database setup
def _resolve_sqlite_file_path(database_url: str) -> Path | None:
    try:
        url = make_url(database_url)
    except Exception:
        return None
    if url.get_backend_name() != "sqlite":
        return None
    database = str(url.database or "").strip()
    if not database or database == ":memory:":
        return None
    candidate = Path(database)
    if candidate.is_absolute():
        return candidate
    return (PROJECT_ROOT / candidate).resolve()


_sqlite_file_path = _resolve_sqlite_file_path(settings.DATABASE_URL)
if _sqlite_file_path is not None:
    _sqlite_file_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
SESSION_LOCAL = SessionLocal
Base = declarative_base()


def get_db() -> Session:
    """Dependency to acquire a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _is_postgres_url(database_url: str) -> bool:
    return database_url.lower().startswith("postgresql")


def _normalize_migration_ddl(ddl: str, *, is_postgres: bool) -> str:
    """Normalize additive migration DDL for backend-specific SQL compatibility."""
    normalized = ddl.strip()
    if not is_postgres:
        return normalized

    # PostgreSQL rejects INTEGER literals as defaults for BOOLEAN columns.
    normalized = re.sub(
        r"\bBOOLEAN\s+DEFAULT\s+0\b",
        "BOOLEAN DEFAULT FALSE",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\bBOOLEAN\s+DEFAULT\s+1\b",
        "BOOLEAN DEFAULT TRUE",
        normalized,
        flags=re.IGNORECASE,
    )

    # Keep legacy DATETIME migration entries valid on PostgreSQL.
    normalized = re.sub(r"\bDATETIME\b", "TIMESTAMPTZ", normalized, flags=re.IGNORECASE)
    return normalized


def _decode_json_like(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None
    return None


def _extract_vehicle_profile_backfill_attrs(pipeline_meta):
    payload = _decode_json_like(pipeline_meta)
    if not isinstance(payload, dict):
        return (None, None, None, None)

    profile = payload.get("vehicle_profile")
    if not isinstance(profile, dict):
        profile = _decode_json_like(profile)
    if not isinstance(profile, dict):
        return (None, None, None, None)

    from vms.backend.services.vehicle_ai.vehicle_taxonomy import (
        normalize_vehicle_body_style,
        normalize_vehicle_brand,
        normalize_vehicle_color,
        normalize_vehicle_model,
    )

    dominant_color = normalize_vehicle_color(profile.get("dominant_color"))
    brand = normalize_vehicle_brand(profile.get("brand") or profile.get("make"))
    model = normalize_vehicle_model(profile.get("model"))
    body_style = normalize_vehicle_body_style(profile.get("body_style"))

    return (
        dominant_color if dominant_color != "unknown" else None,
        brand,
        model,
        body_style,
    )


def ensure_face_detection_appearance_schema(bind=None):
    """Additive migration for person-appearance fields on face detections."""
    bind = bind or engine
    inspector = inspect(bind)

    if "face_detections" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("face_detections")
    }
    column_definitions = {
        "person_bbox": "JSON",
        "appearance_top_color": "VARCHAR(32)",
        "appearance_bottom_color": "VARCHAR(32)",
        "has_backpack": "BOOLEAN",
        "has_hat": "BOOLEAN",
        "appearance_embedding": "JSON",
    }
    is_postgres = _is_postgres_url(settings.DATABASE_URL)

    with bind.begin() as connection:
        for column_name, ddl in column_definitions.items():
            if column_name in existing_columns:
                continue
            normalized_ddl = _normalize_migration_ddl(ddl, is_postgres=is_postgres)
            connection.exec_driver_sql(
                f"ALTER TABLE face_detections ADD COLUMN {column_name} {normalized_ddl}"
            )

        for statement in (
            """
            CREATE INDEX IF NOT EXISTS ix_face_detections_appearance_top_color
            ON face_detections (appearance_top_color)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_face_detections_appearance_bottom_color
            ON face_detections (appearance_bottom_color)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_face_detections_has_backpack
            ON face_detections (has_backpack)
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_face_detections_has_hat
            ON face_detections (has_hat)
            """,
        ):
            connection.exec_driver_sql(statement)


def get_database_startup_report(bind=None) -> dict:
    bind = bind or engine
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    required_tables = ("cameras", "users", "tenants")
    return {
        "database_url": settings.DATABASE_URL,
        "backend": (
            "postgresql"
            if _is_postgres_url(settings.DATABASE_URL)
            else ("sqlite" if "sqlite" in settings.DATABASE_URL.lower() else "other")
        ),
        "sqlite_path": str(_resolve_sqlite_file_path(settings.DATABASE_URL) or ""),
        "required_tables": {table: table in table_names for table in required_tables},
        "table_count": len(table_names),
    }


def init_db():
    """Initialize schema and run additive compatibility migrations."""
    # Ensure model classes are imported so Base.metadata includes all tables.
    from vms.backend import models as _models  # noqa: F401

    db_url = settings.DATABASE_URL.lower()
    is_sqlite = "sqlite" in db_url
    is_postgres = _is_postgres_url(db_url)
    pgvector_enabled = os.getenv("FACE_PGVECTOR_ENABLED", "true").lower() == "true"
    use_pgvector = bool(is_postgres and pgvector_enabled and _HAS_PGVECTOR_PY)

    if use_pgvector:
        with engine.begin() as conn:
            try:
                conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
                logger.info("DB extension ready: pgvector")
            except Exception as e:
                logger.warning("pgvector extension setup skipped: %s", e)

    Base.metadata.create_all(bind=engine)

    migrations = [
        ("users", "tenant_id", "INTEGER"),
        ("users", "role", "VARCHAR(20) DEFAULT 'operator'"),
        ("users", "last_login", "TIMESTAMP"),
        ("users", "setup_completed", "BOOLEAN DEFAULT FALSE"),
        ("users", "application_mode", "VARCHAR(20)"),
        ("users", "country_code", "VARCHAR(3)"),
        ("users", "timezone", "VARCHAR(50)"),
        ("tenants", "project_type", "VARCHAR(20) DEFAULT 'soc'"),
        ("subscriptions", "tenant_id", "INTEGER"),
        ("sites", "tenant_id", "INTEGER"),
        ("cameras", "tenant_id", "INTEGER"),
        ("zones", "tenant_id", "INTEGER"),
        ("events", "tenant_id", "INTEGER"),
        ("alert_rules", "tenant_id", "INTEGER"),
        ("notifications", "tenant_id", "INTEGER"),
        ("security_alerts", "tenant_id", "INTEGER"),
        ("sites", "code", "VARCHAR(40)"),
        ("sites", "description", "TEXT"),
        ("sites", "is_active", "BOOLEAN DEFAULT TRUE"),
        ("sites", "created_at", "TIMESTAMP"),
        ("sites", "updated_at", "TIMESTAMP"),
        ("zones", "site_id", "INTEGER"),
        ("zones", "zone_type", "VARCHAR(30) DEFAULT 'custom'"),
        ("zones", "is_blocked", "BOOLEAN DEFAULT FALSE"),
        ("zones", "block_reason", "VARCHAR(255)"),
        ("cameras", "site_id", "INTEGER"),
        ("cameras", "zone_id", "INTEGER"),
        ("cameras", "camera_type", "VARCHAR(20) DEFAULT 'mix'"),
        ("cameras", "is_enabled", "BOOLEAN DEFAULT TRUE"),
        ("cameras", "selection_role", "VARCHAR(40)"),
        ("cameras", "selection_score", "FLOAT"),
        ("cameras", "stream_validation_status", "VARCHAR(20)"),
        ("cameras", "stream_validation_message", "VARCHAR(255)"),
        ("cameras", "stream_codec", "VARCHAR(32)"),
        ("cameras", "stream_width", "INTEGER"),
        ("cameras", "stream_height", "INTEGER"),
        ("cameras", "stream_fps", "FLOAT"),
        ("cameras", "analysis_metadata", "JSON"),
        ("cameras", "last_snapshot_path", "VARCHAR(255)"),
        ("events", "site_id", "INTEGER"),
        ("events", "decision", "VARCHAR(30) DEFAULT 'review'"),
        ("vehicle_entries", "vehicle_registry_id", "INTEGER"),
        ("vehicle_registry", "matricule", "VARCHAR(20)"),
        ("vehicle_registry", "marque", "VARCHAR(50)"),
        ("vehicle_registry", "modele", "VARCHAR(50)"),
        ("vehicle_registry", "categorie", "VARCHAR(50) DEFAULT 'civil'"),
        ("vehicle_registry", "unite", "VARCHAR(100)"),
        ("vehicle_registry", "sous_categorie_militaire", "VARCHAR(30)"),
        ("vehicle_registry", "statut", "VARCHAR(50) DEFAULT 'actif'"),
        ("vehicle_registry", "photo_path", "VARCHAR(255)"),
        ("vehicle_registry", "date_enregistrement", "DATETIME"),
        ("vehicle_registry", "date_modification", "DATETIME"),
        ("vehicle_registry", "is_whitelisted", "BOOLEAN DEFAULT 0"),
        ("vehicle_registry", "is_blacklisted", "BOOLEAN DEFAULT 0"),
        ("vehicle_registry", "blacklist_reason", "VARCHAR(255)"),
        ("vehicle_registry", "is_flagged", "BOOLEAN DEFAULT 0"),
        ("vehicle_registry", "flag_reason", "VARCHAR(255)"),
        ("personnel", "unite", "VARCHAR(100)"),
        ("personnel", "photo_path", "VARCHAR(255)"),
        ("personnel", "face_embedding", "BLOB"),
        ("personnel", "custom_fields", "JSON"),
        ("face_encodings", "face_image_id", "INTEGER"),
        ("face_encodings", "embedding_dim", "INTEGER DEFAULT 512"),
        ("face_encodings", "model_name", "VARCHAR(50) DEFAULT 'arcface'"),
        ("face_encodings", "is_active", "BOOLEAN DEFAULT 1"),
        ("face_encodings", "detector_score", "FLOAT"),
        ("face_detections", "track_id", "INTEGER"),
        ("face_detections", "person_bbox", "JSON"),
        ("face_detections", "appearance_top_color", "VARCHAR(32)"),
        ("face_detections", "appearance_bottom_color", "VARCHAR(32)"),
        ("face_detections", "has_backpack", "BOOLEAN"),
        ("face_detections", "has_hat", "BOOLEAN"),
        ("face_detections", "appearance_embedding", "JSON"),
        ("vehicle_events", "plate_number", "VARCHAR(50)"),
        ("vehicle_events", "plate_type", "VARCHAR(20) DEFAULT 'unknown'"),
        ("vehicle_events", "confidence", "FLOAT DEFAULT 0"),
        ("vehicle_events", "vehicle_detected", "BOOLEAN DEFAULT 1"),
        ("vehicle_events", "vehicle_type", "VARCHAR(50)"),
        ("vehicle_events", "body_style", "VARCHAR(50)"),
        ("vehicle_events", "dominant_color", "VARCHAR(30)"),
        ("vehicle_events", "brand", "VARCHAR(100)"),
        ("vehicle_events", "model", "VARCHAR(100)"),
        ("vehicle_events", "vehicle_confidence", "FLOAT DEFAULT 0"),
        ("vehicle_events", "vehicle_bbox", "JSON"),
        ("vehicle_events", "plate_confidence", "FLOAT DEFAULT 0"),
        ("vehicle_events", "plate_bbox", "JSON"),
        ("vehicle_events", "raw_plate_text", "VARCHAR(120)"),
        ("vehicle_events", "normalized_plate", "VARCHAR(80)"),
        ("vehicle_events", "camera_id", "INTEGER"),
        ("vehicle_events", "zone_id", "INTEGER"),
        ("vehicle_events", "site_id", "INTEGER"),
        ("vehicle_events", "timestamp", "TIMESTAMP"),
        ("vehicle_events", "snapshot_path", "VARCHAR(255)"),
        ("vehicle_events", "severity", "VARCHAR(20) DEFAULT 'info'"),
        ("vehicle_events", "is_priority", "BOOLEAN DEFAULT 0"),
        ("vehicle_events", "security_tag", "VARCHAR(50)"),
        ("vehicle_events", "reason", "VARCHAR(120)"),
        ("vehicle_events", "matched_registry", "BOOLEAN DEFAULT 0"),
        ("vehicle_events", "consistency_score", "FLOAT DEFAULT 0"),
        ("vehicle_events", "consistency_level", "VARCHAR(20) DEFAULT 'low'"),
        ("vehicle_events", "consistency_flags", "JSON"),
        ("vehicle_events", "anomaly_detected", "BOOLEAN DEFAULT 0"),
        ("vehicle_events", "anomaly_level", "VARCHAR(20) DEFAULT 'none'"),
        ("vehicle_events", "anomaly_reason", "VARCHAR(160)"),
        ("vehicle_events", "anomaly_flags", "JSON"),
        ("vehicle_events", "pipeline_meta", "JSON"),
        ("vehicle_events", "created_at", "TIMESTAMP"),
        ("vehicle_access_logs", "event_id", "INTEGER"),
        ("vehicle_access_logs", "plate_number", "VARCHAR(50)"),
        ("vehicle_access_logs", "normalized_plate", "VARCHAR(80)"),
        ("vehicle_access_logs", "plate_type", "VARCHAR(20) DEFAULT 'unknown'"),
        ("vehicle_access_logs", "camera_id", "INTEGER"),
        ("vehicle_access_logs", "site_id", "INTEGER"),
        ("vehicle_access_logs", "gate_id", "VARCHAR(60)"),
        ("vehicle_access_logs", "timestamp", "TIMESTAMP"),
        ("vehicle_access_logs", "direction", "VARCHAR(12) DEFAULT 'UNKNOWN'"),
        ("vehicle_access_logs", "decision", "VARCHAR(30) DEFAULT 'denied'"),
        ("vehicle_access_logs", "confidence_score", "FLOAT DEFAULT 0"),
        ("vehicle_access_logs", "vehicle_detected", "BOOLEAN DEFAULT 1"),
        ("vehicle_access_logs", "vehicle_type", "VARCHAR(50)"),
        ("vehicle_access_logs", "plate_confidence", "FLOAT DEFAULT 0"),
        ("vehicle_access_logs", "security_tag", "VARCHAR(50)"),
        ("vehicle_access_logs", "reason", "VARCHAR(160)"),
        ("vehicle_access_logs", "snapshot_path", "VARCHAR(255)"),
        ("vehicle_access_logs", "registry_vehicle_id", "INTEGER"),
        ("vehicle_access_logs", "operator_id", "INTEGER"),
        ("vehicle_access_logs", "operator_note", "TEXT"),
        ("vehicle_access_logs", "dominant_color", "VARCHAR(30)"),
        ("vehicle_access_logs", "visual_consistency", "FLOAT"),
        ("vehicle_access_logs", "audit_meta", "JSON"),
        ("vehicle_access_logs", "created_at", "TIMESTAMP"),
        ("security_alerts", "type", "VARCHAR(40)"),
        ("security_alerts", "plate_number", "VARCHAR(50)"),
        ("security_alerts", "normalized_plate", "VARCHAR(80)"),
        ("security_alerts", "camera_id", "INTEGER"),
        ("security_alerts", "site_id", "INTEGER"),
        ("security_alerts", "gate_id", "VARCHAR(60)"),
        ("security_alerts", "timestamp", "TIMESTAMP"),
        ("security_alerts", "severity_level", "VARCHAR(20) DEFAULT 'high'"),
        ("security_alerts", "resolution_status", "VARCHAR(20) DEFAULT 'open'"),
        ("security_alerts", "message", "VARCHAR(255)"),
        ("security_alerts", "event_id", "INTEGER"),
        ("security_alerts", "access_log_id", "INTEGER"),
        ("security_alerts", "handled_by", "INTEGER"),
        ("security_alerts", "handled_at", "TIMESTAMP"),
        ("security_alerts", "snapshot_path", "VARCHAR(255)"),
        ("security_alerts", "details", "JSON"),
        ("security_alerts", "created_at", "TIMESTAMP"),
        ("vehicle_event_frames", "event_id", "INTEGER"),
        ("vehicle_event_frames", "frame_path", "VARCHAR(255)"),
        ("vehicle_event_frames", "timestamp", "TIMESTAMP"),
        ("vehicle_event_frames", "stage", "VARCHAR(30) DEFAULT 'full_frame'"),
        ("vehicle_event_frames", "ocr_text", "VARCHAR(120)"),
        ("vehicle_event_frames", "decision", "VARCHAR(30)"),
        ("vehicle_event_frames", "frame_meta", "JSON"),
        ("vehicle_event_frames", "created_at", "TIMESTAMP"),
        ("system_health_logs", "service_name", "VARCHAR(80)"),
        ("system_health_logs", "status", "VARCHAR(20) DEFAULT 'unknown'"),
        ("system_health_logs", "last_check", "TIMESTAMP"),
        ("system_health_logs", "latency_ms", "FLOAT"),
        ("system_health_logs", "error_count", "INTEGER DEFAULT 0"),
        ("system_health_logs", "details", "JSON"),
        ("system_health_logs", "created_at", "TIMESTAMP"),
        ("refresh_tokens", "token_hash", "VARCHAR(128)"),
        ("refresh_tokens", "user_id", "INTEGER"),
        ("refresh_tokens", "expires_at", "TIMESTAMP"),
        ("refresh_tokens", "is_revoked", "BOOLEAN DEFAULT 0"),
        ("refresh_tokens", "revoked_at", "TIMESTAMP"),
        ("refresh_tokens", "replaced_by_token_hash", "VARCHAR(128)"),
        ("refresh_tokens", "created_by_ip", "VARCHAR(64)"),
        ("refresh_tokens", "user_agent", "VARCHAR(255)"),
        ("audit_logs", "user_id", "INTEGER"),
        ("audit_logs", "username", "VARCHAR(50)"),
        ("audit_logs", "event_type", "VARCHAR(60)"),
        ("audit_logs", "action", "VARCHAR(80)"),
        ("audit_logs", "method", "VARCHAR(10)"),
        ("audit_logs", "path", "VARCHAR(255)"),
        ("audit_logs", "status_code", "INTEGER"),
        ("audit_logs", "ip_address", "VARCHAR(64)"),
        ("audit_logs", "user_agent", "VARCHAR(255)"),
        ("audit_logs", "request_id", "VARCHAR(64)"),
        ("audit_logs", "details", "JSON"),
        ("audit_logs", "created_at", "TIMESTAMP"),
    ]
    if use_pgvector:
        migrations.append(("face_encodings", "embedding_vector", "vector(512)"))
    else:
        migrations.append(("face_encodings", "embedding_vector", "JSON"))

    with engine.begin() as conn:
        if is_sqlite:
            # Defensive create for local legacy DBs where metadata.create_all may be bypassed.
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS sites (
                    id INTEGER PRIMARY KEY,
                    name VARCHAR(120) NOT NULL UNIQUE,
                    code VARCHAR(40) UNIQUE,
                    description TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS face_images (
                    id INTEGER PRIMARY KEY,
                    personnel_id INTEGER NOT NULL,
                    image_path VARCHAR(255) NOT NULL,
                    pose_label VARCHAR(20) DEFAULT 'front',
                    yaw FLOAT,
                    pitch FLOAT,
                    roll FLOAT,
                    quality_score FLOAT,
                    detector_score FLOAT,
                    is_reference BOOLEAN DEFAULT 0,
                    source VARCHAR(30) DEFAULT 'manual',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS vehicle_registry_images (
                    id INTEGER PRIMARY KEY,
                    vehicle_registry_id INTEGER NOT NULL,
                    image_path VARCHAR(255) NOT NULL,
                    view_label VARCHAR(20) DEFAULT 'front',
                    quality_score FLOAT,
                    is_reference BOOLEAN DEFAULT 0,
                    source VARCHAR(30) DEFAULT 'manual',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS vehicle_events (
                    id INTEGER PRIMARY KEY,
                    plate_number VARCHAR(50),
                    plate_type VARCHAR(20) DEFAULT 'unknown',
                    confidence FLOAT DEFAULT 0,
                    vehicle_detected BOOLEAN DEFAULT 1,
                    vehicle_type VARCHAR(50),
                    body_style VARCHAR(50),
                    dominant_color VARCHAR(30),
                    brand VARCHAR(100),
                    model VARCHAR(100),
                    vehicle_confidence FLOAT DEFAULT 0,
                    vehicle_bbox JSON,
                    plate_confidence FLOAT DEFAULT 0,
                    plate_bbox JSON,
                    raw_plate_text VARCHAR(120),
                    normalized_plate VARCHAR(80),
                    camera_id INTEGER NOT NULL,
                    zone_id INTEGER,
                    site_id INTEGER,
                    timestamp DATETIME NOT NULL,
                    snapshot_path VARCHAR(255),
                    severity VARCHAR(20) DEFAULT 'info',
                    is_priority BOOLEAN DEFAULT 0,
                    security_tag VARCHAR(50),
                    reason VARCHAR(120),
                    matched_registry BOOLEAN DEFAULT 0,
                    consistency_score FLOAT DEFAULT 0,
                    consistency_level VARCHAR(20) DEFAULT 'low',
                    consistency_flags JSON,
                    anomaly_detected BOOLEAN DEFAULT 0,
                    anomaly_level VARCHAR(20) DEFAULT 'none',
                    anomaly_reason VARCHAR(160),
                    anomaly_flags JSON,
                    pipeline_meta JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS vehicle_access_logs (
                    id INTEGER PRIMARY KEY,
                    event_id INTEGER,
                    plate_number VARCHAR(50),
                    normalized_plate VARCHAR(80),
                    plate_type VARCHAR(20) DEFAULT 'unknown',
                    camera_id INTEGER NOT NULL,
                    site_id INTEGER,
                    gate_id VARCHAR(60),
                    timestamp DATETIME NOT NULL,
                    direction VARCHAR(12) DEFAULT 'UNKNOWN',
                    decision VARCHAR(30) DEFAULT 'denied',
                    confidence_score FLOAT DEFAULT 0,
                    vehicle_detected BOOLEAN DEFAULT 1,
                    vehicle_type VARCHAR(50),
                    plate_confidence FLOAT DEFAULT 0,
                    security_tag VARCHAR(50),
                    reason VARCHAR(160),
                    snapshot_path VARCHAR(255),
                    registry_vehicle_id INTEGER,
                    operator_id INTEGER,
                    operator_note TEXT,
                    dominant_color VARCHAR(30),
                    visual_consistency FLOAT,
                    audit_meta JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS security_alerts (
                    id INTEGER PRIMARY KEY,
                    type VARCHAR(40) NOT NULL,
                    plate_number VARCHAR(50),
                    normalized_plate VARCHAR(80),
                    camera_id INTEGER,
                    site_id INTEGER,
                    gate_id VARCHAR(60),
                    timestamp DATETIME NOT NULL,
                    severity_level VARCHAR(20) DEFAULT 'high',
                    resolution_status VARCHAR(20) DEFAULT 'open',
                    message VARCHAR(255),
                    event_id INTEGER,
                    access_log_id INTEGER,
                    handled_by INTEGER,
                    handled_at DATETIME,
                    snapshot_path VARCHAR(255),
                    details JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS vehicle_event_frames (
                    id INTEGER PRIMARY KEY,
                    event_id INTEGER NOT NULL,
                    frame_path VARCHAR(255) NOT NULL,
                    timestamp DATETIME NOT NULL,
                    stage VARCHAR(30) DEFAULT 'full_frame',
                    ocr_text VARCHAR(120),
                    decision VARCHAR(30),
                    frame_meta JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS system_health_logs (
                    id INTEGER PRIMARY KEY,
                    service_name VARCHAR(80) NOT NULL,
                    status VARCHAR(20) DEFAULT 'unknown',
                    last_check DATETIME NOT NULL,
                    latency_ms FLOAT,
                    error_count INTEGER DEFAULT 0,
                    details JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    token_hash VARCHAR(128) NOT NULL UNIQUE,
                    expires_at DATETIME NOT NULL,
                    is_revoked BOOLEAN DEFAULT 0,
                    revoked_at DATETIME,
                    replaced_by_token_hash VARCHAR(128),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_by_ip VARCHAR(64),
                    user_agent VARCHAR(255)
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    username VARCHAR(50),
                    event_type VARCHAR(60) NOT NULL,
                    action VARCHAR(80) NOT NULL,
                    method VARCHAR(10) NOT NULL,
                    path VARCHAR(255) NOT NULL,
                    status_code INTEGER NOT NULL,
                    ip_address VARCHAR(64),
                    user_agent VARCHAR(255),
                    request_id VARCHAR(64),
                    details JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        elif is_postgres:
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS sites (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(120) NOT NULL UNIQUE,
                    code VARCHAR(40) UNIQUE,
                    description TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS vehicle_events (
                    id SERIAL PRIMARY KEY,
                    plate_number VARCHAR(50),
                    plate_type VARCHAR(20) DEFAULT 'unknown',
                    confidence DOUBLE PRECISION DEFAULT 0,
                    vehicle_detected BOOLEAN DEFAULT TRUE,
                    vehicle_type VARCHAR(50),
                    body_style VARCHAR(50),
                    dominant_color VARCHAR(30),
                    brand VARCHAR(100),
                    model VARCHAR(100),
                    vehicle_confidence DOUBLE PRECISION DEFAULT 0,
                    vehicle_bbox JSONB,
                    plate_confidence DOUBLE PRECISION DEFAULT 0,
                    plate_bbox JSONB,
                    raw_plate_text VARCHAR(120),
                    normalized_plate VARCHAR(80),
                    camera_id INTEGER NOT NULL,
                    zone_id INTEGER,
                    site_id INTEGER,
                    timestamp TIMESTAMPTZ NOT NULL,
                    snapshot_path VARCHAR(255),
                    severity VARCHAR(20) DEFAULT 'info',
                    is_priority BOOLEAN DEFAULT FALSE,
                    security_tag VARCHAR(50),
                    reason VARCHAR(120),
                    matched_registry BOOLEAN DEFAULT FALSE,
                    consistency_score DOUBLE PRECISION DEFAULT 0,
                    consistency_level VARCHAR(20) DEFAULT 'low',
                    consistency_flags JSONB,
                    anomaly_detected BOOLEAN DEFAULT FALSE,
                    anomaly_level VARCHAR(20) DEFAULT 'none',
                    anomaly_reason VARCHAR(160),
                    anomaly_flags JSONB,
                    pipeline_meta JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS vehicle_access_logs (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER,
                    plate_number VARCHAR(50),
                    normalized_plate VARCHAR(80),
                    plate_type VARCHAR(20) DEFAULT 'unknown',
                    camera_id INTEGER NOT NULL,
                    site_id INTEGER,
                    gate_id VARCHAR(60),
                    timestamp TIMESTAMPTZ NOT NULL,
                    direction VARCHAR(12) DEFAULT 'UNKNOWN',
                    decision VARCHAR(30) DEFAULT 'denied',
                    confidence_score DOUBLE PRECISION DEFAULT 0,
                    vehicle_detected BOOLEAN DEFAULT TRUE,
                    vehicle_type VARCHAR(50),
                    plate_confidence DOUBLE PRECISION DEFAULT 0,
                    security_tag VARCHAR(50),
                    reason VARCHAR(160),
                    snapshot_path VARCHAR(255),
                    registry_vehicle_id INTEGER,
                    operator_id INTEGER,
                    operator_note TEXT,
                    dominant_color VARCHAR(30),
                    visual_consistency DOUBLE PRECISION,
                    audit_meta JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS security_alerts (
                    id SERIAL PRIMARY KEY,
                    type VARCHAR(40) NOT NULL,
                    plate_number VARCHAR(50),
                    normalized_plate VARCHAR(80),
                    camera_id INTEGER,
                    site_id INTEGER,
                    gate_id VARCHAR(60),
                    timestamp TIMESTAMPTZ NOT NULL,
                    severity_level VARCHAR(20) DEFAULT 'high',
                    resolution_status VARCHAR(20) DEFAULT 'open',
                    message VARCHAR(255),
                    event_id INTEGER,
                    access_log_id INTEGER,
                    handled_by INTEGER,
                    handled_at TIMESTAMPTZ,
                    snapshot_path VARCHAR(255),
                    details JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS vehicle_event_frames (
                    id SERIAL PRIMARY KEY,
                    event_id INTEGER NOT NULL,
                    frame_path VARCHAR(255) NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    stage VARCHAR(30) DEFAULT 'full_frame',
                    ocr_text VARCHAR(120),
                    decision VARCHAR(30),
                    frame_meta JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS system_health_logs (
                    id SERIAL PRIMARY KEY,
                    service_name VARCHAR(80) NOT NULL,
                    status VARCHAR(20) DEFAULT 'unknown',
                    last_check TIMESTAMPTZ NOT NULL,
                    latency_ms DOUBLE PRECISION,
                    error_count INTEGER DEFAULT 0,
                    details JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    token_hash VARCHAR(128) NOT NULL UNIQUE,
                    expires_at TIMESTAMPTZ NOT NULL,
                    is_revoked BOOLEAN DEFAULT FALSE,
                    revoked_at TIMESTAMPTZ,
                    replaced_by_token_hash VARCHAR(128),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by_ip VARCHAR(64),
                    user_agent VARCHAR(255)
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER,
                    username VARCHAR(50),
                    event_type VARCHAR(60) NOT NULL,
                    action VARCHAR(80) NOT NULL,
                    method VARCHAR(10) NOT NULL,
                    path VARCHAR(255) NOT NULL,
                    status_code INTEGER NOT NULL,
                    ip_address VARCHAR(64),
                    user_agent VARCHAR(255),
                    request_id VARCHAR(64),
                    details JSONB,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )

        inspector = inspect(conn)
        table_names = set(inspector.get_table_names())
        for table, column, ddl in migrations:
            try:
                if table not in table_names:
                    continue
                existing_cols = {col["name"] for col in inspector.get_columns(table)}
                if column not in existing_cols:
                    normalized_ddl = _normalize_migration_ddl(ddl, is_postgres=is_postgres)
                    with conn.begin_nested():
                        conn.exec_driver_sql(
                            f"ALTER TABLE {table} ADD COLUMN {column} {normalized_ddl}"
                        )
                    logger.info("DB migration applied: %s.%s", table, column)
            except Exception as e:
                logger.warning("DB migration skipped for %s.%s: %s", table, column, e)

        # Legacy SQLite compatibility: older datasets used accented column name "unité".
        # Keep the ORM-facing "unite" column populated when both exist.
        if is_sqlite and "personnel" in table_names:
            try:
                personnel_cols = {col["name"] for col in inspect(conn).get_columns("personnel")}
                if "unité" in personnel_cols and "unite" in personnel_cols:
                    conn.exec_driver_sql(
                        'UPDATE personnel SET unite = "unité" '
                        "WHERE unite IS NULL OR TRIM(unite) = ''"
                    )
                    logger.info("DB migration applied: personnel.unité -> personnel.unite backfill")
            except Exception as e:
                logger.warning("DB migration skipped for personnel.unité backfill: %s", e)

        if "vehicle_events" in table_names:
            try:
                vehicle_event_cols = {col["name"] for col in inspect(conn).get_columns("vehicle_events")}
                required_attr_cols = {"dominant_color", "brand", "model", "body_style"}
                if required_attr_cols.issubset(vehicle_event_cols):
                    from vms.backend.services.vehicle_ai.vehicle_taxonomy import (
                        normalize_vehicle_body_style,
                        normalize_vehicle_brand,
                        normalize_vehicle_color,
                        normalize_vehicle_model,
                    )

                    rows = conn.exec_driver_sql(
                        """
                        SELECT id, pipeline_meta, dominant_color, brand, model, body_style
                        FROM vehicle_events
                        """
                    ).mappings().all()
                    updated = 0
                    for row in rows:
                        next_color, next_brand, next_model, next_body_style = _extract_vehicle_profile_backfill_attrs(
                            row.get("pipeline_meta")
                        )
                        normalized_current_color = normalize_vehicle_color(row.get("dominant_color"))
                        current_color = None if normalized_current_color == "unknown" else normalized_current_color
                        current_brand = normalize_vehicle_brand(row.get("brand"))
                        current_model = normalize_vehicle_model(row.get("model"))
                        current_body_style = normalize_vehicle_body_style(row.get("body_style"))

                        resolved_color = current_color or next_color
                        resolved_brand = current_brand or next_brand
                        resolved_model = current_model or next_model
                        resolved_body_style = current_body_style or next_body_style

                        raw_current_color = str(row.get("dominant_color") or "").strip() or None
                        raw_current_brand = str(row.get("brand") or "").strip() or None
                        raw_current_model = str(row.get("model") or "").strip() or None
                        raw_current_body_style = str(row.get("body_style") or "").strip() or None

                        if (
                            resolved_color == raw_current_color
                            and resolved_brand == raw_current_brand
                            and resolved_model == raw_current_model
                            and resolved_body_style == raw_current_body_style
                        ):
                            continue

                        conn.execute(
                            text(
                                """
                                UPDATE vehicle_events
                                SET dominant_color = :dominant_color,
                                    brand = :brand,
                                    model = :model,
                                    body_style = :body_style
                                WHERE id = :row_id
                                """
                            ),
                            {
                                "dominant_color": resolved_color,
                                "brand": resolved_brand,
                                "model": resolved_model,
                                "body_style": resolved_body_style,
                                "row_id": int(row["id"]),
                            },
                        )
                        updated += 1

                    if updated:
                        logger.info("DB migration applied: vehicle_events attribute backfill (%s row(s))", updated)
            except Exception as e:
                logger.warning("DB migration skipped for vehicle_events attribute backfill: %s", e)

        if "sites" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_sites_is_active
                    ON sites (is_active)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_sites_code
                    ON sites (code)
                    """
                )
            except Exception as e:
                logger.warning("sites index creation skipped: %s", e)

        if "zones" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_zones_site_active_blocked
                    ON zones (site_id, is_active, is_blocked)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_zones_site_name
                    ON zones (site_id, name)
                    """
                )
            except Exception as e:
                logger.warning("zones index creation skipped: %s", e)

        if "cameras" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_cameras_site_enabled_active
                    ON cameras (site_id, is_enabled, is_active)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_cameras_site_zone
                    ON cameras (site_id, zone_id)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_cameras_camera_type
                    ON cameras (camera_type)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_cameras_selection_role
                    ON cameras (selection_role)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_cameras_stream_validation_status
                    ON cameras (stream_validation_status)
                    """
                )
            except Exception as e:
                logger.warning("cameras index creation skipped: %s", e)

        if "events" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_events_site_detected
                    ON events (site_id, detected_at)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_events_decision_detected
                    ON events (decision, detected_at)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_events_site_zone
                    ON events (site_id, zone_id)
                    """
                )
            except Exception as e:
                logger.warning("events index creation skipped: %s", e)

        if "vehicle_events" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_camera_timestamp
                    ON vehicle_events (camera_id, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_plate_type_timestamp
                    ON vehicle_events (plate_type, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_plate_number
                    ON vehicle_events (plate_number)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_consistency_score
                    ON vehicle_events (consistency_score)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_anomaly_level
                    ON vehicle_events (anomaly_level)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_site_timestamp
                    ON vehicle_events (site_id, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_color_timestamp
                    ON vehicle_events (dominant_color, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_brand_timestamp
                    ON vehicle_events (brand, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_model_timestamp
                    ON vehicle_events (model, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_events_body_style_timestamp
                    ON vehicle_events (body_style, timestamp)
                    """
                )
            except Exception as e:
                logger.warning("vehicle_events index creation skipped: %s", e)

        if "vehicle_access_logs" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_access_logs_camera_timestamp
                    ON vehicle_access_logs (camera_id, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_access_logs_decision_timestamp
                    ON vehicle_access_logs (decision, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_access_logs_norm_plate
                    ON vehicle_access_logs (normalized_plate)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_access_logs_site_timestamp
                    ON vehicle_access_logs (site_id, timestamp)
                    """
                )
            except Exception as e:
                logger.warning("vehicle_access_logs index creation skipped: %s", e)

        if "security_alerts" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_security_alerts_status_severity_time
                    ON security_alerts (resolution_status, severity_level, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_security_alerts_camera_time
                    ON security_alerts (camera_id, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_security_alerts_type_time
                    ON security_alerts (type, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_security_alerts_site_time
                    ON security_alerts (site_id, timestamp)
                    """
                )
            except Exception as e:
                logger.warning("security_alerts index creation skipped: %s", e)

        if "vehicle_event_frames" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_event_frames_event_timestamp
                    ON vehicle_event_frames (event_id, timestamp)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_vehicle_event_frames_stage
                    ON vehicle_event_frames (stage)
                    """
                )
            except Exception as e:
                logger.warning("vehicle_event_frames index creation skipped: %s", e)

        if "system_health_logs" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_system_health_logs_service_time
                    ON system_health_logs (service_name, last_check)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_system_health_logs_status_time
                    ON system_health_logs (status, last_check)
                    """
                )
            except Exception as e:
                logger.warning("system_health_logs index creation skipped: %s", e)

        if "refresh_tokens" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_revoked_exp
                    ON refresh_tokens (user_id, is_revoked, expires_at)
                    """
                )
            except Exception as e:
                logger.warning("refresh_tokens index creation skipped: %s", e)

        if "audit_logs" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_audit_logs_created_action
                    ON audit_logs (created_at, action)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_audit_logs_user_created
                    ON audit_logs (user_id, created_at)
                    """
                )
            except Exception as e:
                logger.warning("audit_logs index creation skipped: %s", e)

        if "face_detections" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_face_detections_camera_track_detected
                    ON face_detections (camera_id, track_id, detected_at)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_face_detections_track_detected
                    ON face_detections (track_id, detected_at)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_face_detections_appearance_top_color
                    ON face_detections (appearance_top_color)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_face_detections_appearance_bottom_color
                    ON face_detections (appearance_bottom_color)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_face_detections_has_backpack
                    ON face_detections (has_backpack)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_face_detections_has_hat
                    ON face_detections (has_hat)
                    """
                )
            except Exception as e:
                logger.warning("face_detections index creation skipped: %s", e)

        if "users" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_users_role
                    ON users (role)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_users_last_login
                    ON users (last_login)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_users_setup_completed
                    ON users (setup_completed)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_users_application_mode
                    ON users (application_mode)
                    """
                )
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_users_country_code
                    ON users (country_code)
                    """
                )
            except Exception as e:
                logger.warning("users index creation skipped: %s", e)

        if use_pgvector and "face_encodings" in table_names:
            try:
                conn.exec_driver_sql(
                    """
                    CREATE INDEX IF NOT EXISTS ix_face_encodings_embedding_vector_hnsw
                    ON face_encodings
                    USING hnsw (embedding_vector vector_cosine_ops)
                    """
                )
                logger.info("pgvector index ready: HNSW cosine")
            except Exception as hnsw_error:
                logger.warning("HNSW index creation skipped: %s", hnsw_error)
                try:
                    conn.exec_driver_sql(
                        """
                        CREATE INDEX IF NOT EXISTS ix_face_encodings_embedding_vector_ivfflat
                        ON face_encodings
                        USING ivfflat (embedding_vector vector_cosine_ops)
                        WITH (lists = 100)
                        """
                    )
                    logger.info("pgvector index ready: IVFFLAT cosine")
                except Exception as ivf_error:
                    logger.warning("IVFFLAT index creation skipped: %s", ivf_error)

    ensure_face_detection_appearance_schema(engine)
    report = get_database_startup_report(bind=engine)
    missing = [name for name, present in report["required_tables"].items() if not present]
    if missing:
        raise RuntimeError(f"Database initialization incomplete, missing tables: {', '.join(missing)}")
    return report
