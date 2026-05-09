# Falcon AI Vision - Product Action Plan

## Goal

Transform the current project into a sellable SaaS security platform:

- VMS + AI detection
- human and vehicle access control
- incident operations
- auditability
- mobile response workflow

Target product statement:

> An intelligent platform that controls, analyzes, and secures human and vehicle access in real time.

## Repo Reality Today

The codebase already contains several strong building blocks. The fastest path is to harden and unify them, not rebuild them.

### What already exists

- Web personnel management:
  - `falcon_ai_vision-platform/frontend/src/pages/PersonnelPage.tsx`
  - `falcon_ai_vision-platform/backend/vms/backend/routers/personnel.py`
- Web vehicle registry:
  - `falcon_ai_vision-platform/frontend/src/pages/VehicleRegistryPage.tsx`
  - `falcon_ai_vision-platform/backend/vms/backend/routers/vehicles.py`
  - `falcon_ai_vision-platform/backend/vms/backend/routers/vehicle_registry.py`
- Unknown detections review flow:
  - `falcon_ai_vision-platform/frontend/src/pages/UnknownDetectionsPage.tsx`
  - `falcon_ai_vision-platform/backend/vms/backend/routers/unknown_detections.py`
- Alerts and realtime notifications:
  - `falcon_ai_vision-platform/backend/vms/backend/services/alert_service.py`
  - `falcon_ai_vision-platform/backend/vms/backend/routers/ws.py`
- Audit foundations:
  - `falcon_ai_vision-platform/backend/vms/backend/core/audit.py`
  - admin audit UI in `falcon_ai_vision-platform/frontend/src/components/AdminPanel.tsx`
- Vehicle access and security logic:
  - `falcon_ai_vision-platform/backend/vms/backend/routers/vehicle_recognition.py`
  - `falcon_ai_vision-platform/backend/vms/backend/services/vehicle_ai/`
- Recording capability:
  - `falcon_ai_vision-platform/backend/vms/backend/services/video_recorder.py`

### What is still missing to make it sellable

- one unified decision engine across face, vehicle, zone, and unknown flows
- a real incident workflow with owner, comments, SLA, and resolution states
- audit exposed as a first-class product surface, not only an admin detail
- secured short-lived media access for streams and clips
- clear SaaS limits, trial logic, and billing-ready entitlements
- a mobile client built on top of stabilized incident and notification APIs

## Product Priorities

### 1. Intelligent Directory (Critical)

Objective:
Turn personnel and vehicle data into the trusted reference used by the AI system.

Current state:

- Personnel CRUD already exists.
- Vehicle registry CRUD already exists.
- Unknown detections already exist.

Main gap:

- the product still feels split across separate pages and schemas
- the AI references exist, but business rules are not yet unified around them

Actions:

- keep existing APIs and stabilize their contracts instead of introducing parallel `/persons` and `/vehicles` stacks
- normalize the canonical fields used by decision logic
- add one business entry point in the web UI named `Annuaire` that groups:
  - Personnel
  - Vehicles
  - Unknown detections
- define explicit authorization metadata on both humans and vehicles:
  - authorized zones
  - schedule windows
  - allowed gates
  - active/inactive
  - blacklist/flag state

Definition of done:

- operators can find a person, vehicle, or unknown item from one place
- each detection can resolve to a canonical entity
- decision logic can query one stable source of truth

Relevant code:

- `falcon_ai_vision-platform/frontend/src/pages/PersonnelPage.tsx`
- `falcon_ai_vision-platform/frontend/src/pages/VehicleRegistryPage.tsx`
- `falcon_ai_vision-platform/frontend/src/pages/UnknownDetectionsPage.tsx`
- `falcon_ai_vision-platform/backend/vms/backend/routers/personnel.py`
- `falcon_ai_vision-platform/backend/vms/backend/routers/vehicles.py`
- `falcon_ai_vision-platform/backend/vms/backend/routers/unknown_detections.py`

### 2. AI to Decision Engine (Very Important)

Objective:
Make the platform active, not passive.

Decision cases:

- recognized face -> verify access policy
- detected plate -> verify authorization policy
- unknown person or vehicle -> create alert or incident automatically

Actions:

- create one policy evaluation service that takes:
  - entity type
  - match confidence
  - site or zone
  - time window
  - security profile
- return a single result shape:
  - `allow`
  - `deny`
  - `review`
  - `unknown`
- attach the result to alerts, access logs, incidents, and audit rows
- unify face and vehicle outputs under the same operator language

Definition of done:

- every detection produces a business decision
- the UI shows not only "detected", but also "why allowed/denied/review"

Suggested implementation area:

- new service under `falcon_ai_vision-platform/backend/vms/backend/services/`
- integrate with:
  - `routers/personnel.py`
  - `routers/vehicle_recognition.py`
  - `routers/vehicle_registry.py`
  - `routers/unknown_detections.py`

### 3. Incident Workflow

Objective:
Convert alerts into operational work.

Status model:

- `NEW`
- `ACK`
- `IN_PROGRESS`
- `RESOLVED`

Actions:

- create persistent incident records linked to alerts, detections, personnel, vehicles, clips, and cameras
- add fields for:
  - assignee
  - comments
  - timestamps per status
  - severity
  - source type
  - SLA metadata
- update the web UI so operators can acknowledge, assign, comment, and resolve

Definition of done:

- an alert can become an incident without manual copy/paste
- supervisors can see who owns what and what is still open

Likely affected areas:

- `falcon_ai_vision-platform/frontend/src/pages/AlertsPage.tsx`
- `falcon_ai_vision-platform/frontend/src/pages/EventsPage.tsx`
- backend alert models and routers

### 4. Audit Log as a Product Feature (Mandatory)

Objective:
Create trust for enterprise buyers.

Current state:

- audit foundations exist in the backend
- audit is partially visible in admin tooling

Actions:

- expose a dedicated audit page in the product navigation
- support filters for:
  - user
  - action
  - entity
  - time range
  - outcome
- include business events:
  - access allowed or denied
  - incident assignment and resolution
  - policy changes
  - stream access issuance

Definition of done:

- compliance teams can answer "who did what, when, and why" without backend access

Relevant code:

- `falcon_ai_vision-platform/backend/vms/backend/core/audit.py`
- `falcon_ai_vision-platform/frontend/src/components/AdminPanel.tsx`

### 5. Stream Security

Objective:
Protect stream and media URLs from uncontrolled sharing.

Actions:

- issue short-lived signed JWT or HMAC tokens for media access
- avoid permanent raw URLs in the client
- secure live stream, snapshots, and recorded clips with the same pattern

Definition of done:

- copied URLs expire quickly
- media access is attributable and revocable

### 6. Automatic Recording on Critical Events

Objective:
Generate proof automatically.

Actions:

- on critical decision or incident creation:
  - record pre/post event window when possible
  - store clip metadata
  - link clip to incident
- expose clip preview in alerts and incident workflow

Definition of done:

- operators can review evidence from the incident itself

Relevant code:

- `falcon_ai_vision-platform/backend/vms/backend/services/video_recorder.py`

### 7. SaaS Monetization

Objective:
Move from demo software to billable product.

Actions:

- define plans:
  - Starter
  - Pro
  - Enterprise
- enforce entitlements:
  - number of cameras
  - retention days
  - AI modules
  - operators
  - mobile notifications
- add 7-day or 14-day trial support

Definition of done:

- one tenant can be limited, upgraded, and trialed without code changes

### 8. Mobile App + WhatsApp

Objective:
Drive field adoption and faster reaction time.

Important framing:

The mobile app should be an operational companion, not a full admin clone of the web platform.

Mobile MVP:

- login and session refresh
- incident feed
- push notification on critical alerts
- acknowledge / assign / comment
- quick lookup for personnel and vehicles
- secure clip or snapshot viewing
- optional WhatsApp escalation for critical incidents

Dependencies:

- incident workflow must exist first
- stream security must exist first
- notification events must be stable first

Recommended stack:

- React Native + Expo

Why:

- the existing product already uses TypeScript in the SPA
- team reuse is higher across API types, validation, and UI logic

### 9. Business Dashboard

Objective:
Speak to decision-makers, not only operators.

Business KPIs to add:

- incidents per day
- mean acknowledgment time
- mean resolution time
- access denied count
- unknown detection rate
- site presence summary
- vehicle compliance rate

Definition of done:

- a buyer can understand operational ROI in less than 2 minutes

## Four-Week Roadmap

### Week 1

- stabilize the directory data model
- unify navigation around Personnel, Vehicles, Unknown detections
- define canonical business fields for access decisions

### Week 2

- implement unified decision engine
- create incident model and first workflow states
- connect alerts to incidents automatically

### Week 3

- ship first-class audit page
- add signed media access
- connect critical incidents to clip recording

### Week 4

- add SaaS entitlements and trial logic
- expose business KPIs
- freeze mobile API contract
- start mobile MVP scaffold

## First Tasks for Tomorrow Morning

1. Freeze the canonical entity model for personnel and vehicles.
2. Add a single business navigation entry for `Annuaire`.
3. Define the decision engine contract before writing more detection-specific code.
4. Introduce an `Incident` model instead of treating alerts as the final object.
5. Protect media URLs before shipping mobile or external demos.

## What Not to Do Next

- do not add more AI models before the business layer is unified
- do not split CRUD into new duplicate APIs when working ones already exist
- do not grow the UI surface faster than the operational workflow
- do not ship mobile before incidents and secured media are stable
