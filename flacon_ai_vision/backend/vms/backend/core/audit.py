from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from vms.backend.core.database import SessionLocal

logger = logging.getLogger("falcon_ai_vision.audit")


def _normalize_client_ip(ip_address: Optional[str]) -> Optional[str]:
    if ip_address is None:
        return None
    return ip_address.strip()[:64] or None


def write_audit_log(
    *,
    event_type: str,
    action: str,
    method: str,
    path: str,
    status_code: int,
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    request_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Best-effort audit logger; never raises in request path."""
    try:
        from vms.backend.models import AuditLog

        db = SessionLocal()
        try:
            row = AuditLog(
                user_id=user_id,
                username=username,
                event_type=event_type[:60],
                action=action[:80],
                method=method[:10],
                path=path[:255],
                status_code=int(status_code),
                ip_address=_normalize_client_ip(ip_address),
                user_agent=(user_agent or "")[:255] or None,
                request_id=(request_id or "")[:64] or None,
                details=details or {},
                created_at=datetime.now(timezone.utc),
            )
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug("audit log write skipped: %s", exc)
