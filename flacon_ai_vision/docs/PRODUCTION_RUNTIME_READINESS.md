# Production Runtime Readiness

This phase is no longer about structural fixes. The goal is operational:

- reliability
- observability
- real scaling validation

## Main entrypoint

Run the phase 4 readiness gate:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\phase4_production_readiness.ps1 -RequireFrontend
```

The script writes a JSON report in `logs/phase4_production_readiness_*.json`.

## What phase 4 checks

- backend live probe: `GET /api/health/live`
- backend ready probe: `GET /api/health/ready`
- auth login
- GPU runtime readiness via `scripts/verify_gpu_stack.py`
- API smoke checks via `scripts/smoke_api.py`
- live module verification via `scripts/verify_live_modules.ps1`
- system health snapshot: `GET /api/system/health/full`
- realtime manager health: `GET /api/realtime/health`
- scaling monitor dashboard: `GET /api/scaling-monitor/dashboard`

## Recommended production gate

Minimal pass criteria:

- `backend_ready` = `OK`
- `auth_login` = `OK`
- `api_smoke` = `OK`
- `system_health_full` != `down`
- `realtime_health` = `OK`
- `scaling_monitor_dashboard` = `OK` or `WARN` if no runtime report exists yet

GPU rule:

- use `-RequireGpu` only on hosts that are expected to run GPU inference
- on CPU-only environments, `gpu_stack` can be `WARN` without blocking the whole gate

## Operational tuning targets

The distributed runtime now exposes `snapshot()["runtime_tuning"]`.

Track these values:

- `effective_inference_batch_size`
- `inference_local_queue_maxsize`
- `effective_inference_ownership_heartbeat_interval_sec`
- `effective_inference_ownership_lease_ttl_sec`

Use them with:

- `GET /api/scaling-monitor/dashboard`
- runtime report JSON files in `logs/`
- `scripts/run_scaling_runtime_distributed.py`

## Scaling guidance

Start simple:

1. keep sticky inference enabled
2. increase `inference_partition_count` before increasing per-worker batch aggressively
3. only increase `inference_batch_size` if GPU is saturated and queue depth stays stable
4. adjust lease TTL only after observing heartbeat jitter and restart timing in real runs

Rules of thumb:

- high queue depth + low GPU usage: increase partitions or reduce sticky imbalance
- high GPU usage + acceptable latency: increase batch slightly
- repeated standby/ownership churn: increase heartbeat/TTL margin
- high memory on inference nodes: reduce local queue maxsize or worker count

## E2E sequence before production rollout

1. Run phase 4 readiness.
2. Run a distributed scaling smoke with representative camera count.
3. Verify `logs/*_live.json` and `logs/*report*.json`.
4. Open Grafana/Prometheus stack if deployed.
5. Confirm frontend reconnect and multi-cam monitor behavior against the live backend.

## Windows note

`PermissionError` on `pytest tmp_path` cleanup in this workstation does not indicate a backend/runtime bug.

For Windows local validation:

- prefer targeted `pytest` without `tmp_path` when possible
- use direct smoke execution for SQLite/runtime failover scenarios
- rely on the JSON reports produced by phase 4 and scaling scripts
