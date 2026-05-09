"""
PostgreSQL/pgvector readiness script for Falcon AI Vision runtime.

Usage (PowerShell):
  $env:DATABASE_URL='postgresql+psycopg://user:pwd@127.0.0.1:5432/falcon_ai_vision'
  $env:FACE_PGVECTOR_ENABLED='true'
  .\venv_ai\Scripts\python.exe vms/backend/scripts/migrate_postgres_runtime.py
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import inspect, text

# Allow running as a script: `python vms/backend/scripts/migrate_postgres_runtime.py`
if __package__ in (None, ""):
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))

from vms.backend.core.config import settings
from vms.backend.core.database import engine, init_db


@dataclass
class CheckResult:
    name: str
    ok: bool
    details: str


def _is_postgres() -> bool:
    return settings.DATABASE_URL.lower().startswith("postgresql")


def _print_results(rows: Iterable[CheckResult]) -> int:
    failed = 0
    for row in rows:
        status = "OK" if row.ok else "FAIL"
        print(f"[{status}] {row.name}: {row.details}")
        if not row.ok:
            failed += 1
    return failed


def main() -> int:
    print("== Falcon AI Vision DB runtime migration check ==")
    print(f"DATABASE_URL={settings.DATABASE_URL}")

    init_db()
    inspector = inspect(engine)

    table_names = set(inspector.get_table_names())
    results: list[CheckResult] = []
    results.append(CheckResult("table.face_encodings", "face_encodings" in table_names, "exists" if "face_encodings" in table_names else "missing"))

    if "face_encodings" in table_names:
        columns = {col["name"] for col in inspector.get_columns("face_encodings")}
        results.append(CheckResult("column.encoding_vector", "encoding_vector" in columns, "present" if "encoding_vector" in columns else "missing"))
        results.append(CheckResult("column.embedding_vector", "embedding_vector" in columns, "present" if "embedding_vector" in columns else "missing"))

    if _is_postgres():
        with engine.connect() as conn:
            ext = conn.execute(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")).scalar()
            results.append(CheckResult("extension.pgvector", bool(ext), "installed" if ext else "not installed"))

            index_rows = conn.execute(
                text(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename = 'face_encodings'
                    """
                )
            ).fetchall()
            index_names = {str(row[0]) for row in index_rows}
            hnsw = "ix_face_encodings_embedding_vector_hnsw" in index_names
            ivf = "ix_face_encodings_embedding_vector_ivfflat" in index_names
            results.append(
                CheckResult(
                    "index.embedding_vector",
                    bool(hnsw or ivf),
                    "hnsw" if hnsw else ("ivfflat" if ivf else "missing"),
                )
            )
    else:
        results.append(CheckResult("postgresql", False, "DATABASE_URL is not PostgreSQL"))

    failures = _print_results(results)
    if failures:
        print(f"Completed with {failures} failing checks.")
        return 1
    print("All runtime checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
