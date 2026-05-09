from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from vms.backend.services.scaling.distributed_pipeline import (
    DistributedPipelineConfig,
    DistributedPipelineNode,
)
from vms.backend.services.scaling.scaling_runtime import RuntimeThresholds

try:
    import psutil  # type: ignore

    _HAS_PSUTIL = True
except Exception:
    psutil = None
    _HAS_PSUTIL = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run distributed scaling node with role-based execution "
            "(ingestion / inference / writer / full)."
        ),
    )
    parser.add_argument("--role", choices=["ingestion", "inference", "writer", "full"], default="full")
    parser.add_argument("--duration-sec", type=int, default=120)
    parser.add_argument("--progress-interval-sec", type=int, default=5)

    parser.add_argument("--queue-backend", choices=["memory", "sqlite"], default="sqlite")
    parser.add_argument("--queue-sqlite-path", type=str, default="data/scaling_runtime_queue.db")
    parser.add_argument("--queue-namespace", type=str, default="distributed")
    parser.add_argument("--queue-purge-on-start", action="store_true")
    parser.add_argument("--frame-queue-maxsize", type=int, default=4096)
    parser.add_argument("--result-queue-maxsize", type=int, default=4096)

    parser.add_argument("--camera-count", type=int, default=20)
    parser.add_argument("--sample-interval-ms", type=int, default=200)

    parser.add_argument("--inference-mode", choices=["simulated", "real"], default="simulated")
    parser.add_argument("--inference-workers", type=int, default=8)
    parser.add_argument("--inference-batch-size", type=int, default=4)
    parser.add_argument("--inference-batch-max-wait-ms", type=float, default=0.0)

    parser.add_argument("--writer-workers", type=int, default=6)
    parser.add_argument("--persist-target", choices=["memory", "db"], default="memory")
    parser.add_argument("--dead-letter-backend", choices=["none", "memory", "sqlite"], default="none")
    parser.add_argument("--dead-letter-sqlite-path", type=str, default="data/scaling_dead_letters.db")
    parser.add_argument("--dead-letter-namespace", type=str, default="")

    parser.add_argument("--frame-read-ms-min", type=float, default=2.0)
    parser.add_argument("--frame-read-ms-max", type=float, default=8.0)
    parser.add_argument("--inference-ms-min", type=float, default=40.0)
    parser.add_argument("--inference-ms-max", type=float, default=120.0)
    parser.add_argument("--inference-success-ratio", type=float, default=1.0)
    parser.add_argument("--persist-ms-min", type=float, default=3.0)
    parser.add_argument("--persist-ms-max", type=float, default=18.0)
    parser.add_argument("--persist-success-ratio", type=float, default=1.0)

    parser.add_argument("--p95-threshold-ms", type=float, default=3000.0)
    parser.add_argument("--queue-depth-threshold", type=int, default=1200)
    parser.add_argument("--queue-overflow-threshold", type=int, default=0)
    parser.add_argument("--persist-success-threshold-pct", type=float, default=99.0)
    parser.add_argument("--output-json", type=str, default="")
    parser.add_argument("--live-status-json", type=str, default="")
    parser.add_argument(
        "--checkpoint-minutes",
        type=str,
        default="15,30,60",
        help="Comma-separated checkpoint minutes to capture (example: 15,30,60).",
    )
    parser.add_argument(
        "--checkpoint-json",
        type=str,
        default="",
        help="Optional path to write checkpoint snapshots continuously.",
    )
    parser.add_argument(
        "--quiet-checkpoints",
        action="store_true",
        help="Disable checkpoint lines in stdout.",
    )
    parser.add_argument(
        "--disable-resilience-supervisor",
        action="store_true",
        help="Disable self-healing supervisor for ingestion/inference/writer workers.",
    )
    parser.add_argument(
        "--resilience-supervisor-interval-sec",
        type=float,
        default=2.0,
        help="Supervisor polling interval in seconds.",
    )
    parser.add_argument(
        "--resilience-restart-cooldown-sec",
        type=float,
        default=1.0,
        help="Minimum cooldown between automatic restarts of the same component.",
    )
    parser.add_argument(
        "--resilience-max-restarts-per-component",
        type=int,
        default=100,
        help="Safety cap for automatic restarts per component.",
    )
    return parser.parse_args()


def _safe_system_cpu_percent() -> float | None:
    if not _HAS_PSUTIL:
        return None
    try:
        return float(psutil.cpu_percent(interval=None))
    except Exception:
        return None


def _safe_process_rss_mb(process) -> float | None:
    if process is None:
        return None
    try:
        return float(process.memory_info().rss) / (1024.0 * 1024.0)
    except Exception:
        return None


def _sum_camera_metric(per_camera: dict, key: str) -> int:
    total = 0
    for payload in (per_camera or {}).values():
        try:
            total += int(payload.get(key, 0))
        except Exception:
            continue
    return total


def _build_live_status(
    *,
    snapshot: dict,
    started_epoch: float,
    pid: int,
    mem_start_mb: float | None,
    process,
) -> dict:
    now_epoch = time.time()
    elapsed_sec = max(0.0, now_epoch - float(started_epoch))
    elapsed_min = elapsed_sec / 60.0

    frame_q = snapshot.get("frame_queue", {}) or {}
    result_q = snapshot.get("result_queue", {}) or {}
    inference = snapshot.get("inference_worker", {}) or {}
    persistence = snapshot.get("measured_persistence", {}) or {}
    latency = persistence.get("latency_ms", {}) or {}
    ingestion = snapshot.get("ingestion", {}) or {}
    service = ingestion.get("service", {}) or {}
    per_camera = ingestion.get("per_camera", {}) or {}
    dead_letters = snapshot.get("dead_letters", {}) or {}
    resilience = snapshot.get("resilience", {}) or {}

    queue_depth_current = max(
        int(frame_q.get("size", 0) or 0),
        int(result_q.get("size", 0) or 0),
    )
    queue_depth_high = max(
        int(frame_q.get("high_watermark", 0) or 0),
        int(result_q.get("high_watermark", 0) or 0),
    )

    dead_total = int(dead_letters.get("total", 0) or 0)
    dead_rate = (dead_total / elapsed_min) if elapsed_min > 0 else 0.0
    dropped_frames_total = int(frame_q.get("dropped_overflow", 0) or 0) + int(
        frame_q.get("dropped_replaced", 0) or 0
    )
    dropped_events_total = int(result_q.get("dropped_overflow", 0) or 0) + int(
        result_q.get("dropped_replaced", 0) or 0
    )

    cpu_percent = _safe_system_cpu_percent()
    mem_current_mb = _safe_process_rss_mb(process)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": int(pid),
        "running": bool(
            (snapshot.get("ingestion", {}) or {}).get("service", {}).get("running", False)
            or (snapshot.get("inference_worker", {}) or {}).get("running", False)
            or (snapshot.get("event_writer_worker", {}) or {}).get("running", False)
        ),
        "elapsed_min": round(elapsed_min, 3),
        "throughput": {
            "frames_processed_total": int(inference.get("processed", 0) or 0),
            "events_persisted_total": int(persistence.get("persisted", 0) or 0),
            "persist_success_pct": float(persistence.get("success_pct", 0.0) or 0.0),
        },
        "inference": {
            "p95_end_to_end_ms": float(latency.get("end_to_end_p95", 0.0) or 0.0),
            "infer_latency_avg_ms": float(inference.get("avg_latency_ms", 0.0) or 0.0),
            "queue_depth_current": int(queue_depth_current),
            "queue_depth_high_watermark": int(queue_depth_high),
        },
        "drops": {
            "dropped_frames_total": int(dropped_frames_total),
            "dropped_events_total": int(dropped_events_total),
        },
        "resources": {
            "cpu_percent": cpu_percent,
            "ram_mb_start": mem_start_mb,
            "ram_mb_current": mem_current_mb,
        },
        "ingestion": {
            "cam_health_counts": {
                "up": int((service.get("health_counts", {}) or {}).get("up", 0)),
                "degraded": int((service.get("health_counts", {}) or {}).get("degraded", 0)),
                "down": int((service.get("health_counts", {}) or {}).get("down", 0)),
            },
            "reconnect_attempts_total": _sum_camera_metric(per_camera, "reconnect_attempts"),
            "decode_errors_total": _sum_camera_metric(per_camera, "read_errors"),
        },
        "dead_letters": {
            "dead_letters_total": int(dead_total),
            "dead_letters_rate_per_min": round(float(dead_rate), 3),
        },
        "resilience": {
            "enabled": bool(resilience.get("enabled", False)),
            "supervisor_running": bool(resilience.get("supervisor_running", False)),
            "restarts_total": int(resilience.get("restarts_total", 0) or 0),
            "incidents_total": int(resilience.get("incidents_total", 0) or 0),
            "restarts": {
                "ingestion": int((resilience.get("restarts", {}) or {}).get("ingestion", 0) or 0),
                "inference": int((resilience.get("restarts", {}) or {}).get("inference", 0) or 0),
                "writer": int((resilience.get("restarts", {}) or {}).get("writer", 0) or 0),
            },
        },
    }


def _parse_checkpoint_seconds(raw_minutes: str, *, duration_sec: int) -> list[int]:
    points: set[int] = set()
    text = str(raw_minutes or "").strip()
    if not text:
        return []
    for token in text.split(","):
        value = token.strip()
        if not value:
            continue
        try:
            minute = float(value)
        except Exception:
            continue
        if minute <= 0:
            continue
        sec = int(round(minute * 60.0))
        if sec <= 0:
            continue
        if sec <= int(duration_sec):
            points.add(sec)
    return sorted(points)


def _derive_checkpoint_path(*, output_json: str, checkpoint_json: str) -> str:
    explicit = str(checkpoint_json or "").strip()
    if explicit:
        return explicit
    output = str(output_json or "").strip()
    if not output:
        return ""
    base = Path(output)
    return str(base.with_name(f"{base.stem}_checkpoints{base.suffix or '.json'}"))


def _write_json_file(path: str, payload: object) -> None:
    target = str(path or "").strip()
    if not target:
        return
    p = Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_post_run_summary(
    *,
    final_live_status: dict,
    thresholds: RuntimeThresholds,
    evaluation: dict | None,
) -> dict:
    throughput = final_live_status.get("throughput", {}) or {}
    inference = final_live_status.get("inference", {}) or {}
    drops = final_live_status.get("drops", {}) or {}
    resources = final_live_status.get("resources", {}) or {}

    p95 = float(inference.get("p95_end_to_end_ms", 0.0) or 0.0)
    infer_avg = float(inference.get("infer_latency_avg_ms", 0.0) or 0.0)
    queue_current = int(inference.get("queue_depth_current", 0) or 0)
    queue_high = int(inference.get("queue_depth_high_watermark", 0) or 0)
    persist_success = float(throughput.get("persist_success_pct", 0.0) or 0.0)
    dropped_frames = int(drops.get("dropped_frames_total", 0) or 0)
    dropped_events = int(drops.get("dropped_events_total", 0) or 0)

    verdict = str((evaluation or {}).get("verdict") or "NO-EVAL")
    alerts: list[dict] = []

    if p95 > float(thresholds.p95_end_to_end_ms_max):
        alerts.append(
            {
                "severity": "critical",
                "code": "p95_over_sla",
                "message": (
                    f"p95_end_to_end_ms={round(p95, 3)} > "
                    f"{round(float(thresholds.p95_end_to_end_ms_max), 3)}"
                ),
            }
        )
    if queue_high > int(thresholds.queue_depth_max):
        alerts.append(
            {
                "severity": "critical",
                "code": "queue_high_watermark_over_threshold",
                "message": f"queue_depth_high_watermark={queue_high} > {int(thresholds.queue_depth_max)}",
            }
        )
    if persist_success < float(thresholds.event_persist_success_min_pct):
        alerts.append(
            {
                "severity": "critical",
                "code": "persist_success_below_threshold",
                "message": (
                    f"persist_success_pct={round(persist_success, 3)} < "
                    f"{round(float(thresholds.event_persist_success_min_pct), 3)}"
                ),
            }
        )
    if dropped_events > int(thresholds.queue_overflow_max):
        alerts.append(
            {
                "severity": "critical",
                "code": "dropped_events_detected",
                "message": (
                    f"dropped_events_total={dropped_events} > "
                    f"{int(thresholds.queue_overflow_max)}"
                ),
            }
        )
    if dropped_frames > 0:
        alerts.append(
            {
                "severity": "warning",
                "code": "dropped_frames_detected",
                "message": f"dropped_frames_total={dropped_frames}",
            }
        )

    recommendations: list[str] = []
    if queue_high > int(thresholds.queue_depth_max) or dropped_events > int(thresholds.queue_overflow_max):
        recommendations.append("Increase writer_workers and/or sample_interval_ms, then rerun 60m validation.")
    if p95 > float(thresholds.p95_end_to_end_ms_max):
        recommendations.append("Lower ingestion pressure or increase inference throughput (workers/batch tuning).")
    if persist_success < float(thresholds.event_persist_success_min_pct):
        recommendations.append("Investigate DB latency/errors before increasing camera load.")
    if not recommendations:
        recommendations.append("Baseline is stable for long-run validation at current load.")

    return {
        "status": "healthy" if not alerts else "attention_required",
        "verdict": verdict,
        "metrics": {
            "p95_end_to_end_ms": round(p95, 3),
            "infer_latency_avg_ms": round(infer_avg, 3),
            "queue_depth_current": int(queue_current),
            "queue_depth_high_watermark": int(queue_high),
            "persist_success_pct": round(persist_success, 3),
            "dropped_frames_total": int(dropped_frames),
            "dropped_events_total": int(dropped_events),
            "cpu_percent": resources.get("cpu_percent"),
            "ram_mb_start": resources.get("ram_mb_start"),
            "ram_mb_current": resources.get("ram_mb_current"),
        },
        "alerts": alerts,
        "recommendations": recommendations,
    }


def main() -> None:
    args = parse_args()
    config = DistributedPipelineConfig(
        role=args.role,
        queue_backend=args.queue_backend,
        queue_sqlite_path=args.queue_sqlite_path,
        queue_namespace=args.queue_namespace,
        queue_purge_on_start=bool(args.queue_purge_on_start),
        frame_queue_maxsize=int(args.frame_queue_maxsize),
        result_queue_maxsize=int(args.result_queue_maxsize),
        camera_count=int(args.camera_count),
        sample_interval_ms=int(args.sample_interval_ms),
        inference_mode=args.inference_mode,
        inference_workers=int(args.inference_workers),
        inference_batch_size=int(args.inference_batch_size),
        inference_batch_max_wait_ms=float(args.inference_batch_max_wait_ms),
        writer_workers=int(args.writer_workers),
        persist_target=args.persist_target,
        frame_reader_latency_ms_min=float(args.frame_read_ms_min),
        frame_reader_latency_ms_max=float(args.frame_read_ms_max),
        inference_latency_ms_min=float(args.inference_ms_min),
        inference_latency_ms_max=float(args.inference_ms_max),
        inference_success_ratio=float(args.inference_success_ratio),
        persistence_latency_ms_min=float(args.persist_ms_min),
        persistence_latency_ms_max=float(args.persist_ms_max),
        persistence_success_ratio=float(args.persist_success_ratio),
        dead_letter_backend=str(args.dead_letter_backend),
        dead_letter_sqlite_path=str(args.dead_letter_sqlite_path),
        dead_letter_namespace=str(args.dead_letter_namespace or args.queue_namespace),
        resilience_supervisor_enabled=not bool(args.disable_resilience_supervisor),
        resilience_supervisor_interval_sec=float(args.resilience_supervisor_interval_sec),
        resilience_restart_cooldown_sec=float(args.resilience_restart_cooldown_sec),
        resilience_max_restarts_per_component=int(args.resilience_max_restarts_per_component),
    )
    thresholds = RuntimeThresholds(
        p95_end_to_end_ms_max=float(args.p95_threshold_ms),
        queue_depth_max=int(args.queue_depth_threshold),
        queue_overflow_max=int(args.queue_overflow_threshold),
        event_persist_success_min_pct=float(args.persist_success_threshold_pct),
    )
    node = DistributedPipelineNode(config=config)

    started_at = datetime.now(timezone.utc).isoformat()
    started_epoch = time.time()
    process = psutil.Process(os.getpid()) if _HAS_PSUTIL else None
    mem_start_mb = _safe_process_rss_mb(process)
    output_json = str(args.output_json or "").strip()
    live_status_path = str(args.live_status_json or "").strip()
    checkpoint_seconds = _parse_checkpoint_seconds(
        str(args.checkpoint_minutes or ""),
        duration_sec=int(args.duration_sec),
    )
    checkpoint_schedule_min = [round(float(sec) / 60.0, 3) for sec in checkpoint_seconds]
    checkpoint_path = _derive_checkpoint_path(
        output_json=output_json,
        checkpoint_json=str(args.checkpoint_json or ""),
    )
    checkpoints: list[dict] = []
    next_checkpoint_idx = 0
    progress_samples: list[dict] = []
    interval = max(1, int(args.progress_interval_sec))

    node.start()
    try:
        for sec in range(max(1, int(args.duration_sec))):
            time.sleep(1)
            current_sec = sec + 1
            collect_progress = (current_sec % interval == 0) or (sec == 0)
            collect_checkpoint = (
                next_checkpoint_idx < len(checkpoint_seconds)
                and current_sec >= checkpoint_seconds[next_checkpoint_idx]
            )

            if not collect_progress and not collect_checkpoint:
                continue

            snap = node.snapshot()
            if collect_progress:
                progress_samples.append(
                    {
                        "t_sec": current_sec,
                        "frame_queue_size": snap.get("frame_queue", {}).get("size"),
                        "frame_queue_high_watermark": snap.get("frame_queue", {}).get("high_watermark"),
                        "frame_dropped_overflow": snap.get("frame_queue", {}).get("dropped_overflow", 0),
                        "frame_dropped_replaced": snap.get("frame_queue", {}).get("dropped_replaced", 0),
                        "result_queue_size": snap.get("result_queue", {}).get("size"),
                        "result_dropped_overflow": snap.get("result_queue", {}).get("dropped_overflow", 0),
                        "result_dropped_replaced": snap.get("result_queue", {}).get("dropped_replaced", 0),
                        "inference_processed": snap.get("inference_worker", {}).get("processed", 0),
                        "writer_processed": snap.get("event_writer_worker", {}).get("processed", 0),
                        "persisted": snap.get("measured_persistence", {}).get("persisted", 0),
                        "persist_failed": snap.get("measured_persistence", {}).get("failed", 0),
                        "dead_letters_total": snap.get("dead_letters", {}).get("total", 0),
                    }
                )

            live_status = _build_live_status(
                snapshot=snap,
                started_epoch=started_epoch,
                pid=os.getpid(),
                mem_start_mb=mem_start_mb,
                process=process,
            )
            if live_status_path:
                _write_json_file(live_status_path, live_status)

            while next_checkpoint_idx < len(checkpoint_seconds) and current_sec >= checkpoint_seconds[next_checkpoint_idx]:
                checkpoint_sec = int(checkpoint_seconds[next_checkpoint_idx])
                checkpoint_min = round(float(checkpoint_sec) / 60.0, 3)
                checkpoint = {
                    "checkpoint_min": checkpoint_min,
                    "t_sec": int(current_sec),
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "live_status": live_status,
                }
                checkpoints.append(checkpoint)
                if not bool(args.quiet_checkpoints):
                    print(
                        json.dumps(
                            {
                                "type": "checkpoint",
                                "checkpoint_min": checkpoint_min,
                                "elapsed_min": live_status.get("elapsed_min"),
                                "queue_depth_current": (
                                    (live_status.get("inference", {}) or {}).get("queue_depth_current")
                                ),
                                "queue_depth_high_watermark": (
                                    (live_status.get("inference", {}) or {}).get("queue_depth_high_watermark")
                                ),
                                "p95_end_to_end_ms": (
                                    (live_status.get("inference", {}) or {}).get("p95_end_to_end_ms")
                                ),
                                "infer_latency_avg_ms": (
                                    (live_status.get("inference", {}) or {}).get("infer_latency_avg_ms")
                                ),
                                "dropped_frames_total": (
                                    (live_status.get("drops", {}) or {}).get("dropped_frames_total")
                                ),
                                "dropped_events_total": (
                                    (live_status.get("drops", {}) or {}).get("dropped_events_total")
                                ),
                                "cpu_percent": (
                                    (live_status.get("resources", {}) or {}).get("cpu_percent")
                                ),
                                "ram_mb_current": (
                                    (live_status.get("resources", {}) or {}).get("ram_mb_current")
                                ),
                            }
                        )
                    )
                if checkpoint_path:
                    _write_json_file(
                        checkpoint_path,
                        {
                            "checkpoint_schedule_min": checkpoint_schedule_min,
                            "checkpoints": checkpoints,
                        },
                    )
                next_checkpoint_idx += 1
    finally:
        node.stop()

    ended_at = datetime.now(timezone.utc).isoformat()
    final_snapshot = node.snapshot()
    final_live_status = _build_live_status(
        snapshot=final_snapshot,
        started_epoch=started_epoch,
        pid=os.getpid(),
        mem_start_mb=mem_start_mb,
        process=process,
    )
    evaluation = node.evaluate(thresholds) if args.role in {"full", "writer"} else None
    post_run_summary = _build_post_run_summary(
        final_live_status=final_live_status,
        thresholds=thresholds,
        evaluation=evaluation,
    )
    report = {
        "phase": "scaling_runtime_distributed",
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_sec": int(args.duration_sec),
        "config": asdict(config),
        "thresholds": asdict(thresholds),
        "evaluation": evaluation,
        "final_snapshot": final_snapshot,
        "final_live_status": final_live_status,
        "checkpoint_schedule_min": checkpoint_schedule_min,
        "checkpoint_path": checkpoint_path or None,
        "checkpoints": checkpoints,
        "progress_samples": progress_samples,
        "post_run_summary": post_run_summary,
    }

    payload = json.dumps(report, indent=2)
    print(payload)

    if output_json:
        path = Path(output_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    if checkpoint_path:
        _write_json_file(
            checkpoint_path,
            {
                "checkpoint_schedule_min": checkpoint_schedule_min,
                "checkpoints": checkpoints,
                "final_live_status": final_live_status,
                "post_run_summary": post_run_summary,
            },
        )

    if live_status_path:
        _write_json_file(live_status_path, final_live_status)


if __name__ == "__main__":
    main()
