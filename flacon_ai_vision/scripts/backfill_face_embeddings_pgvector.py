#!/usr/bin/env python
"""
Backfill script: copy JSON face embeddings into pgvector column.

Usage examples:
  python scripts/backfill_face_embeddings_pgvector.py
  python scripts/backfill_face_embeddings_pgvector.py --dry-run
  python scripts/backfill_face_embeddings_pgvector.py --database-url "postgresql+psycopg://user:pass@localhost:5432/db"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill face_encodings.embedding_vector from face_encodings.encoding_vector",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Override DATABASE_URL for this execution.",
    )
    parser.add_argument(
        "--vector-dim",
        type=int,
        default=int(os.getenv("FACE_PGVECTOR_DIM", "512")),
        help="Expected embedding dimension (default: FACE_PGVECTOR_DIM or 512).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Commit frequency while updating rows.",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        help="Overwrite embedding_vector even when already present.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report counts, do not update rows.",
    )
    return parser.parse_args()


def _is_postgres_session(session) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def _column_exists(session, table_name: str, column_name: str) -> bool:
    from sqlalchemy import inspect

    inspector = inspect(session.get_bind())
    try:
        columns = {col["name"] for col in inspector.get_columns(table_name)}
    except Exception:
        return False
    return column_name in columns


def _is_vector_like(value) -> bool:
    return isinstance(value, (list, tuple))


def _normalize_vector(raw, expected_dim: int) -> Tuple[bool, list[float] | None]:
    if not _is_vector_like(raw):
        return False, None
    if len(raw) != expected_dim:
        return False, None
    try:
        out = [float(v) for v in raw]
    except Exception:
        return False, None
    return True, out


def main() -> int:
    args = parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    # Deferred imports so DATABASE_URL override is applied before engine creation.
    from vms.backend.core.database import SessionLocal
    from vms.backend.models import FaceEncoding

    session = SessionLocal()

    try:
        if not _is_postgres_session(session):
            print("ERROR: this script only supports PostgreSQL/pgvector backfill.")
            return 2

        if not _column_exists(session, "face_encodings", "embedding_vector"):
            print("ERROR: face_encodings.embedding_vector does not exist. Run backend init/migrations first.")
            return 3

        query = session.query(FaceEncoding).filter(FaceEncoding.encoding_vector.isnot(None))
        if not args.force_overwrite:
            query = query.filter(FaceEncoding.embedding_vector.is_(None))

        total_candidates = query.count()
        if total_candidates == 0:
            print("No candidate rows found.")
            return 0

        scanned = 0
        updated = 0
        skipped_dim = 0
        skipped_invalid = 0
        pending_updates = 0

        for row in query.yield_per(max(1, args.batch_size)):
            scanned += 1
            ok, vector = _normalize_vector(row.encoding_vector, args.vector_dim)
            if not ok:
                if _is_vector_like(row.encoding_vector) and len(row.encoding_vector) != args.vector_dim:
                    skipped_dim += 1
                else:
                    skipped_invalid += 1
                continue

            if args.dry_run:
                updated += 1
                continue

            row.embedding_vector = vector
            updated += 1
            pending_updates += 1

            if pending_updates >= args.batch_size:
                session.commit()
                pending_updates = 0

        if not args.dry_run and pending_updates > 0:
            session.commit()

        print(f"Candidates: {total_candidates}")
        print(f"Scanned: {scanned}")
        print(f"Updated: {updated}{' (dry-run)' if args.dry_run else ''}")
        print(f"Skipped (dimension mismatch): {skipped_dim}")
        print(f"Skipped (invalid JSON values): {skipped_invalid}")
        return 0

    except Exception as exc:
        session.rollback()
        print(f"ERROR: backfill failed: {exc}")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
