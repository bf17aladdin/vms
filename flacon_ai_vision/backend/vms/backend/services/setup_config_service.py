from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from vms.backend.core.config import DB_DIR

logger = logging.getLogger(__name__)

DEFAULT_PROFILES: Dict[str, Dict[str, object]] = {
    "maison": {
        "camera_limit": 4,
        "detection_types": ["person", "vehicle"],
        "alert_types": ["motion", "person", "vehicle", "system"],
        "alert_channels": ["ui", "email"],
        "ui_preset": "home",
    },
    "magasin": {
        "camera_limit": 8,
        "detection_types": ["person", "vehicle"],
        "alert_types": ["motion", "person", "vehicle", "alarm", "system"],
        "alert_channels": ["ui", "email"],
        "ui_preset": "retail",
    },
    "entreprise": {
        "camera_limit": 32,
        "detection_types": ["person", "vehicle"],
        "alert_types": ["motion", "person", "vehicle", "face", "alarm", "system"],
        "alert_channels": ["ui", "email", "sms"],
        "ui_preset": "enterprise",
    },
    "parking": {
        "camera_limit": 16,
        "detection_types": ["vehicle"],
        "alert_types": ["motion", "vehicle", "alarm", "system"],
        "alert_channels": ["ui", "email", "sms"],
        "ui_preset": "parking",
    },
    "securite_avancee": {
        "camera_limit": 64,
        "detection_types": ["person", "vehicle"],
        "alert_types": ["motion", "person", "vehicle", "face", "alarm", "system"],
        "alert_channels": ["ui", "email", "sms", "webhook"],
        "ui_preset": "advanced",
    },
}


PERSONNEL_VISIBLE_FIELDS_ALLOWED = [
    "last_name",
    "first_name",
    "id_number",
    "reference_id",
    "role",
    "category",
    "unit",
    "email",
    "phone",
]

DEFAULT_PERSONNEL_VISIBLE_FIELDS: Dict[str, List[str]] = {
    "home": [
        "last_name",
        "first_name",
        "role",
        "phone",
    ],
    "business": [
        "last_name",
        "first_name",
        "id_number",
        "role",
        "unit",
        "email",
        "phone",
    ],
    "soc": [
        "last_name",
        "first_name",
        "id_number",
        "reference_id",
        "role",
        "category",
        "unit",
        "email",
        "phone",
    ],
}

DEFAULT_PERSONNEL_CUSTOM_FIELDS: Dict[str, List[Dict[str, object]]] = {
    "home": [
        {
            "key": "level",
            "label": "Level",
            "type": "select",
            "required": False,
            "options": ["Normal", "Priority"],
        }
    ],
    "business": [
        {
            "key": "level",
            "label": "Level",
            "type": "select",
            "required": False,
            "options": ["Staff", "Admin", "VIP"],
        }
    ],
    "soc": [],
}


def _usage_to_project_type(usage_type: str) -> str:
    normalized = str(usage_type or "").strip().lower()
    if normalized in {"maison"}:
        return "home"
    if normalized in {"magasin", "entreprise", "parking"}:
        return "business"
    if normalized in {"securite_avancee", "soc", "security", "security_ops"}:
        return "soc"
    return "business"


def _operation_mode_from_project(project_type: str) -> str:
    normalized = str(project_type or "").strip().lower()
    return "family" if normalized == "home" else "enterprise"


def _project_type_from_operation_mode(operation_mode: str) -> Optional[str]:
    normalized = str(operation_mode or "").strip().lower()
    if normalized == "family":
        return "home"
    if normalized == "enterprise":
        return "business"
    return None


def _normalize_personnel_custom_fields(raw_fields: object) -> List[Dict[str, object]]:
    if not isinstance(raw_fields, list):
        return []
    normalized: List[Dict[str, object]] = []
    for entry in raw_fields:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if not key:
            continue
        label = str(entry.get("label") or key).strip()
        field_type = str(entry.get("type") or "text").strip().lower() or "text"
        required = bool(entry.get("required", False))
        options = entry.get("options")
        if isinstance(options, list):
            clean_options = [str(opt).strip() for opt in options if str(opt).strip()]
        else:
            clean_options = []
        normalized.append(
            {
                "key": key,
                "label": label,
                "type": field_type,
                "required": required,
                "options": clean_options,
            }
        )
    return normalized


def _default_personnel_custom_fields(project_type: str) -> List[Dict[str, object]]:
    defaults = DEFAULT_PERSONNEL_CUSTOM_FIELDS.get(project_type, [])
    return [
        {
            "key": str(field.get("key") or "").strip(),
            "label": str(field.get("label") or "").strip(),
            "type": str(field.get("type") or "text").strip().lower() or "text",
            "required": bool(field.get("required", False)),
            "options": list(field.get("options") or []),
        }
        for field in defaults
        if field.get("key")
    ]


def _apply_personnel_level_migration(config: "SetupConfig") -> bool:
    if config.personnel_level_migrated:
        return False
    if config.project_type not in {"home", "business"}:
        return False
    has_level = any(
        str(field.get("key") or "").strip().lower() == "level"
        for field in config.personnel_custom_fields
        if isinstance(field, dict)
    )
    if not has_level:
        defaults = _default_personnel_custom_fields(config.project_type)
        level_defaults = [
            field for field in defaults if str(field.get("key") or "").strip().lower() == "level"
        ]
        if level_defaults:
            config.personnel_custom_fields = list(config.personnel_custom_fields) + level_defaults
    config.personnel_level_migrated = True
    return True


def _normalize_personnel_visible_fields(raw_fields: object, project_type: str) -> List[str]:
    allowed = set(PERSONNEL_VISIBLE_FIELDS_ALLOWED)
    normalized: List[str] = []
    if isinstance(raw_fields, list):
        for entry in raw_fields:
            key = str(entry or "").strip()
            if not key or key not in allowed:
                continue
            if key not in normalized:
                normalized.append(key)

    defaults = DEFAULT_PERSONNEL_VISIBLE_FIELDS.get(project_type, DEFAULT_PERSONNEL_VISIBLE_FIELDS["business"])
    if not normalized:
        normalized = list(defaults)

    required = {"last_name", "first_name"}
    if project_type == "soc":
        required.update({"id_number", "reference_id", "role", "category"})
    for key in required:
        if key not in normalized:
            normalized.append(key)

    ordered = [key for key in defaults if key in normalized]
    trailing = [key for key in normalized if key not in ordered]
    return ordered + trailing


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SetupConfig:
    usage_type: str
    project_type: str
    operation_mode: str
    camera_limit: int
    detection_types: List[str]
    alert_types: List[str]
    alert_channels: List[str]
    ui_preset: str
    connect_email: Optional[str] = None
    configured: bool = False
    updated_at: Optional[str] = None
    subscription_active: bool = False
    subscription_tier: str = "free"
    subscription_expires_at: Optional[str] = None
    personnel_custom_fields: List[Dict[str, object]] = field(default_factory=list)
    personnel_visible_fields: List[str] = field(default_factory=list)
    personnel_level_migrated: bool = False


class SetupConfigService:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or (DB_DIR / "setup_config.json")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()

    def _default_config(self, usage_type: str = "maison") -> SetupConfig:
        defaults = DEFAULT_PROFILES.get(usage_type, DEFAULT_PROFILES["maison"])
        project_type = _usage_to_project_type(usage_type)
        operation_mode = _operation_mode_from_project(project_type)
        level_migrated = project_type in {"home", "business"}
        return SetupConfig(
            usage_type=usage_type,
            project_type=project_type,
            operation_mode=operation_mode,
            camera_limit=int(defaults["camera_limit"]),
            detection_types=list(defaults["detection_types"]),
            alert_types=list(defaults.get("alert_types") or []),
            alert_channels=list(defaults["alert_channels"]),
            ui_preset=str(defaults["ui_preset"]),
            connect_email=None,
            configured=False,
            updated_at=None,
            subscription_active=False,
            subscription_tier="free",
            subscription_expires_at=None,
            personnel_custom_fields=_default_personnel_custom_fields(project_type),
            personnel_visible_fields=_normalize_personnel_visible_fields(None, project_type),
            personnel_level_migrated=level_migrated,
        )

    def _load_config(self) -> SetupConfig:
        if self.config_path.exists():
            try:
                raw = json.loads(self.config_path.read_text(encoding="utf-8"))
                usage_type = str(raw.get("usage_type") or "maison")
                defaults = DEFAULT_PROFILES.get(usage_type, DEFAULT_PROFILES["maison"])
                raw_operation_mode = str(raw.get("operation_mode") or "").strip().lower()
                project_type = str(raw.get("project_type") or _usage_to_project_type(usage_type))
                if "project_type" not in raw and raw_operation_mode:
                    mapped = _project_type_from_operation_mode(raw_operation_mode)
                    if mapped:
                        project_type = mapped
                operation_mode = _operation_mode_from_project(project_type)
                personnel_custom_fields = (
                    _normalize_personnel_custom_fields(raw.get("personnel_custom_fields"))
                    if "personnel_custom_fields" in raw
                    else _default_personnel_custom_fields(project_type)
                )
                config = SetupConfig(
                    usage_type=usage_type,
                    project_type=project_type,
                    operation_mode=operation_mode,
                    camera_limit=int(raw.get("camera_limit") or defaults["camera_limit"]),
                    detection_types=list(raw.get("detection_types") or defaults["detection_types"]),
                    alert_types=list(raw.get("alert_types") or defaults.get("alert_types") or []),
                    alert_channels=list(raw.get("alert_channels") or defaults["alert_channels"]),
                    ui_preset=str(raw.get("ui_preset") or defaults["ui_preset"]),
                    connect_email=raw.get("connect_email"),
                    configured=bool(raw.get("configured", False)),
                    updated_at=raw.get("updated_at"),
                    subscription_active=bool(raw.get("subscription_active", False)),
                    subscription_tier=str(raw.get("subscription_tier") or "free"),
                    subscription_expires_at=raw.get("subscription_expires_at"),
                    personnel_custom_fields=personnel_custom_fields,
                    personnel_visible_fields=_normalize_personnel_visible_fields(
                        raw.get("personnel_visible_fields"),
                        project_type,
                    ),
                    personnel_level_migrated=bool(raw.get("personnel_level_migrated", False)),
                )
                if _apply_personnel_level_migration(config):
                    try:
                        self.config_path.write_text(
                            json.dumps(asdict(config), indent=2),
                            encoding="utf-8",
                        )
                    except Exception as exc:
                        logger.warning("Failed to persist personnel level migration: %s", exc)
                return config
            except Exception as exc:
                logger.warning("Failed to load setup config: %s", exc)
        return self._default_config()

    def _save_config(self) -> None:
        payload = asdict(self.config)
        self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_config(self) -> Dict[str, object]:
        return asdict(self.config)

    def get_presets(self) -> Dict[str, Dict[str, object]]:
        return DEFAULT_PROFILES.copy()

    def update_config(self, payload: Dict[str, object]) -> Dict[str, object]:
        usage_type = str(payload.get("usage_type") or self.config.usage_type)
        defaults = DEFAULT_PROFILES.get(usage_type, DEFAULT_PROFILES["maison"])

        self.config.usage_type = usage_type
        operation_mode = str(payload.get("operation_mode") or "").strip().lower()
        project_type = _project_type_from_operation_mode(operation_mode) or str(
            payload.get("project_type") or _usage_to_project_type(usage_type)
        )
        self.config.project_type = project_type
        self.config.operation_mode = _operation_mode_from_project(project_type)
        self.config.camera_limit = int(payload.get("camera_limit") or defaults["camera_limit"])
        self.config.detection_types = list(payload.get("detection_types") or defaults["detection_types"])
        self.config.alert_types = list(payload.get("alert_types") or defaults.get("alert_types") or [])
        self.config.alert_channels = list(payload.get("alert_channels") or defaults["alert_channels"])
        self.config.ui_preset = str(payload.get("ui_preset") or defaults["ui_preset"])
        self.config.connect_email = (
            str(payload.get("connect_email")).strip()
            if payload.get("connect_email")
            else None
        )
        if "personnel_custom_fields" in payload:
            self.config.personnel_custom_fields = _normalize_personnel_custom_fields(
                payload.get("personnel_custom_fields")
            )
        if "personnel_visible_fields" in payload:
            self.config.personnel_visible_fields = _normalize_personnel_visible_fields(
                payload.get("personnel_visible_fields"),
                project_type,
            )
        if not self.config.personnel_visible_fields:
            self.config.personnel_visible_fields = _normalize_personnel_visible_fields(
                None,
                project_type,
            )
        _apply_personnel_level_migration(self.config)
        self.config.configured = True
        self.config.updated_at = _utc_now()

        self._save_config()
        return asdict(self.config)


_setup_config_service: Optional[SetupConfigService] = None


def get_setup_config_service() -> SetupConfigService:
    global _setup_config_service
    if _setup_config_service is None:
        _setup_config_service = SetupConfigService()
    return _setup_config_service
