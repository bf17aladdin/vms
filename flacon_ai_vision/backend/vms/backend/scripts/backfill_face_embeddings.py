"""
Backfill script: face_encodings.encoding_vector -> face_encodings.embedding_vector.

Usage (PowerShell):
  $env:DATABASE_URL='postgresql+psycopg://user:pwd@127.0.0.1:5432/falcon_ai_vision'
  .\venv_ai\Scripts\python.exe vms/backend/scripts/backfill_face_embeddings.py --batch-size 500
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Optional

from sqlalchemy import inspect, text

# Allow running as a script: `python vms/backend/scripts/backfill_face_embeddings.py`
if __package__ in (None, ""):
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[3]))

from vms.backend.core.config import settings
from vms.backend.core.database import engine, init_db


def _is_postgres() -> bool:
    return settings.DATABASE_URL.lower().startswith("postgresql")


def _table_and_columns_ok() -> tuple[bool, Optional[str]]:
    inspector = inspect(engine)
    if "face_encodings" not in set(inspector.get_table_names()):
        return False, "table face_encodings not found"
    cols = {c["name"] for c in inspector.get_columns("face_encodings")}
    if "encoding_vector" not in cols:
        return False, "column encoding_vector not found"
    if "embedding_vector" not in cols:
        return False, "column embedding_vector not found"
    return True, None


def _count_pending() -> int:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM face_encodings
                WHERE embedding_vector IS NULL
                  AND encoding_vector IS NOT NULL
                """
            )
        ).scalar()
        return int(row or 0)


def _backfill_postgres(batch_size: int) -> int:
    updated_total = 0
    while True:
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    WITH batch AS (
                        SELECT id, encoding_vector
                        FROM face_encodings
                        WHERE embedding_vector IS NULL
                          AND encoding_vector IS NOT NULL
                        LIMIT :batch_size
                    )
                    UPDATE face_encodings AS fe
                    SET embedding_vector = CAST(batch.encoding_vector::text AS vector)
                    FROM batch
                    WHERE fe.id = batch.id
                    RETURNING fe.id
                    """
                ),
                {"batch_size": int(batch_size)},
            ).fetchall()

        changed = len(rows)
        updated_total += changed
        print(f"batch updated={changed}, total={updated_total}")
        if changed == 0:
            break
    return updated_total


def _backfill_generic() -> int:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE face_encodings
                SET embedding_vector = encoding_vector
                WHERE embedding_vector IS NULL
                  AND encoding_vector IS NOT NULL
                """
            )
        )
    # rowcount may be -1 on some DB drivers.
    return max(0, int(result.rowcount or 0))


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill embedding_vector from encoding_vector")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size for PostgreSQL updates")
    args = parser.parse_args()

    print("== Falcon AI Vision embedding backfill ==")
    print(f"DATABASE_URL={settings.DATABASE_URL}")

    init_db()
    ok, err = _table_and_columns_ok()
    if not ok:
        print(f"ERROR: {err}")
        return 1

    pending_before = _count_pending()
    print(f"pending_before={pending_before}")
    if pending_before == 0:
        print("Nothing to backfill.")
        return 0

    if _is_postgres():
        updated = _backfill_postgres(batch_size=max(1, int(args.batch_size)))
    else:
        updated = _backfill_generic()
        print(f"updated={updated}")

    pending_after = _count_pending()
    print(f"pending_after={pending_after}")
    print(f"updated_total={updated}")

    if pending_after > 0:
        print("WARNING: backfill incomplete.")
        return 2
    print("Backfill completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
