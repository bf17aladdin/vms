from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from vms.backend.core.config import settings


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for centralized log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for attr in ("request_id", "method", "path", "status_code", "latency_ms", "user_id", "camera_id"):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _build_console_handler(use_json: bool) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    if use_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    return handler


def _build_file_handler(log_file_path: str, use_json: bool) -> logging.Handler | None:
    try:
        path = Path(log_file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            filename=str(path),
            maxBytes=int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024))),
            backupCount=int(os.getenv("LOG_BACKUP_COUNT", "10")),
            encoding="utf-8",
        )
        if use_json:
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s %(name)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        return handler
    except Exception:
        return None


def configure_logging() -> None:
    """Configure root logging once for API runtime."""
    root_logger = logging.getLogger()
    if getattr(root_logger, "_falcon_logging_configured", False):
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = bool(settings.LOG_JSON)

    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(_build_console_handler(use_json))

    file_handler = _build_file_handler(settings.LOG_FILE_PATH, use_json)
    if file_handler is not None:
        root_logger.addHandler(file_handler)

    root_logger._falcon_logging_configured = True  # type: ignore[attr-defined]
