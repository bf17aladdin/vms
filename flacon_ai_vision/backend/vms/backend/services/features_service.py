from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_operation_mode(operation_mode: str | None, project_type: str) -> str:
    raw = str(operation_mode or "").strip().lower()
    if raw in {"family", "enterprise"}:
        return raw
    return "family" if project_type == "home" else "enterprise"


def _bool_from_collection(values: list[str], key: str) -> bool:
    return str(key).strip().lower() in {str(item).strip().lower() for item in values}


def build_feature_payload(
    *,
    config: Dict[str, Any],
    subscription: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    project_type = str(config.get("project_type") or "business").strip().lower() or "business"
    operation_mode = _normalize_operation_mode(config.get("operation_mode"), project_type)
    detection_types = [str(item).strip().lower() for item in (config.get("detection_types") or [])]

    is_enterprise = operation_mode == "enterprise"
    is_soc = project_type == "soc"

    flags = {
        # Global product behaviors
        "rules_engine": bool(is_enterprise),
        "simple_notifications": not is_enterprise,
        "advanced_notifications": bool(is_enterprise),

        # UI sections
        "ui_facial_recognition": bool(is_enterprise),
        "ui_zones": bool(is_enterprise),
        "ui_personnel": bool(is_enterprise),
        "ui_personnel_entry_exit": bool(is_enterprise),
        "ui_personnel_history": bool(is_enterprise),
        "ui_vehicles": bool(is_enterprise),
        "ui_vehicle_entry_exit": bool(is_enterprise),
        "ui_vehicle_registry": bool(is_enterprise),
        "ui_map": bool(is_enterprise),
        "ui_reporting": bool(is_enterprise),
        "ui_users": bool(is_enterprise),

        # SOC-only surface
        "ui_security_center": bool(is_soc),
        "ui_security_config": bool(is_soc),
        "ui_security_realtime": bool(is_soc),
        "ui_vehicle_multicam": bool(is_soc),
        "ui_unknown_detections": bool(is_soc),
        "ui_ai_monitoring": bool(is_soc),
        "ui_admin": bool(is_soc),
    }

    categories = {
        "person": _bool_from_collection(detection_types, "person"),
        "vehicle": _bool_from_collection(detection_types, "vehicle"),
    }

    rules = {
        "engine_enabled": bool(is_enterprise),
        "visitor_zone": bool(is_enterprise),
        "off_hours_presence": bool(is_enterprise),
        "unknown_vehicle": bool(is_enterprise),
    }

    alerts = {
        "simple": not is_enterprise,
        "advanced": bool(is_enterprise),
    }

    return {
        "operation_mode": operation_mode,
        "project_type": project_type,
        "flags": flags,
        "categories": categories,
        "rules": rules,
        "alerts": alerts,
        "subscription": subscription or {},
        "config_snapshot": {
            "ui_preset": config.get("ui_preset"),
            "camera_limit": config.get("camera_limit"),
            "detection_types": list(detection_types),
        },
        "timestamp": _utc_now(),
    }
