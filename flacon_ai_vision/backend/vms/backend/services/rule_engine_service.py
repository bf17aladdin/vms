from __future__ import annotations

import json
import logging
import os
import time as time_module
from datetime import datetime, time
from threading import RLock
from pathlib import Path
from typing import Any, Dict, List, Optional

from vms.backend.core.config import DB_DIR
from vms.backend.core.database import get_db
from vms.backend.models import AlertRule, AlertRuleCondition
from vms.backend.services.setup_config_service import get_setup_config_service

logger = logging.getLogger(__name__)


DEFAULT_RULES: List[Dict[str, Any]] = [
    {
        "id": "visitor_in_restricted_zone",
        "type": "visitor_in_restricted_zone",
        "enabled": True,
        "conditions": {
            "event_type": "person",
            "person_status": "unknown",
            "zone_restricted": True,
        },
        "action": {
            "severity": "high",
            "message": "Visitor detected in restricted zone",
        },
    },
    {
        "id": "presence_outside_allowed_hours",
        "type": "presence_outside_allowed_hours",
        "enabled": True,
        "conditions": {
            "event_type": "person",
            "outside_hours": True,
            "allowed_hours": {"start": "08:00", "end": "18:00"},
            "allowed_days": [0, 1, 2, 3, 4],
        },
        "action": {
            "severity": "medium",
            "message": "Presence detected outside allowed hours",
        },
    },
    {
        "id": "unknown_vehicle_detection",
        "type": "unknown_vehicle_detection",
        "enabled": True,
        "conditions": {
            "event_type": "vehicle",
            "vehicle_known": False,
            "plate_required": True,
            "plate_confidence_min": 0.7,
            "dedup_seconds": 30,
        },
        "action": {
            "severity": "medium",
            "message": "Unknown vehicle detected",
        },
    },
]


def _normalize_operation_mode(operation_mode: str | None, project_type: str) -> str:
    raw = str(operation_mode or "").strip().lower()
    if raw in {"family", "enterprise"}:
        return raw
    return "family" if project_type == "home" else "enterprise"


def _parse_time(value: object) -> Optional[time]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parts = raw.split(":")
        if len(parts) < 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return time(hour=hour, minute=minute)
    except Exception:
        return None


def _parse_event_timestamp(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _is_within_hours(timestamp: datetime, start_at: time, end_at: time) -> bool:
    current = timestamp.time()
    if start_at <= end_at:
        return start_at <= current <= end_at
    # Overnight range (e.g. 22:00 -> 06:00)
    return current >= start_at or current <= end_at


def _matches_time_window(event: Dict[str, Any], conditions: Dict[str, Any]) -> Optional[bool]:
    allowed_hours = conditions.get("allowed_hours") or {}
    start_at = _parse_time(allowed_hours.get("start"))
    end_at = _parse_time(allowed_hours.get("end"))
    if start_at is None or end_at is None:
        return None

    timestamp = _parse_event_timestamp(event.get("timestamp"))
    if timestamp is None:
        return None

    allowed_days = conditions.get("allowed_days")
    if isinstance(allowed_days, list) and allowed_days:
        if timestamp.weekday() not in {int(day) for day in allowed_days}:
            return False

    return _is_within_hours(timestamp, start_at, end_at)


def _event_person_status(event: Dict[str, Any]) -> str:
    raw = str(event.get("person_status") or "").strip().lower()
    if raw:
        return raw
    is_known = event.get("is_known")
    if isinstance(is_known, bool):
        return "known" if is_known else "unknown"
    return ""


def _event_vehicle_known(event: Dict[str, Any]) -> Optional[bool]:
    value = event.get("vehicle_known")
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in {"true", "yes", "1"}:
        return True
    if raw in {"false", "no", "0"}:
        return False
    return None


def _event_plate_text(event: Dict[str, Any]) -> str:
    raw = event.get("plate_text")
    if not raw:
        raw = event.get("plate_number")
    return str(raw or "").strip().upper()


def _event_plate_confidence(event: Dict[str, Any]) -> Optional[float]:
    raw = event.get("plate_confidence")
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def evaluate_rules(event: Dict[str, Any], rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Evaluate rules against a single event and return triggered rules.

    Args:
        event: dict containing detection context.
        rules: list of rule dicts.
    """
    if not isinstance(event, dict):
        return []

    triggered: List[Dict[str, Any]] = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        if not bool(rule.get("enabled", True)):
            continue

        conditions = rule.get("conditions") or {}
        if not isinstance(conditions, dict):
            conditions = {}

        event_type = str(conditions.get("event_type") or "").strip().lower()
        if event_type and str(event.get("type") or "").strip().lower() != event_type:
            continue

        person_status = str(conditions.get("person_status") or "").strip().lower()
        if person_status:
            if _event_person_status(event) != person_status:
                continue

        if "is_known" in conditions:
            expected_known = bool(conditions.get("is_known"))
            actual_known = event.get("is_known")
            if isinstance(actual_known, bool):
                if actual_known != expected_known:
                    continue
            else:
                continue

        if "vehicle_known" in conditions:
            expected_known = bool(conditions.get("vehicle_known"))
            actual_known = _event_vehicle_known(event)
            if actual_known is None or actual_known != expected_known:
                continue

        if conditions.get("plate_required") is True:
            if not _event_plate_text(event):
                continue

        if "plate_confidence_min" in conditions:
            threshold = conditions.get("plate_confidence_min")
            try:
                min_conf = float(threshold)
            except Exception:
                min_conf = None
            if min_conf is not None:
                conf_value = _event_plate_confidence(event)
                if conf_value is None or conf_value < min_conf:
                    continue

        if "zone_restricted" in conditions:
            expected_restricted = bool(conditions.get("zone_restricted"))
            actual_restricted = bool(event.get("zone_restricted"))
            if actual_restricted != expected_restricted:
                continue

        if conditions.get("outside_hours") is True:
            within_hours = _matches_time_window(event, conditions)
            if within_hours is None or within_hours:
                continue

        triggered.append(rule)

    return triggered


class RuleEngineService:
    """Simple rule engine backed by database with local caching."""

    def __init__(self, rules_path: Optional[Path] = None):
        self.rules_path = rules_path or (DB_DIR / "rules_engine.json")
        self.rules_path.parent.mkdir(parents=True, exist_ok=True)
        self._recent_hits: Dict[tuple[str, str], float] = {}
        self._recent_lock = RLock()
        self._rules_lock = RLock()
        self._cache_ttl_sec = float(os.getenv("RULE_ENGINE_CACHE_TTL_SEC", "30"))
        self._rules_cache: Dict[Optional[int], tuple[float, List[Dict[str, Any]]]] = {}

    @staticmethod
    def _apply_rule_defaults(rules: List[Dict[str, Any]]) -> bool:
        """Ensure critical defaults are present without overriding user choices."""
        updated = False
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id") or rule.get("type") or "").strip().lower()
            if rule_id not in {"unknown_vehicle_detection", "unknown_vehicle"}:
                continue
            conditions = rule.get("conditions")
            if not isinstance(conditions, dict):
                conditions = {}
                rule["conditions"] = conditions
                updated = True

            if "plate_required" not in conditions:
                conditions["plate_required"] = True
                updated = True
            if "plate_confidence_min" not in conditions:
                conditions["plate_confidence_min"] = 0.7
                updated = True
            if "dedup_seconds" not in conditions:
                conditions["dedup_seconds"] = 30
                updated = True
        return updated

    def _load_seed_rules(self) -> List[Dict[str, Any]]:
        if self.rules_path.exists():
            try:
                raw = json.loads(self.rules_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    return raw
            except Exception as exc:
                logger.warning("Failed to load JSON seed rules: %s", exc)
        return list(DEFAULT_RULES)

    def _serialize_rule(self, rule: AlertRule) -> Dict[str, Any]:
        conditions: Dict[str, Any] = {}
        for cond in rule.conditions:
            conditions[str(cond.key)] = cond.value
        payload = {
            "id": rule.rule_key or str(rule.id),
            "type": rule.rule_type or rule.rule_key or str(rule.id),
            "enabled": bool(rule.is_active),
            "conditions": conditions,
            "action": rule.action or {},
        }
        self._apply_rule_defaults([payload])
        return payload

    def _seed_defaults(self, db, tenant_id: Optional[int]) -> None:
        seed_rules = self._load_seed_rules()
        for rule in seed_rules:
            rule_key = str(rule.get("id") or rule.get("type") or "").strip().lower()
            if not rule_key:
                continue
            existing = (
                db.query(AlertRule)
                .filter(AlertRule.rule_key == rule_key)
                .filter(AlertRule.tenant_id == tenant_id)
                .first()
            )
            if existing:
                continue
            conditions = rule.get("conditions") or {}
            event_type = str(conditions.get("event_type") or "custom").strip().lower()
            alert_rule = AlertRule(
                tenant_id=tenant_id,
                rule_key=rule_key,
                rule_type=str(rule.get("type") or rule_key),
                name=rule_key.replace("_", " ").title(),
                description=str((rule.get("action") or {}).get("message") or ""),
                event_type=event_type or "custom",
                camera_id=None,
                min_confidence=float(conditions.get("min_confidence") or 0.5),
                min_object_count=int(conditions.get("min_object_count") or 1),
                enable_notification=True,
                enable_recording=True,
                enable_alert_sound=False,
                is_active=bool(rule.get("enabled", True)),
                action=rule.get("action") or {},
            )
            db.add(alert_rule)
            db.flush()
            for key, value in (conditions if isinstance(conditions, dict) else {}).items():
                db.add(
                    AlertRuleCondition(
                        rule_id=alert_rule.id,
                        key=str(key),
                        value=value,
                    )
                )
        db.commit()

    def _get_rules_from_db(self, tenant_id: Optional[int]) -> List[Dict[str, Any]]:
        db = next(get_db())
        try:
            query = db.query(AlertRule).filter(AlertRule.rule_key.isnot(None))
            if tenant_id is not None:
                query = query.filter(AlertRule.tenant_id == tenant_id)
            rules = query.order_by(AlertRule.id.asc()).all()

            if not rules and tenant_id is not None:
                fallback = (
                    db.query(AlertRule)
                    .filter(AlertRule.rule_key.isnot(None))
                    .filter(AlertRule.tenant_id.is_(None))
                    .order_by(AlertRule.id.asc())
                    .all()
                )
                rules = fallback

            if not rules:
                self._seed_defaults(db, tenant_id)
                rules = (
                    db.query(AlertRule)
                    .filter(AlertRule.rule_key.isnot(None))
                    .filter(AlertRule.tenant_id == tenant_id)
                    .order_by(AlertRule.id.asc())
                    .all()
                )
            return [self._serialize_rule(rule) for rule in rules]
        finally:
            db.close()

    def _get_rules_cached(self, tenant_id: Optional[int]) -> List[Dict[str, Any]]:
        now = time_module.time()
        with self._rules_lock:
            cached = self._rules_cache.get(tenant_id)
            if cached and (now - cached[0]) < self._cache_ttl_sec:
                return list(cached[1])

            rules = self._get_rules_from_db(tenant_id)
            self._rules_cache[tenant_id] = (now, rules)
            return list(rules)

    def _invalidate_cache(self, tenant_id: Optional[int]) -> None:
        with self._rules_lock:
            self._rules_cache.pop(tenant_id, None)

    def _ensure_unknown_vehicle_defaults(self, db, rule: AlertRule) -> None:
        rule_key = str(rule.rule_key or rule.rule_type or "").strip().lower()
        if rule_key not in {"unknown_vehicle_detection", "unknown_vehicle"}:
            return
        existing = {cond.key: cond for cond in rule.conditions}
        defaults = {
            "plate_required": True,
            "plate_confidence_min": 0.7,
            "dedup_seconds": 30,
        }
        updated = False
        for key, value in defaults.items():
            if key in existing:
                continue
            db.add(AlertRuleCondition(rule_id=rule.id, key=key, value=value))
            updated = True
        if updated:
            db.flush()

    def update_rule(
        self,
        rule_id: str,
        payload: Dict[str, Any],
        *,
        tenant_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Invalid payload")
        target = str(rule_id or "").strip().lower()
        if not target:
            raise ValueError("Rule id is required")

        with self._rules_lock:
            db = next(get_db())
            try:
                query = db.query(AlertRule).filter(AlertRule.rule_key == target)
                if tenant_id is not None:
                    query = query.filter(AlertRule.tenant_id == tenant_id)
                rule = query.first()
                if rule is None and tenant_id is not None:
                    rule = (
                        db.query(AlertRule)
                        .filter(AlertRule.rule_key == target)
                        .filter(AlertRule.tenant_id.is_(None))
                        .first()
                    )
                if rule is None:
                    # Seed defaults and retry once if rules are missing
                    self._seed_defaults(db, tenant_id)
                    rule = (
                        db.query(AlertRule)
                        .filter(AlertRule.rule_key == target)
                        .filter(AlertRule.tenant_id == tenant_id)
                        .first()
                    )
                if rule is None:
                    raise KeyError("Rule not found")

                if "enabled" in payload:
                    rule.is_active = bool(payload.get("enabled"))

                if "action" in payload:
                    incoming_action = payload.get("action") or {}
                    if not isinstance(incoming_action, dict):
                        raise ValueError("action must be an object")
                    current_action = rule.action if isinstance(rule.action, dict) else {}
                    current_action.update(incoming_action)
                    rule.action = current_action

                if "conditions" in payload:
                    incoming_conditions = payload.get("conditions")
                    if incoming_conditions is None:
                        incoming_conditions = {}
                    if not isinstance(incoming_conditions, dict):
                        raise ValueError("conditions must be an object")
                    existing_conditions = {cond.key: cond for cond in rule.conditions}
                    for key, value in incoming_conditions.items():
                        if key == "event_type" and value:
                            rule.event_type = str(value)
                        if key in existing_conditions:
                            existing_conditions[key].value = value
                        else:
                            db.add(AlertRuleCondition(rule_id=rule.id, key=str(key), value=value))

                self._ensure_unknown_vehicle_defaults(db, rule)
                db.commit()
                db.refresh(rule)
                self._invalidate_cache(tenant_id)
                self._invalidate_cache(rule.tenant_id)
                return self._serialize_rule(rule)
            finally:
                db.close()

    def get_rules(self, *, tenant_id: Optional[int] = None) -> List[Dict[str, Any]]:
        return self._get_rules_cached(tenant_id)

    def is_enabled(self) -> bool:
        try:
            config = get_setup_config_service().get_config()
            project_type = str(config.get("project_type") or "business").strip().lower() or "business"
            operation_mode = _normalize_operation_mode(config.get("operation_mode"), project_type)
            return operation_mode == "enterprise"
        except Exception:
            return False

    def evaluate_event(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.is_enabled():
            return []
        tenant_id = event.get("tenant_id") if isinstance(event, dict) else None
        rules = self.get_rules(tenant_id=tenant_id)
        triggered = evaluate_rules(event, rules)
        if not triggered:
            return []

        # Apply deduplication per rule+plate if configured.
        plate_text = _event_plate_text(event)
        if not plate_text:
            return triggered

        now = time_module.time()
        deduped: List[Dict[str, Any]] = []
        with self._recent_lock:
            for rule in triggered:
                conditions = rule.get("conditions") or {}
                try:
                    dedup_seconds = float(conditions.get("dedup_seconds") or 0)
                except Exception:
                    dedup_seconds = 0.0
                if dedup_seconds <= 0:
                    deduped.append(rule)
                    continue

                rule_id = str(rule.get("id") or rule.get("type") or "rule")
                key = (rule_id, plate_text)
                last_seen = self._recent_hits.get(key)
                if last_seen is not None and (now - last_seen) < dedup_seconds:
                    continue

                self._recent_hits[key] = now
                deduped.append(rule)

        return deduped


_rule_engine_service: Optional[RuleEngineService] = None


def get_rule_engine_service() -> RuleEngineService:
    global _rule_engine_service
    if _rule_engine_service is None:
        _rule_engine_service = RuleEngineService()
    return _rule_engine_service
