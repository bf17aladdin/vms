"""
Train YOLO vehicle classification (civil vs military) on prepared dataset.

Default dataset expected:
  data/datasets/tunisian_vehicles_prepared/vehicle_classification
"""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train vehicle classification model.")
    parser.add_argument(
        "--data",
        default="data/datasets/tunisian_vehicles_prepared/vehicle_classification",
        help="Dataset root containing train/val/test class folders.",
    )
    parser.add_argument("--model", default="yolov8n-cls.yaml", help="YOLO classification model or weights.")
    parser.add_argument("--epochs", type=int, default=60, help="Training epochs.")
    parser.add_argument("--imgsz", type=int, default=224, help="Image size.")
    parser.add_argument("--batch", type=int, default=16, help="Batch size.")
    parser.add_argument("--workers", type=int, default=2, help="Data loader workers.")
    parser.add_argument("--project", default="runs/vehicle_classification", help="Project output dir.")
    parser.add_argument("--name", default="civil_military_v1", help="Run name.")
    parser.add_argument(
        "--device",
        default="auto",
        help="Device to use: auto | cpu | 0",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = Path(args.data).resolve()
    if not data_dir.exists():
        raise SystemExit(f"Dataset not found: {data_dir}")

    device = args.device
    if device == "auto":
        device = "0" if torch.cuda.is_available() else "cpu"

    print("Starting vehicle classification training")
    print(f"data={data_dir}")
    print(f"model={args.model}")
    print(f"epochs={args.epochs} imgsz={args.imgsz} batch={args.batch} workers={args.workers}")
    print(f"device={device}")
    print(f"project={args.project} name={args.name}")

    model = YOLO(args.model)
    model.train(
        data=str(data_dir),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        workers=args.workers,
        project=args.project,
        name=args.name,
        device=device,
    )

    print("Training completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

