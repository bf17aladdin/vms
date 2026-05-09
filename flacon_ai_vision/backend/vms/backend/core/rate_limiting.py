"""
Rate limiting module for Falcon AI Vision.
Uses slowapi with Redis-backed storage when configured.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import settings

logger = logging.getLogger("falcon_ai_vision")


def _build_default_limit() -> str:
    requests = max(1, int(settings.RATE_LIMIT_REQUESTS))
    window = max(1, int(settings.RATE_LIMIT_WINDOW_SECONDS))
    return f"{requests}/{window} seconds"


def _build_storage_uri() -> str:
    uri = (settings.RATE_LIMIT_STORAGE_URI or "").strip()
    if not uri:
        return "memory://"
    if uri.startswith("redis://") or uri.startswith("rediss://"):
        return uri
    if uri == "memory://":
        return uri
    # Unknown backend value: fail-safe to in-memory.
    return "memory://"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_build_default_limit()],
    storage_uri=_build_storage_uri(),
)


def setup_rate_limiting(app: FastAPI, enabled: bool = True) -> FastAPI:
    if not enabled or not settings.RATE_LIMIT_ENABLED:
        logger.info("Rate limiting disabled")
        return app

    app.state.limiter = limiter

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        limit_value = None
        try:
            limit_value = str(exc.detail).split(" ")[0]
        except Exception:
            limit_value = str(settings.RATE_LIMIT_REQUESTS)
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "x_ratelimit_limit": limit_value,
                "error": "too_many_requests",
            },
        )

    logger.info(
        "Rate limiting configured: limit=%s storage=%s",
        _build_default_limit(),
        _build_storage_uri(),
    )
    return app


def get_rate_limiter():
    return limiter


class RateLimits:
    PUBLIC_READ = "200/minute"
    PUBLIC_WRITE = "60/minute"
    LOGIN = "15/minute"
    REGISTER = "10/minute"
    WEBSOCKET = "1500/minute"
    INTERNAL_READ = "2000/minute"
    INTERNAL_WRITE = "1000/minute"
    AI_INFERENCE = "90/minute"
    HEALTH_CHECK = "3000/minute"
