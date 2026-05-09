from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class FaceMatcher:
    """Cosine matcher with pgvector acceleration and NumPy fallback."""

    def __init__(self, db: Session):
        self.db = db
        self.threshold = float(os.getenv("FACE_MATCH_THRESHOLD", "0.62"))
        self.allow_fallback_models = os.getenv("FACE_MATCH_ALLOW_FALLBACK_MODELS", "false").lower() == "true"
        self.small_gallery_candidate_limit = int(
            os.getenv("FACE_SMALL_GALLERY_CANDIDATE_LIMIT", "2")
        )
        self.small_gallery_min_threshold = float(
            os.getenv("FACE_SMALL_GALLERY_MIN_THRESHOLD", "0.72")
        )
        self.cache_ttl_sec = int(os.getenv("FACE_MATCH_CACHE_TTL_SEC", "20"))
        self.pgvector_dim = int(os.getenv("FACE_PGVECTOR_DIM", "512"))
        self.pgvector_enabled = os.getenv("FACE_PGVECTOR_ENABLED", "false").lower() == "true"
        self._cache_timestamp = 0.0
        self._rows: List[Dict[str, Any]] = []
        self._vectors: List[np.ndarray] = []
        self.use_pgvector = self._detect_pgvector_support()
        self.backend = "pgvector_cosine" if self.use_pgvector else "cosine_numpy"

    def invalidate(self) -> None:
        self._cache_timestamp = 0.0

    def refresh_index(self, force: bool = False) -> None:
        if self.use_pgvector:
            # pgvector path is query-time and does not require in-memory cache.
            return
        if not force and (time.time() - self._cache_timestamp) <= self.cache_ttl_sec and self._rows:
            return

        from vms.backend.models import FaceEncoding, FaceImage, Personnel

        try:
            rows = (
                self.db.query(FaceEncoding, Personnel, FaceImage)
                .join(Personnel, FaceEncoding.personnel_id == Personnel.id)
                .outerjoin(FaceImage, FaceImage.id == FaceEncoding.face_image_id)
                .filter(FaceEncoding.is_active.is_(True))
                .all()
            )
        except Exception as exc:
            logger.warning("Failed to refresh face matcher gallery cache: %s", exc)
            self._safe_rollback()
            self._rows = []
            self._vectors = []
            self._cache_timestamp = time.time()
            return

        out: List[Dict[str, Any]] = []
        vectors: List[np.ndarray] = []

        for face_encoding, person, face_image in rows:
            model_name = str(face_encoding.model_name or "unknown")
            if (not self.allow_fallback_models) and model_name.lower().startswith("fallback"):
                continue

            raw_vector = face_encoding.encoding_vector or []
            if not raw_vector and hasattr(face_encoding, "embedding_vector"):
                raw_vector = getattr(face_encoding, "embedding_vector") or []

            vec = np.asarray(raw_vector, dtype=np.float32).reshape(-1)
            if vec.size == 0:
                continue
            vec = self._normalize(vec)
            vectors.append(vec)
            out.append(
                {
                    "personnel_id": person.id,
                    "full_name": person.full_name,
                    "is_active": bool(person.is_active),
                    "is_blacklisted": bool(person.is_blacklisted),
                    "face_encoding_id": face_encoding.id,
                    "pose_label": face_image.pose_label if face_image else None,
                    "quality_score": float(face_encoding.quality_score or 0.0),
                    "model_name": model_name,
                }
            )

        self._rows = out
        self._vectors = vectors
        self._cache_timestamp = time.time()

    def match(
        self,
        embedding: np.ndarray,
        top_k: int = 5,
        threshold_override: Optional[float] = None,
    ) -> Dict[str, Any]:
        effective_threshold = (
            float(threshold_override) if threshold_override is not None else self.threshold
        )
        query = self._normalize(np.asarray(embedding, dtype=np.float32).reshape(-1))
        if query.size == 0:
            return {
                "matched": False,
                "best_score": 0.0,
                "best": None,
                "top_matches": [],
                "threshold": effective_threshold,
            }

        if self.use_pgvector and query.shape[0] == self.pgvector_dim:
            pgvector_result = self._match_pgvector(query, top_k=top_k)
            if pgvector_result is not None:
                candidate_count = int(pgvector_result.get("candidate_count") or 0)
                if (
                    threshold_override is None
                    and candidate_count > 0
                    and candidate_count <= max(1, self.small_gallery_candidate_limit)
                ):
                    effective_threshold = max(
                        effective_threshold,
                        float(self.small_gallery_min_threshold),
                    )
                best = pgvector_result.get("best")
                best_score = float(pgvector_result.get("best_score") or 0.0)
                pgvector_result["matched"] = bool(best and best_score >= effective_threshold)
                pgvector_result["threshold"] = effective_threshold
                return pgvector_result

        self.refresh_index(force=False)
        if not self._rows or not self._vectors:
            return {
                "matched": False,
                "best_score": 0.0,
                "best": None,
                "top_matches": [],
                "threshold": effective_threshold,
            }

        valid_rows: List[Dict[str, Any]] = []
        valid_vectors: List[np.ndarray] = []
        for row, vec in zip(self._rows, self._vectors):
            if vec.shape[0] == query.shape[0]:
                valid_rows.append(row)
                valid_vectors.append(vec)

        if not valid_vectors:
            return {
                "matched": False,
                "best_score": 0.0,
                "best": None,
                "top_matches": [],
                "threshold": effective_threshold,
            }

        matrix = np.vstack(valid_vectors).astype(np.float32)
        similarities = matrix @ query

        k = max(1, min(int(top_k), len(valid_rows)))
        top_local = np.argpartition(-similarities, kth=k - 1)[:k]
        top_sorted = top_local[np.argsort(-similarities[top_local])]
        candidate_count = len(valid_rows)

        if (
            threshold_override is None
            and candidate_count > 0
            and candidate_count <= max(1, self.small_gallery_candidate_limit)
        ):
            effective_threshold = max(
                effective_threshold,
                float(self.small_gallery_min_threshold),
            )

        top_matches: List[Dict[str, Any]] = []
        for local_idx in top_sorted:
            row = valid_rows[int(local_idx)]
            score = float(similarities[int(local_idx)])
            top_matches.append(
                {
                    "personnel_id": row["personnel_id"],
                    "full_name": row["full_name"],
                    "score": score,
                    "is_active": row["is_active"],
                    "is_blacklisted": row["is_blacklisted"],
                    "face_encoding_id": row["face_encoding_id"],
                    "pose_label": row["pose_label"],
                    "quality_score": row["quality_score"],
                    "model_name": row["model_name"],
                }
            )

        best = top_matches[0] if top_matches else None
        best_score = float(best["score"]) if best else 0.0
        matched = bool(best and best_score >= effective_threshold)

        return {
            "matched": matched,
            "best_score": best_score,
            "best": best,
            "top_matches": top_matches,
            "threshold": effective_threshold,
            "candidate_count": candidate_count,
        }

    def _match_pgvector(self, query: np.ndarray, top_k: int) -> Optional[Dict[str, Any]]:
        k = max(1, min(int(top_k), 50))
        sql = text(
            """
            SELECT
                fe.personnel_id AS personnel_id,
                p.full_name AS full_name,
                p.is_active AS is_active,
                p.is_blacklisted AS is_blacklisted,
                fe.id AS face_encoding_id,
                fi.pose_label AS pose_label,
                COALESCE(fe.quality_score, 0) AS quality_score,
                COALESCE(fe.model_name, 'unknown') AS model_name,
                1 - (fe.embedding_vector <=> CAST(:query_vector AS vector)) AS score
            FROM face_encodings fe
            JOIN personnel p ON p.id = fe.personnel_id
            LEFT JOIN face_images fi ON fi.id = fe.face_image_id
            WHERE fe.is_active IS TRUE
              AND fe.embedding_vector IS NOT NULL
            ORDER BY fe.embedding_vector <=> CAST(:query_vector AS vector)
            LIMIT :limit_value
            """
        )

        try:
            vector_literal = self._to_vector_literal(query)
            rows = (
                self.db.execute(
                    sql,
                    {
                        "query_vector": vector_literal,
                        "limit_value": k,
                    },
                )
                .mappings()
                .all()
            )
        except Exception as exc:
            logger.warning("pgvector face match query failed, falling back to NumPy matcher: %s", exc)
            self._safe_rollback()
            self.use_pgvector = False
            self.backend = "cosine_numpy"
            return None

        top_matches: List[Dict[str, Any]] = []
        for row in rows:
            model_name = str(row.get("model_name") or "unknown")
            if (not self.allow_fallback_models) and model_name.lower().startswith("fallback"):
                continue
            score = float(row.get("score") or 0.0)
            top_matches.append(
                {
                    "personnel_id": int(row["personnel_id"]),
                    "full_name": str(row["full_name"] or "UNKNOWN"),
                    "score": score,
                    "is_active": bool(row["is_active"]),
                    "is_blacklisted": bool(row["is_blacklisted"]),
                    "face_encoding_id": int(row["face_encoding_id"]),
                    "pose_label": row.get("pose_label"),
                    "quality_score": float(row.get("quality_score") or 0.0),
                    "model_name": model_name,
                }
            )

        best = top_matches[0] if top_matches else None
        best_score = float(best["score"]) if best else 0.0
        matched = bool(best and best_score >= self.threshold)

        return {
            "matched": matched,
            "best_score": best_score,
            "best": best,
            "top_matches": top_matches,
            "threshold": self.threshold,
            "candidate_count": len(top_matches),
        }

    def _detect_pgvector_support(self) -> bool:
        if not self.pgvector_enabled:
            return False

        try:
            dialect_name = self.db.get_bind().dialect.name
        except Exception as exc:
            logger.debug("Unable to inspect database dialect for face matcher: %s", exc)
            return False

        if dialect_name != "postgresql":
            return False

        check_sql = text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'face_encodings'
                  AND column_name = 'embedding_vector'
            )
            """
        )
        try:
            has_column = bool(self.db.execute(check_sql).scalar())
            return has_column
        except Exception as exc:
            logger.debug("pgvector support probe failed: %s", exc)
            self._safe_rollback()
            return False

    def _to_vector_literal(self, vector: np.ndarray) -> str:
        return "[" + ",".join(f"{float(v):.8f}" for v in vector.tolist()) + "]"

    def _safe_rollback(self) -> None:
        try:
            self.db.rollback()
        except Exception as exc:
            logger.debug("Face matcher rollback failed: %s", exc)

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            return vector.astype(np.float32)
        return (vector / norm).astype(np.float32)
