#!/usr/bin/env python
"""
Calibrate FACE_MATCH_THRESHOLD from labeled score samples.

Modes:
1) CSV mode (recommended):
   - Provide --csv with columns:
       score,label
   - label values accepted: 1/0, true/false, matched/unknown, known/impostor, etc.

2) DB mode (quick baseline):
   - Use --from-db to read face_detections from DATABASE_URL.
   - Labels are heuristic:
       personnel_id IS NOT NULL -> positive (known)
       personnel_id IS NULL     -> negative (unknown)
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class Sample:
    score: float
    label: int  # 1 = positive, 0 = negative


@dataclass
class Metrics:
    threshold: float
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    accuracy: float
    far: float
    frr: float
    youden_j: float
    balanced_accuracy: float


TRUE_LABELS = {"1", "true", "t", "yes", "y", "matched", "known", "positive", "genuine", "same"}
FALSE_LABELS = {"0", "false", "f", "no", "n", "unknown", "impostor", "negative", "different"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate face match threshold.")
    parser.add_argument("--csv", default="", help="Path to CSV file with score,label columns.")
    parser.add_argument("--score-col", default="score", help="CSV score column name.")
    parser.add_argument("--label-col", default="label", help="CSV label column name.")
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Use face_detections from DB as a fallback dataset (heuristic labels).",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Override DATABASE_URL for DB mode.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="How many past days to use in DB mode.",
    )
    parser.add_argument(
        "--metric",
        choices=["f1", "balanced_accuracy", "youden_j"],
        default="balanced_accuracy",
        help="Optimization metric for threshold selection.",
    )
    parser.add_argument(
        "--write-env",
        default="",
        help="Optional .env file path to update FACE_MATCH_THRESHOLD.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=30,
        help="Minimum number of samples required for reliable calibration.",
    )
    return parser.parse_args()


def _parse_label(raw: str) -> int | None:
    value = str(raw).strip().lower()
    if value in TRUE_LABELS:
        return 1
    if value in FALSE_LABELS:
        return 0
    return None


def load_csv_samples(path: str, score_col: str, label_col: str) -> list[Sample]:
    samples: list[Sample] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if score_col not in row or label_col not in row:
                continue
            try:
                score = float(str(row[score_col]).strip())
            except Exception:
                continue
            label = _parse_label(row[label_col])
            if label is None:
                continue
            samples.append(Sample(score=score, label=label))
    return samples


def load_db_samples(database_url: str, days: int) -> list[Sample]:
    if database_url:
        os.environ["DATABASE_URL"] = database_url

    from vms.backend.core.database import SessionLocal
    from vms.backend.models import FaceDetection

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    session = SessionLocal()
    try:
        rows = (
            session.query(FaceDetection.confidence, FaceDetection.personnel_id, FaceDetection.detected_at)
            .filter(FaceDetection.detected_at >= cutoff)
            .all()
        )
        out: list[Sample] = []
        for confidence, personnel_id, _detected_at in rows:
            try:
                score = float(confidence or 0.0)
            except Exception:
                continue
            label = 1 if personnel_id is not None else 0
            out.append(Sample(score=score, label=label))
        return out
    finally:
        session.close()


def evaluate(samples: list[Sample], threshold: float) -> Metrics:
    tp = fp = tn = fn = 0
    for sample in samples:
        pred = 1 if sample.score >= threshold else 0
        if pred == 1 and sample.label == 1:
            tp += 1
        elif pred == 1 and sample.label == 0:
            fp += 1
        elif pred == 0 and sample.label == 0:
            tn += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / max(1, (tp + fp + tn + fn))
    far = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    frr = fn / (tp + fn) if (tp + fn) > 0 else 0.0
    tpr = recall
    tnr = tn / (tn + fp) if (tn + fp) > 0 else 0.0
    youden_j = tpr + tnr - 1.0
    balanced_accuracy = (tpr + tnr) / 2.0

    return Metrics(
        threshold=threshold,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        accuracy=accuracy,
        far=far,
        frr=frr,
        youden_j=youden_j,
        balanced_accuracy=balanced_accuracy,
    )


def select_best(samples: list[Sample], metric_name: str) -> Metrics:
    scores = sorted({round(sample.score, 6) for sample in samples})
    if not scores:
        raise ValueError("No valid scores found.")

    # Add boundaries for exhaustive sweep.
    thresholds = [min(scores) - 1e-6] + scores + [max(scores) + 1e-6]

    def metric_value(m: Metrics) -> float:
        return getattr(m, metric_name)

    best: Metrics | None = None
    for threshold in thresholds:
        current = evaluate(samples, threshold)
        if best is None:
            best = current
            continue
        if metric_value(current) > metric_value(best):
            best = current
            continue
        if metric_value(current) == metric_value(best):
            # Tie-breaker: favor lower FAR, then lower FRR.
            if current.far < best.far or (current.far == best.far and current.frr < best.frr):
                best = current

    assert best is not None
    return best


def update_env_file(env_path: str, threshold: float) -> None:
    path = Path(env_path)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    key = "FACE_MATCH_THRESHOLD"
    updated = False
    out: list[str] = []
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={threshold:.6f}")
            updated = True
        else:
            out.append(line)

    if not updated:
        out.append(f"{key}={threshold:.6f}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    samples: list[Sample] = []
    source = ""

    if args.csv:
        samples = load_csv_samples(args.csv, args.score_col, args.label_col)
        source = f"csv:{args.csv}"
    elif args.from_db:
        samples = load_db_samples(args.database_url, args.days)
        source = f"db:last_{max(1, args.days)}d"
    else:
        print("ERROR: provide --csv or --from-db")
        return 2

    if len(samples) < args.min_samples:
        print(f"ERROR: not enough samples for calibration ({len(samples)} < {args.min_samples})")
        print("Tip: run a few real surveillance videos first, then export more detections.")
        return 3

    positives = sum(1 for s in samples if s.label == 1)
    negatives = sum(1 for s in samples if s.label == 0)
    if positives == 0 or negatives == 0:
        print("ERROR: calibration requires both positive and negative samples.")
        return 4

    best = select_best(samples, args.metric)

    print(f"Source: {source}")
    print(f"Samples: total={len(samples)} positives={positives} negatives={negatives}")
    print(f"Metric optimized: {args.metric}")
    print(f"Recommended FACE_MATCH_THRESHOLD={best.threshold:.6f}")
    print(
        "Metrics: "
        f"precision={best.precision:.4f} "
        f"recall={best.recall:.4f} "
        f"f1={best.f1:.4f} "
        f"balanced_accuracy={best.balanced_accuracy:.4f} "
        f"far={best.far:.4f} "
        f"frr={best.frr:.4f}"
    )
    print(f"Confusion: TP={best.tp} FP={best.fp} TN={best.tn} FN={best.fn}")

    if args.write_env:
        update_env_file(args.write_env, best.threshold)
        print(f"Updated {args.write_env} with FACE_MATCH_THRESHOLD={best.threshold:.6f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
