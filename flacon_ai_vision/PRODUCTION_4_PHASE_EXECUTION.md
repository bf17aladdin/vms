# Production 4-Phase Execution (Falcon AI Vision)

This runbook executes the exact order requested for production readiness.

## Scope (No Docker)
- Docker is intentionally out of scope for this stage.
- Runtime target:
  - backend: `127.0.0.1:5003`
  - frontend: `localhost:3000`
  - PostgreSQL/pgvector: local service on `127.0.0.1:5433`

## Step 0 - Local PostgreSQL + pgvector check
- Script: `scripts/start_postgres_pgvector_local.ps1`
- Command:
```powershell
.\scripts\start_postgres_pgvector_local.ps1 -EnsurePgvector -RunMigrations
```
- Output:
  - validates local PostgreSQL reachability
  - optionally runs `CREATE EXTENSION IF NOT EXISTS vector`
  - runs migration/backfill checks for embeddings

## Phase 1 - Calibration Terrain
- Goal: validate secure access decisions using real field scenarios.
- Script: `scripts/phase1_vehicle_calibration.ps1`
- Command:
```powershell
.\scripts\phase1_vehicle_calibration.ps1 -ApiBase "http://127.0.0.1:5003"
```
- Required images:
  - `data/tests/plate_clean_day.jpg`
  - `data/tests/plate_dirty.jpg`
  - `data/tests/plate_diff_same_car.jpg`
  - `data/tests/good_plate_wrong_car.jpg`
- Output report: `logs/phase1_calibration_report_*.json`

## Phase 2 - Hardening Securite
- Goal: verify auth boundaries, role enforcement, refresh flow, login rate limit.
- Script: `scripts/phase2_backend_hardening_audit.ps1`
- Command:
```powershell
.\scripts\phase2_backend_hardening_audit.ps1 -ApiBase "http://127.0.0.1:5003"
```
- Output report: `logs/phase2_hardening_audit_*.json`

## Phase 3 - Performance & Scalabilite
- Goal: baseline endpoint latency and success rates under repeated load.
- Script: `scripts/phase3_perf_scalability_benchmark.ps1`
- Command:
```powershell
.\scripts\phase3_perf_scalability_benchmark.ps1 -ApiBase "http://127.0.0.1:5003" -Iterations 25
```
- Output report: `logs/phase3_perf_report_*.json`

## Phase 4 - Dashboard Temps Reel Securite
- Frontend page added: `/security-realtime`
- Data sources:
  - `GET /api/system/health/full`
  - `GET /api/vehicle/access/alerts`
  - `GET /api/vehicle/access/logs`
- Capabilities:
  - health status card
  - open alert counters (critical/high)
  - denied/review counters
  - auto-refresh and manual refresh
  - raw health snapshot

## Recommended acceptance gates
- Phase 1: >= 3/4 scenario targets pass on real camera samples.
- Phase 2: all hardening checks pass (`pass=true`).
- Phase 3: p95 stable and no repeated 5xx under benchmark.
- Phase 4: dashboard refreshes every 3-10s without UI errors.
