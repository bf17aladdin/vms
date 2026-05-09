# Feature Flag Map (Operation Mode + Project Type)

Source of truth:
- `falcon_ai_vision/backend/vms/backend/services/features_service.py`
- `falcon_ai_vision/frontend/src/hooks/useFeatures.ts`

## Global Behavior Flags
| Flag | Condition |
| --- | --- |
| `rules_engine` | `operation_mode == "enterprise"` |
| `simple_notifications` | `operation_mode != "enterprise"` |
| `advanced_notifications` | `operation_mode == "enterprise"` |

## Core UI Flags (Enterprise-only)
| Flag | Condition |
| --- | --- |
| `ui_facial_recognition` | `operation_mode == "enterprise"` |
| `ui_zones` | `operation_mode == "enterprise"` |
| `ui_personnel` | `operation_mode == "enterprise"` |
| `ui_personnel_entry_exit` | `operation_mode == "enterprise"` |
| `ui_personnel_history` | `operation_mode == "enterprise"` |
| `ui_vehicles` | `operation_mode == "enterprise"` |
| `ui_vehicle_entry_exit` | `operation_mode == "enterprise"` |
| `ui_vehicle_registry` | `operation_mode == "enterprise"` |
| `ui_map` | `operation_mode == "enterprise"` |
| `ui_reporting` | `operation_mode == "enterprise"` |
| `ui_users` | `operation_mode == "enterprise"` |

## SOC-only UI Flags
| Flag | Condition |
| --- | --- |
| `ui_security_center` | `project_type == "soc"` |
| `ui_security_config` | `project_type == "soc"` |
| `ui_security_realtime` | `project_type == "soc"` |
| `ui_vehicle_multicam` | `project_type == "soc"` |
| `ui_unknown_detections` | `project_type == "soc"` |
| `ui_ai_monitoring` | `project_type == "soc"` |
| `ui_admin` | `project_type == "soc"` |

## Categories (Driven by Setup Config)
`categories` are derived from `detection_types` in setup config.
| Category | Condition |
| --- | --- |
| `categories.person` | `detection_types` contains `person` |
| `categories.vehicle` | `detection_types` contains `vehicle` |

## Rule Flags
| Rule | Condition |
| --- | --- |
| `rules.engine_enabled` | `operation_mode == "enterprise"` |
| `rules.visitor_zone` | `operation_mode == "enterprise"` |
| `rules.off_hours_presence` | `operation_mode == "enterprise"` |
| `rules.unknown_vehicle` | `operation_mode == "enterprise"` |

## Alert Flags
| Flag | Condition |
| --- | --- |
| `alerts.simple` | `operation_mode != "enterprise"` |
| `alerts.advanced` | `operation_mode == "enterprise"` |

## Notes
- Backend payload is authoritative. Frontend `useFeatures` provides a fallback when `/api/features` is unreachable.
- `operation_mode` and `project_type` are included in the payload for mode-aware UI filtering.
