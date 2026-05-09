# Tech Debt Sweep (Setup, Modes, Features)

This is a focused, code-backed list of gaps found while reviewing the setup flow, feature flags, and routing.

## P0 (Blocking or High-Risk)
| Priority | Issue | Impact | Recommendation | Files |
| --- | --- | --- | --- | --- |
| P0 | Dual setup systems (`/api/setup/status` uses DB, `/api/setup/config` uses JSON file) | Users can be stuck in setup or see stale mode config | Pick one source of truth, unify status + config endpoints | `backend/vms/backend/routers/setup.py`, `backend/vms/backend/routers/setup_config.py`, `backend/vms/backend/services/setup_config_service.py`, `frontend/src/App.tsx` |
| P0 | `/api/setup/mode` expects query `mode`, frontend sends JSON body `application_mode` | Mode select can fail silently | Align request contract (accept JSON body or send query) | `backend/vms/backend/routers/setup.py`, `frontend/src/services/api.ts` |
| P0 | `/api/setup/country` expects query params, frontend sends JSON body with `timezone` and `license_plate_format` | Country, timezone, plate format not persisted | Accept JSON body and persist fields, or change client | `backend/vms/backend/routers/setup.py`, `frontend/src/services/api.ts` |

## P1 (Medium Risk)
| Priority | Issue | Impact | Recommendation | Files |
| --- | --- | --- | --- | --- |
| P1 | `App.tsx` expects `configured` from `/api/setup/status`, but response does not include it | Configured state can be wrong even after setup | Return `configured` or switch UI to `/api/setup/config` | `frontend/src/App.tsx`, `backend/vms/backend/routers/setup.py` |
| P1 | Setup wizard sends fields not in `SetupConfigPayload` (`application_mode`, `country_code`, `timezone`, `license_plate_format`) | Payload mismatch and data loss | Extend payload schema or move these to proper endpoints | `frontend/src/pages/setup/SetupWizardPage.tsx`, `backend/vms/backend/routers/setup_config.py` |
| P1 | SOC mode not selectable in setup UI | SOC features require manual config | Add SOC option in wizard or admin config | `frontend/src/pages/setup/SetupWizardPage.tsx`, `backend/vms/backend/services/setup_config_service.py` |
| P1 | `useFeatures` fallback can drift from backend if localStorage stale | UI flags may not match backend enforcement | Add TTL or always trust backend when reachable | `frontend/src/hooks/useFeatures.ts` |

## P2 (Low Risk / Maintainability)
| Priority | Issue | Impact | Recommendation | Files |
| --- | --- | --- | --- | --- |
| P2 | Preset defaults duplicated in frontend and backend | Drift risk over time | Use backend presets only, keep frontend fallback minimal | `frontend/src/pages/setup/SetupWizardPage.tsx`, `backend/vms/backend/services/setup_config_service.py` |
| P2 | Three mode vocabularies (`operation_mode`, `project_type`, `application_mode`) | Confusing mapping logic | Introduce a single mapping helper and document it | `backend/vms/backend/services/setup_config_service.py`, `frontend/src/hooks/useProjectConfig.ts` |
| P2 | Setup completion not centralized (no single "finish" flow) | Hard to reason about setup completion | Consolidate into one endpoint that sets config and completion | `backend/vms/backend/routers/setup.py`, `backend/vms/backend/routers/setup_config.py` |

## Suggested Fix Order
1. Align setup endpoints and payloads (P0).
2. Make configured state authoritative and consistent (P1).
3. Reduce duplication of presets and mapping logic (P2).
