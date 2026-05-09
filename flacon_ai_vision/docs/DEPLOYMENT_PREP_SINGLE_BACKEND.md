# Falcon AI Vision - Deployment Prep (Single Backend)

This project keeps a **single backend** and a **modular frontend**.
The goal is to deploy module by module without splitting services too early.

## Runtime Topology

- Backend API: `127.0.0.1:5003`
- Frontend UI: `localhost:3000`
- PostgreSQL/pgvector: `127.0.0.1:5433`

## 1) Preconditions on target PC

- Python 3.11 available
- Node.js + npm available
- PostgreSQL running on `5433`
- Database URL configured in `.env`:
  - `DATABASE_URL=postgresql+psycopg://...@127.0.0.1:5433/...`

## 2) Start order (no Docker)

1. Start PostgreSQL/pgvector
2. Start backend on `5003`
3. Start frontend on `3000`
4. Run live smoke check:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\verify_live_modules.ps1 -RequireFrontend`
5. Run production readiness gate:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\phase4_production_readiness.ps1 -RequireFrontend`

## 3) Module verification checklist

- Face module
  - API route exists: `/api/face/recognize`
  - UI route works: `/facial-recognition`
- Vehicle module
  - API route exists: `/api/vehicle/recognize/camera/{camera_id}`
  - UI route works: `/vehicle-detection` (alias to `/vehicles`)
- Security module
  - API route exists: `/api/system/health/full`
  - UI route works: `/security` (alias to `/security-center`)
- Admin module
  - API route exists: `/api/admin/health`
  - UI route works: `/admin`
- Reporting module
  - API route exists: `/api/reporting/health`
  - UI route works: `/reporting`

## 4) CI/quality gates

- Backend tests:
  - `venv_ai\Scripts\python.exe -m pytest vms/backend/tests -p no:cacheprovider -q`
- Frontend type-check:
  - `npm run type-check` (from `vms/frontend`)
- Module structure contract:
  - `venv_ai\Scripts\python.exe scripts\verify_modules_structure.py`

## 5) Why this structure scales

- Single backend keeps operations simple for production rollout.
- Module contracts keep boundaries clear (`face`, `vehicle`, `zone`, `security`, `admin`, `reporting`).
- Frontend wrappers allow extending one module without touching all pages.

## 6) Next operational phase

- Use [PRODUCTION_RUNTIME_READINESS.md](./PRODUCTION_RUNTIME_READINESS.md) for readiness, observability and scaling validation.
