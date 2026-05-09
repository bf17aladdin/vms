from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Iterable

try:
    import psycopg
    from psycopg import sql
except ImportError:  # pragma: no cover - optional dependency in some envs
    psycopg = None
    sql = None


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
BACKEND_DATA_DIR = BACKEND_ROOT / "data"
BACKEND_STORAGE_DIR = BACKEND_ROOT / "storage"
LOGS_DIR = REPO_ROOT / "logs"
RUNTIME_DATA_DIR = REPO_ROOT / "data"
AI_ENGINE_DIR = REPO_ROOT / "ai-engine"
REPORTS_DIR = REPO_ROOT / "reports"
RUNS_DIR = REPO_ROOT / "runs"

SQLITE_FILES = [
    BACKEND_DATA_DIR / "vms.db",
    BACKEND_ROOT / "vms" / "backend" / "data" / "vms.db",
    REPO_ROOT / "vms.db",
]

DIRECTORIES_TO_CLEAR = [
    BACKEND_DATA_DIR,
    BACKEND_STORAGE_DIR / "uploads",
    LOGS_DIR,
    RUNTIME_DATA_DIR,
    REPORTS_DIR,
    RUNS_DIR,
    AI_ENGINE_DIR / "facial_recognition" / "known_faces",
    AI_ENGINE_DIR / "facial_recognition" / "unknown_faces",
]

DIRECTORIES_TO_RECREATE = [
    BACKEND_DATA_DIR,
    BACKEND_DATA_DIR / "recordings",
    BACKEND_DATA_DIR / "zones",
    BACKEND_STORAGE_DIR / "uploads",
    BACKEND_STORAGE_DIR / "uploads" / "person_photos",
    BACKEND_STORAGE_DIR / "uploads" / "vehicle_photos",
    LOGS_DIR,
    LOGS_DIR / "falcon_app",
    RUNTIME_DATA_DIR,
    RUNTIME_DATA_DIR / "recordings",
    RUNTIME_DATA_DIR / "zones",
    RUNTIME_DATA_DIR / "detections",
    RUNTIME_DATA_DIR / "face_detections",
    RUNTIME_DATA_DIR / "unknown_detections",
    RUNTIME_DATA_DIR / "vehicle_events",
    RUNTIME_DATA_DIR / "vehicle_event_frames",
    RUNTIME_DATA_DIR / "known_faces",
    RUNTIME_DATA_DIR / "unknown_faces",
    RUNTIME_DATA_DIR / "thumbnails",
    AI_ENGINE_DIR / "facial_recognition" / "known_faces",
    AI_ENGINE_DIR / "facial_recognition" / "unknown_faces",
]

FILES_TO_DELETE = [
    AI_ENGINE_DIR / "models" / "face_recognition" / "face_recognizer.yml",
    AI_ENGINE_DIR / "models" / "face_recognition" / "face_metadata.pkl",
]

SETUP_CONFIG_DEFAULT = {
    "usage_type": "maison",
    "project_type": "home",
    "operation_mode": "family",
    "camera_limit": 4,
    "detection_types": ["person", "vehicle"],
    "alert_types": ["motion", "person", "vehicle", "system"],
    "alert_channels": ["ui", "email"],
    "ui_preset": "home",
    "connect_email": None,
    "configured": False,
    "updated_at": None,
    "subscription_active": False,
    "subscription_tier": "free",
    "subscription_expires_at": None,
    "personnel_custom_fields": [
        {
            "key": "level",
            "label": "Level",
            "type": "select",
            "required": False,
            "options": ["Normal", "Priority"],
        }
    ],
    "personnel_visible_fields": ["last_name", "first_name", "role", "phone"],
    "personnel_level_migrated": True,
}

AI_CALIBRATION_DEFAULT = {
    "lbph": {
        "threshold": 100,
        "min_samples": 2,
        "grid_x": 8,
        "grid_y": 8,
        "radius": 1,
        "neighbors": 8,
    },
    "yolo": {
        "confidence": 0.5,
        "iou_threshold": 0.45,
        "max_detections": 100,
    },
    "vehicle": {
        "plate_confidence": 0.6,
        "vehicle_confidence": 0.7,
        "min_plate_area": 50,
    },
}


def _guard_workspace_path(path: Path) -> Path:
    resolved = path.resolve()
    root = REPO_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise RuntimeError(f"Refusing to touch path outside workspace: {resolved}")
    return resolved


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        os.environ.setdefault(key, value)


def _clear_directory(path: Path) -> int:
    _guard_workspace_path(path)
    if not path.exists():
        return 0
    removed = 0
    for child in list(path.iterdir()):
        _guard_workspace_path(child)
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def _remove_file(path: Path) -> bool:
    _guard_workspace_path(path)
    if not path.exists():
        return False
    path.unlink()
    return True


def _delete_matching_root_tmp_files() -> list[str]:
    deleted: list[str] = []
    search_roots = [REPO_ROOT, BACKEND_ROOT, REPO_ROOT / "scripts"]
    seen: set[Path] = set()
    for search_root in search_roots:
        if not search_root.exists():
            continue
        for path in search_root.glob("tmp_*"):
            if path in seen or not path.is_file():
                continue
            _remove_file(path)
            deleted.append(str(path.relative_to(REPO_ROOT)))
            seen.add(path)
    return deleted


def _write_json(path: Path, payload: dict) -> None:
    _guard_workspace_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _normalized_postgres_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    return url


def _run_init_db(database_url: str | None) -> None:
    env = os.environ.copy()
    if database_url:
        env["DATABASE_URL"] = database_url
    else:
        env.pop("DATABASE_URL", None)
    env["FACE_PGVECTOR_ENABLED"] = str(env.get("FACE_PGVECTOR_ENABLED", "false")).lower()
    init_code = (
        "import sys; "
        f"sys.path.insert(0, r'{BACKEND_ROOT.as_posix()}'); "
        "import vms; "
        "from vms.backend.core.database import init_db; "
        "init_db()"
    )
    subprocess.run(
        [sys.executable, "-c", init_code],
        cwd=str(BACKEND_ROOT),
        env=env,
        check=True,
    )


def _truncate_postgres(database_url: str) -> int:
    if psycopg is None or sql is None:
        raise RuntimeError("psycopg is required to reset PostgreSQL data")

    normalized_url = _normalized_postgres_url(database_url)
    with psycopg.connect(normalized_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY tablename
                """
            )
            tables = [row[0] for row in cur.fetchall() if row[0] != "alembic_version"]
            if not tables:
                return 0
            statement = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier("public", table_name) for table_name in tables)
            )
            cur.execute(statement)
            return len(tables)


def _count_sqlite_rows(path: Path, tables: Iterable[str]) -> dict[str, int]:
    if not path.exists():
        return {}
    counts: dict[str, int] = {}
    with sqlite3.connect(path) as conn:
        cursor = conn.cursor()
        for table in tables:
            try:
                counts[table] = int(cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.Error:
                continue
    return counts


def _reset_postgres_if_configured() -> str:
    database_url = str(os.environ.get("DATABASE_URL", "")).strip()
    if not database_url.lower().startswith("postgresql"):
        return "DATABASE_URL is not PostgreSQL; skipped"

    _run_init_db(database_url)
    truncated_tables = _truncate_postgres(database_url)
    return f"truncated {truncated_tables} PostgreSQL tables"


def _reset_sqlite_files() -> list[str]:
    removed: list[str] = []
    for path in SQLITE_FILES:
        if _remove_file(path):
            removed.append(str(path.relative_to(REPO_ROOT)))
    _run_init_db(None)
    recreated = BACKEND_DATA_DIR / "vms.db"
    if not recreated.exists():
        raise RuntimeError("SQLite schema recreation failed: backend/data/vms.db missing")
    return removed


def _reset_runtime_files() -> dict[str, object]:
    cleared_counts: dict[str, int] = {}
    for directory in DIRECTORIES_TO_CLEAR:
        cleared_counts[str(directory.relative_to(REPO_ROOT))] = _clear_directory(directory)

    deleted_files = []
    for file_path in FILES_TO_DELETE:
        if _remove_file(file_path):
            deleted_files.append(str(file_path.relative_to(REPO_ROOT)))

    deleted_tmp_files = _delete_matching_root_tmp_files()

    for directory in DIRECTORIES_TO_RECREATE:
        _guard_workspace_path(directory)
        directory.mkdir(parents=True, exist_ok=True)

    _write_json(BACKEND_DATA_DIR / "setup_config.json", SETUP_CONFIG_DEFAULT)
    _write_json(RUNTIME_DATA_DIR / "ai_calibration.json", AI_CALIBRATION_DEFAULT)

    return {
        "cleared_directories": cleared_counts,
        "deleted_files": deleted_files,
        "deleted_tmp_files": deleted_tmp_files,
    }


def _validate_state() -> dict[str, object]:
    sqlite_tables = ["users", "cameras", "events", "vehicle_events", "face_detections"]
    sqlite_counts = _count_sqlite_rows(BACKEND_DATA_DIR / "vms.db", sqlite_tables)

    runtime_checks = {
        "backend_upload_person_photos_files": len(list((BACKEND_STORAGE_DIR / "uploads" / "person_photos").glob("*"))),
        "backend_upload_vehicle_photos_files": len(list((BACKEND_STORAGE_DIR / "uploads" / "vehicle_photos").glob("*"))),
        "logs_files": len([path for path in LOGS_DIR.rglob("*") if path.is_file()]),
        "data_runtime_files": len([path for path in RUNTIME_DATA_DIR.rglob("*") if path.is_file()]),
        "reports_files": len([path for path in REPORTS_DIR.rglob("*") if path.is_file()]) if REPORTS_DIR.exists() else 0,
        "runs_files": len([path for path in RUNS_DIR.rglob("*") if path.is_file()]) if RUNS_DIR.exists() else 0,
    }

    return {
        "sqlite_counts": sqlite_counts,
        "runtime_checks": runtime_checks,
        "kept_models": sorted(path.name for path in (AI_ENGINE_DIR / "models").glob("yolov8*.pt")),
        "setup_config_path": str((BACKEND_DATA_DIR / "setup_config.json").relative_to(REPO_ROOT)),
    }


def main() -> int:
    _load_env_file(REPO_ROOT / ".env")

    runtime_summary = _reset_runtime_files()
    postgres_summary = _reset_postgres_if_configured()
    removed_sqlite_files = _reset_sqlite_files()
    validation = _validate_state()

    summary = {
        "postgres": postgres_summary,
        "removed_sqlite_files": removed_sqlite_files,
        "runtime": runtime_summary,
        "validation": validation,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
