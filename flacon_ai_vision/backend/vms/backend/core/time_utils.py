from __future__ import annotations

from datetime import UTC, datetime


def utc_now_naive() -> datetime:
    """
    Return the current UTC timestamp as a naive datetime.

    This preserves legacy API/database formatting while avoiding direct
    use of deprecated datetime.utcnow() on newer Python versions.
    """

    return datetime.now(UTC).replace(tzinfo=None)


def utc_now_naive_iso() -> str:
    return utc_now_naive().isoformat()


def utc_now_naive_strftime(fmt: str) -> str:
    return utc_now_naive().strftime(fmt)
