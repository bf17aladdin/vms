from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from fastapi import APIRouter, Depends, Query

from vms.backend.core.security import get_current_user

router = APIRouter(prefix="/api/scaling-monitor", tags=["scaling-monitor"])

_SCALING_PHASES = {
    "scaling_runtime_distributed",
    "scaling_runtime_simulation",
    "scaling_runtime_replay",
    "scaling_runtime_webcam_fanout",
}


def _logs_dir() -> Path:
    # .../falcon-ai-vision/logs
    return Path(__file__).resolve().parents[3] / "logs"


def _safe_json_load(path: Path) -> Optional[dict[str, Any]]:
    try:
        if not path.exists() or not path.is_file():
            return None
        # Defensive cap to avoid reading unexpectedly huge files.
        if path.stat().st_size > 20 * 1024 * 1024:
            return None
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _iter_scaling_reports(*, max_files: int = 300) -> Iterator[tuple[Path, dict[str, Any]]]:
    logs = _logs_dir()
    if not logs.exists():
        return iter(())

    candidates = sorted(
        logs.glob("*.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )[: max(1, int(max_files))]

    for path in candidates:
        lname = path.name.lower()
        if lname.endswith("_live.json") or lname.endswith("_checkpoints.json"):
            continue
        payload = _safe_json_load(path)
        if not payload:
            continue
        if str(payload.get("phase", "")).strip().lower() not in _SCALING_PHASES:
            continue
        yield path, payload


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _extract_summary(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    final_live = payload.get("final_live_status", {}) or {}
    throughput = final_live.get("throughput", {}) or {}
    inference = final_live.get("inference", {}) or {}
    drops = final_live.get("drops", {}) or {}
    resources = final_live.get("resources", {}) or {}
    ingestion = final_live.get("ingestion", {}) or {}
    resilience = final_live.get("resilience", {}) or {}
    health_counts = ingestion.get("cam_health_counts", {}) or {}

    post_run = payload.get("post_run_summary", {}) or {}
    post_metrics = post_run.get("metrics", {}) or {}
    alerts = post_run.get("alerts", [])

    return {
        "run_id": path.stem,
        "file_name": path.name,
        "phase": payload.get("phase"),
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "started_at": payload.get("started_at"),
        "ended_at": payload.get("ended_at"),
        "duration_sec": _to_int(payload.get("duration_sec")),
        "verdict": (payload.get("evaluation", {}) or {}).get("verdict"),
        "status": post_run.get("status"),
        "alerts_count": len(alerts) if isinstance(alerts, list) else 0,
        "checkpoint_count": len(payload.get("checkpoints", []) or []),
        "p95_end_to_end_ms": _to_float(
            inference.get("p95_end_to_end_ms", post_metrics.get("p95_end_to_end_ms"))
        ),
        "infer_latency_avg_ms": _to_float(
            inference.get("infer_latency_avg_ms", post_metrics.get("infer_latency_avg_ms"))
        ),
        "queue_depth_current": _to_int(
            inference.get("queue_depth_current", post_metrics.get("queue_depth_current"))
        ),
        "queue_depth_high_watermark": _to_int(
            inference.get(
                "queue_depth_high_watermark",
                post_metrics.get("queue_depth_high_watermark"),
            )
        ),
        "persist_success_pct": _to_float(
            throughput.get("persist_success_pct", post_metrics.get("persist_success_pct"))
        ),
        "frames_processed_total": _to_int(throughput.get("frames_processed_total")),
        "events_persisted_total": _to_int(throughput.get("events_persisted_total")),
        "dropped_frames_total": _to_int(
            drops.get("dropped_frames_total", post_metrics.get("dropped_frames_total"))
        ),
        "dropped_events_total": _to_int(
            drops.get("dropped_events_total", post_metrics.get("dropped_events_total"))
        ),
        "cpu_percent": _to_float(resources.get("cpu_percent", post_metrics.get("cpu_percent"))),
        "ram_mb_start": _to_float(resources.get("ram_mb_start", post_metrics.get("ram_mb_start"))),
        "ram_mb_current": _to_float(resources.get("ram_mb_current", post_metrics.get("ram_mb_current"))),
        "cam_up": _to_int(health_counts.get("up")),
        "cam_degraded": _to_int(health_counts.get("degraded")),
        "cam_down": _to_int(health_counts.get("down")),
        "reconnect_attempts_total": _to_int(ingestion.get("reconnect_attempts_total")),
        "decode_errors_total": _to_int(ingestion.get("decode_errors_total")),
        "dead_letters_total": _to_int((final_live.get("dead_letters", {}) or {}).get("dead_letters_total")),
        "resilience_restarts_total": _to_int(resilience.get("restarts_total")),
        "resilience_incidents_total": _to_int(resilience.get("incidents_total")),
    }


def _infer_live_path_for_report(report_path: Path) -> Path:
    stem = report_path.stem
    if stem.endswith("_report"):
        return report_path.with_name(f"{stem[:-7]}_live{report_path.suffix}")
    return report_path.with_name(f"{stem}_live{report_path.suffix}")


def _latest_live_status() -> Optional[dict[str, Any]]:
    logs = _logs_dir()
    if not logs.exists():
        return None
    live_files = sorted(
        logs.glob("*_live.json"),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    for path in live_files:
        payload = _safe_json_load(path)
        if not payload:
            continue
        if "throughput" in payload and "inference" in payload:
            return payload
    return None


@router.get("/dashboard")
def scaling_monitor_dashboard(
    limit: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
):
    runs: list[dict[str, Any]] = []
    latest_report_payload: Optional[dict[str, Any]] = None
    latest_report_file: Optional[Path] = None
    latest_summary: Optional[dict[str, Any]] = None

    for idx, (path, payload) in enumerate(_iter_scaling_reports()):
        summary = _extract_summary(path, payload)
        if idx == 0:
            latest_report_payload = payload
            latest_report_file = path
            latest_summary = summary
        if len(runs) < int(limit):
            runs.append(summary)
        else:
            break

    latest_report_obj: Optional[dict[str, Any]] = None
    latest_live = _latest_live_status()

    if latest_report_payload is not None and latest_report_file is not None and latest_summary is not None:
        inferred_live_path = _infer_live_path_for_report(latest_report_file)
        inferred_live_payload = _safe_json_load(inferred_live_path)
        if inferred_live_payload and "throughput" in inferred_live_payload and "inference" in inferred_live_payload:
            latest_live = inferred_live_payload

        checkpoints = latest_report_payload.get("checkpoints", []) or []
        latest_report_obj = {
            "summary": latest_summary,
            "post_run_summary": latest_report_payload.get("post_run_summary"),
            "checkpoint_schedule_min": latest_report_payload.get("checkpoint_schedule_min", []),
            "checkpoints": checkpoints[-3:] if isinstance(checkpoints, list) else [],
            "source": {
                "report_file": latest_report_file.name,
                "live_file": inferred_live_path.name if inferred_live_path.exists() else None,
            },
        }

    return {
        "success": True,
        "latest_report": latest_report_obj,
        "latest_live_status": latest_live,
        "history": runs,
        "logs_dir": str(_logs_dir()),
    }
