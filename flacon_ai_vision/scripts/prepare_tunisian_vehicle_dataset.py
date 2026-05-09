"""
Prepare Tunisian vehicle dataset from zip archive for local training.

What this script does:
1) Extract the source zip archive.
2) Validate expected folders (vehicle_civil, vehicle_military, face).
3) Build a train/val/test split for vehicle classification.
4) Keep face images in a separate folder and emit a warning report.
5) Generate local YAML files and a JSON summary report.

Usage:
    python scripts/prepare_tunisian_vehicle_dataset.py \
      --zip "C:\\Users\\boufm\\Downloads\\tunisian_vehicles_dataset_full.zip" \
      --output "data/datasets/tunisian_vehicles_prepared" \
      --force
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass(frozen=True)
class SplitRatios:
    train: float
    val: float
    test: float

    def validate(self) -> None:
        total = self.train + self.val + self.test
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Split ratios must sum to 1.0, got {total:.6f}")
        for name, value in (("train", self.train), ("val", self.val), ("test", self.test)):
            if value <= 0.0:
                raise ValueError(f"Split ratio '{name}' must be > 0, got {value}")


def _iter_images(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _split_class_items(items: list[Path], ratios: SplitRatios, rng: random.Random) -> dict[str, list[Path]]:
    data = list(items)
    rng.shuffle(data)
    n = len(data)

    if n == 0:
        return {"train": [], "val": [], "test": []}

    train_count = max(1, int(round(n * ratios.train)))
    val_count = max(1, int(round(n * ratios.val)))
    test_count = n - train_count - val_count

    if test_count <= 0:
        # Keep at least 1 sample in test if possible.
        if train_count > val_count and train_count > 1:
            train_count -= 1
            test_count = 1
        elif val_count > 1:
            val_count -= 1
            test_count = 1
        else:
            # Very small class: fallback where test may be 0.
            test_count = max(0, n - train_count - val_count)

    if train_count + val_count + test_count > n:
        overflow = train_count + val_count + test_count - n
        while overflow > 0 and train_count > 1:
            train_count -= 1
            overflow -= 1
        while overflow > 0 and val_count > 1:
            val_count -= 1
            overflow -= 1

    train_slice = data[:train_count]
    val_slice = data[train_count : train_count + val_count]
    test_slice = data[train_count + val_count : train_count + val_count + test_count]

    return {"train": train_slice, "val": val_slice, "test": test_slice}


def _copy_items(items: list[Path], destination_dir: Path) -> int:
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in items:
        dst = destination_dir / src.name
        # Ensure deterministic unique filenames if collisions occur.
        if dst.exists():
            stem = src.stem
            suffix = src.suffix
            index = 1
            while True:
                candidate = destination_dir / f"{stem}_{index}{suffix}"
                if not candidate.exists():
                    dst = candidate
                    break
                index += 1
        shutil.copy2(src, dst)
        copied += 1
    return copied


def _build_vehicle_yaml(root: Path) -> str:
    # We keep this local and relative to avoid Colab-specific absolute paths.
    return "\n".join(
        [
            "path: .",
            "train: train",
            "val: val",
            "test: test",
            "names:",
            "  0: civil",
            "  1: military",
            "",
        ]
    )


def _build_face_yaml(root: Path) -> str:
    return "\n".join(
        [
            "path: .",
            "task: face_recognition",
            "data: face_raw",
            "note: one_image_per_identity_detected_requires_more_samples_for_training",
            "",
        ]
    )


def prepare_dataset(
    zip_path: Path,
    output_root: Path,
    ratios: SplitRatios,
    seed: int,
    force: bool,
) -> dict:
    if not zip_path.exists():
        raise FileNotFoundError(f"Zip not found: {zip_path}")

    ratios.validate()
    rng = random.Random(seed)

    if output_root.exists():
        if not force:
            raise FileExistsError(
                f"Output already exists: {output_root}. Re-run with --force to overwrite."
            )
        shutil.rmtree(output_root)

    extracted_root = output_root / "raw"
    vehicle_root = output_root / "vehicle_classification"
    face_root = output_root / "face_dataset"

    extracted_root.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extracted_root)

    civil_dir = extracted_root / "vehicle_civil"
    military_dir = extracted_root / "vehicle_military"
    face_dir = extracted_root / "face"

    for required in (civil_dir, military_dir, face_dir):
        if not required.exists():
            raise RuntimeError(f"Missing expected folder in extracted dataset: {required}")

    civil_images = sorted(_iter_images(civil_dir))
    military_images = sorted(_iter_images(military_dir))
    face_images = sorted(_iter_images(face_dir))

    class_to_items = {"civil": civil_images, "military": military_images}
    split_counts: dict[str, dict[str, int]] = {}

    for split_name in ("train", "val", "test"):
        for class_name in class_to_items:
            (vehicle_root / split_name / class_name).mkdir(parents=True, exist_ok=True)

    for class_name, items in class_to_items.items():
        split_map = _split_class_items(items, ratios, rng)
        split_counts[class_name] = {}
        for split_name, split_items in split_map.items():
            copied = _copy_items(split_items, vehicle_root / split_name / class_name)
            split_counts[class_name][split_name] = copied

    face_raw_dir = face_root / "face_raw"
    face_raw_dir.mkdir(parents=True, exist_ok=True)
    face_copied = _copy_items(face_images, face_raw_dir)

    _write_text(vehicle_root / "vehicle_classification.yaml", _build_vehicle_yaml(vehicle_root))
    _write_text(face_root / "face_dataset.yaml", _build_face_yaml(face_root))

    report = {
        "source_zip": str(zip_path),
        "output_root": str(output_root),
        "seed": seed,
        "ratios": {"train": ratios.train, "val": ratios.val, "test": ratios.test},
        "input_counts": {
            "vehicle_civil": len(civil_images),
            "vehicle_military": len(military_images),
            "face_images": len(face_images),
        },
        "vehicle_split_counts": split_counts,
        "face_dataset": {
            "copied_images": face_copied,
            "warning": "Face training is not robust with one image per identity.",
        },
        "generated_files": {
            "vehicle_yaml": str(vehicle_root / "vehicle_classification.yaml"),
            "face_yaml": str(face_root / "face_dataset.yaml"),
            "report_json": str(output_root / "dataset_report.json"),
        },
    }

    _write_text(output_root / "dataset_report.json", json.dumps(report, indent=2))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Tunisian vehicle dataset for local training.")
    parser.add_argument(
        "--zip",
        required=False,
        default=r"C:\Users\boufm\Downloads\tunisian_vehicles_dataset_full.zip",
        help="Path to source zip archive.",
    )
    parser.add_argument(
        "--output",
        required=False,
        default="data/datasets/tunisian_vehicles_prepared",
        help="Output folder for prepared dataset.",
    )
    parser.add_argument("--train-ratio", type=float, default=0.70, help="Train split ratio.")
    parser.add_argument("--val-ratio", type=float, default=0.20, help="Validation split ratio.")
    parser.add_argument("--test-ratio", type=float, default=0.10, help="Test split ratio.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--force", action="store_true", help="Overwrite output folder if it exists.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    zip_path = Path(args.zip).expanduser().resolve()
    output_root = Path(args.output).expanduser().resolve()

    ratios = SplitRatios(train=args.train_ratio, val=args.val_ratio, test=args.test_ratio)
    report = prepare_dataset(
        zip_path=zip_path,
        output_root=output_root,
        ratios=ratios,
        seed=int(args.seed),
        force=bool(args.force),
    )

    print("Dataset preparation completed.")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

