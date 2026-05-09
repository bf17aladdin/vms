# Production Validation Checklist (Setup, Modes, Features, Alerts)

## Scope
Validate the onboarding-driven setup flow, mode selection, feature flags, dashboard routing, and alert lifecycle.

## Preconditions
- Backend running with DB migrations applied.
- Frontend running with authentication enabled.
- At least one test user exists with valid token.

## Setup Flow (API + UI)
- [ ] `GET /api/setup/status` returns `setup_completed`, `application_mode`, `country_code`, `timezone`, `has_setup_config`, `entity_counts`, `next_steps`.
- [ ] `GET /api/setup/presets` returns presets for `maison`, `magasin`, `entreprise`, `parking`, `securite_avancee`.
- [ ] `POST /api/setup/mode` updates user `application_mode` to `home` or `company`.
- [ ] `POST /api/setup/country` stores `country_code` and creates `setup_config` row.
- [ ] `POST /api/setup/config` stores setup config and returns `configured=true`.
- [ ] `POST /api/setup/complete` flips `setup_completed=true`.
- [ ] UI wizard writes `eof_setup_config` localStorage and triggers `eof-setup-updated` event.
- [ ] App redirects to `/dashboard` when configured.

## Mode Selection (Mapping)
- [ ] FAMILY mode maps to `operation_mode=family`, `project_type=home`, `application_mode=home`.
- [ ] ENTERPRISE mode maps to `operation_mode=enterprise`, `project_type=business`, `application_mode=company`.
- [ ] SOC mode (usage `securite_avancee`) maps to `project_type=soc`, `operation_mode=enterprise`.
- [ ] `useProjectConfig` reflects mode changes after `eof-setup-updated`.

## Feature Flags (Backend + Frontend)
- [ ] `GET /api/features` returns `operation_mode`, `project_type`, `flags`, `categories`, `rules`, `alerts`.
- [ ] `flags.rules_engine` is true only for enterprise.
- [ ] SOC-only UI flags are true only for project type `soc`.
- [ ] `categories.person` and `categories.vehicle` match `detection_types` from setup config.
- [ ] Frontend `useFeatures` merges backend payload with fallback flags.

## Dashboard Routing (ProjectGuard)
- [ ] `home` users can access `/dashboard`, `/cameras`, `/stream`, `/settings`.
- [ ] `business` users can access `/vehicles`, `/vehicle-entry-exit`, `/personnel`.
- [ ] `soc` users can access `/security-center`, `/security-realtime`, `/vehicle-multicam`, `/unknown-detections`.
- [ ] Unauthorized routes redirect to `/dashboard`.

## Alert Lifecycle
- [ ] Alert created via rule engine is stored in DB.
- [ ] `GET /api/alerts` returns active alerts.
- [ ] `POST /api/alerts/{id}/acknowledge` sets `acknowledged=true` and updates DB.
- [ ] `POST /api/alerts/cleanup` removes old acknowledged alerts by retention policy.
- [ ] WebSocket `new_alert` event updates badge and list without refresh.

## Runtime Sanity
- [ ] WS connected state shows "Live" and fallback shows "Fallback".
- [ ] Polling stops when WS connected and resumes if WS disconnected.
