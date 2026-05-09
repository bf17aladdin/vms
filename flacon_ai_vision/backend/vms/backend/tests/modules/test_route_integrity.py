from __future__ import annotations

from collections import defaultdict

from starlette.routing import WebSocketRoute

from vms.backend.main import app


def test_no_duplicate_http_route_method_pairs() -> None:
    seen: dict[tuple[str, str], list[str]] = defaultdict(list)

    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue

        for method in sorted(methods):
            key = (path, method.upper())
            seen[key].append(getattr(route, "name", repr(route)))

    duplicates = {
        key: names
        for key, names in seen.items()
        if len(names) > 1
    }
    assert not duplicates, f"Duplicate HTTP route method/path pairs detected: {duplicates}"


def test_no_duplicate_websocket_paths() -> None:
    seen: dict[str, list[str]] = defaultdict(list)

    for route in app.routes:
        if isinstance(route, WebSocketRoute):
            seen[route.path].append(getattr(route, "name", repr(route)))

    duplicates = {
        path: names
        for path, names in seen.items()
        if len(names) > 1
    }
    assert not duplicates, f"Duplicate websocket paths detected: {duplicates}"


def test_openapi_has_no_double_api_prefix_paths() -> None:
    schema = app.openapi()
    bad_paths = sorted(path for path in schema.get("paths", {}) if path.startswith("/api/api/"))
    assert not bad_paths, f"OpenAPI contains double-prefixed API paths: {bad_paths}"
