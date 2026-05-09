# vms/backend/core/http_security.py - HTTP header validation + response headers

from __future__ import annotations

from fastapi import Request
from starlette.responses import Response

from .config import settings


def _normalize_host(value: str) -> str:
    host = str(value or "").strip().lower()
    if not host:
        return ""
    if host.startswith("["):
        end = host.find("]")
        if end != -1:
            return host[1:end]
        return host
    if ":" in host:
        return host.split(":", 1)[0]
    return host


def _match_host(host: str, allowed: str) -> bool:
    normalized = _normalize_host(allowed)
    if not normalized:
        return False
    if normalized == "*":
        return True
    if normalized.startswith("*."):
        suffix = normalized[1:]
        return host.endswith(suffix)
    return host == normalized


def is_host_allowed(host: str, allowed_hosts: list[str]) -> bool:
    if not allowed_hosts:
        return True
    if not host:
        return False
    for allowed in allowed_hosts:
        if _match_host(host, allowed):
            return True
    return False


def is_https_request(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded:
        proto = forwarded.split(",", 1)[0].strip().lower()
        return proto == "https"
    forwarded = request.headers.get("x-forwarded-protocol")
    if forwarded:
        proto = forwarded.split(",", 1)[0].strip().lower()
        return proto == "https"
    forwarded = request.headers.get("forwarded")
    if forwarded:
        parts = [part.strip() for part in forwarded.split(";")]
        for part in parts:
            if part.lower().startswith("proto="):
                proto = part.split("=", 1)[1].strip().lower()
                return proto == "https"
    return request.url.scheme == "https"


def validate_request_headers(request: Request) -> tuple[bool, str]:
    host = _normalize_host(request.headers.get("host", ""))
    if settings.ALLOWED_HOSTS and not is_host_allowed(host, settings.ALLOWED_HOSTS):
        return False, "Invalid Host header"
    if settings.REQUIRE_HTTPS and not is_https_request(request):
        return False, "HTTPS required"
    return True, ""


def apply_security_headers(response: Response, *, is_https: bool) -> None:
    if not settings.SECURITY_HEADERS_ENABLED:
        return

    base_headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-site",
    }

    for key, value in base_headers.items():
        if key not in response.headers:
            response.headers[key] = value

    if settings.IS_PROD and is_https:
        hsts = f"max-age={settings.HSTS_MAX_AGE}"
        if settings.HSTS_INCLUDE_SUBDOMAINS:
            hsts += "; includeSubDomains"
        if "Strict-Transport-Security" not in response.headers:
            response.headers["Strict-Transport-Security"] = hsts
