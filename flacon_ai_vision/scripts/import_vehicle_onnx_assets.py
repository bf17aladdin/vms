"""
Import/check vehicle ONNX terrain assets (brand/color/model) for backend pipeline.

Expected destination paths are read from `.env`:
  VEHICLE_TINY_TERRAIN_ONNX_BRAND_MODEL_PATH
  VEHICLE_TINY_TERRAIN_ONNX_BRAND_LABELS_PATH
  VEHICLE_TINY_TERRAIN_ONNX_COLOR_MODEL_PATH
  VEHICLE_TINY_TERRAIN_ONNX_COLOR_LABELS_PATH
  VEHICLE_TINY_TERRAIN_ONNX_MODEL_MODEL_PATH
  VEHICLE_TINY_TERRAIN_ONNX_MODEL_LABELS_PATH

Usage:
  python scripts/import_vehicle_onnx_assets.py --source-dir "C:\\models\\terrain"
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class AssetPaths:
    brand_model: Path
    brand_labels: Path
    color_model: Path
    color_labels: Path
    model_model: Path
    model_labels: Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import/check ONNX terrain assets for vehicle profile inference.")
    parser.add_argument("--source-dir", default="", help="Optional folder to auto-discover assets.")
    parser.add_argument("--brand-model", default="")
    parser.add_argument("--brand-labels", default="")
    parser.add_argument("--color-model", default="")
    parser.add_argument("--color-labels", default="")
    parser.add_argument("--model-model", default="")
    parser.add_argument("--model-labels", default="")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-copy", action="store_true", help="Only validate/check, do not copy files.")
    parser.add_argument(
        "--output-json",
        default="data/reports/vehicle_onnx_assets_report.json",
        help="Write detailed report JSON.",
    )
    return parser.parse_args()


def _load_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _resolve_path(repo_root: Path, value: str, default_rel: str) -> Path:
    candidate = value.strip() if value else default_rel
    p = Path(candidate)
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    return p


def _discover_from_source(source_dir: Path) -> Dict[str, Optional[Path]]:
    if not source_dir.exists() or not source_dir.is_dir():
        return {}

    files = [p for p in source_dir.rglob("*") if p.is_file()]

    def find_exact(name: str) -> Optional[Path]:
        for p in files:
            if p.name.lower() == name.lower():
                return p
        return None

    def find_pattern(*tokens: str, suffix: str) -> Optional[Path]:
        for p in files:
            low = p.name.lower()
            if not low.endswith(suffix.lower()):
                continue
            if all(token.lower() in low for token in tokens):
                return p
        return None

    return {
        "brand_model": find_exact("brand_classifier.onnx") or find_pattern("brand", suffix=".onnx"),
        "brand_labels": find_exact("brand_labels.json") or find_pattern("brand", "label", suffix=".json"),
        "color_model": find_exact("color_classifier.onnx") or find_pattern("color", suffix=".onnx"),
        "color_labels": find_exact("color_labels.json") or find_pattern("color", "label", suffix=".json"),
        "model_model": find_exact("model_classifier.onnx") or find_pattern("model", suffix=".onnx"),
        "model_labels": find_exact("model_labels.json") or find_pattern("model", "label", suffix=".json"),
    }


def _copy_if_needed(src: Optional[Path], dst: Path, overwrite: bool) -> Dict[str, object]:
    if src is None:
        return {"copied": False, "reason": "source_missing"}
    if not src.exists():
        return {"copied": False, "reason": f"source_not_found:{src}"}
    if dst.exists() and not overwrite:
        return {"copied": False, "reason": "destination_exists_skip"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return {"copied": True, "reason": "ok", "source": str(src), "destination": str(dst)}


def _build_destinations(repo_root: Path) -> AssetPaths:
    env = _load_env_file(repo_root / ".env")
    return AssetPaths(
        brand_model=_resolve_path(
            repo_root,
            env.get("VEHICLE_TINY_TERRAIN_ONNX_BRAND_MODEL_PATH", ""),
            "models/vehicle/terrain/brand_classifier.onnx",
        ),
        brand_labels=_resolve_path(
            repo_root,
            env.get("VEHICLE_TINY_TERRAIN_ONNX_BRAND_LABELS_PATH", ""),
            "models/vehicle/terrain/brand_labels.json",
        ),
        color_model=_resolve_path(
            repo_root,
            env.get("VEHICLE_TINY_TERRAIN_ONNX_COLOR_MODEL_PATH", ""),
            "models/vehicle/terrain/color_classifier.onnx",
        ),
        color_labels=_resolve_path(
            repo_root,
            env.get("VEHICLE_TINY_TERRAIN_ONNX_COLOR_LABELS_PATH", ""),
            "models/vehicle/terrain/color_labels.json",
        ),
        model_model=_resolve_path(
            repo_root,
            env.get("VEHICLE_TINY_TERRAIN_ONNX_MODEL_MODEL_PATH", ""),
            "models/vehicle/terrain/model_classifier.onnx",
        ),
        model_labels=_resolve_path(
            repo_root,
            env.get("VEHICLE_TINY_TERRAIN_ONNX_MODEL_LABELS_PATH", ""),
            "models/vehicle/terrain/model_labels.json",
        ),
    )


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    destinations = _build_destinations(repo_root)

    source_dir = Path(args.source_dir).resolve() if str(args.source_dir).strip() else None
    auto = _discover_from_source(source_dir) if source_dir is not None else {}

    explicit = {
        "brand_model": Path(args.brand_model).resolve() if args.brand_model else None,
        "brand_labels": Path(args.brand_labels).resolve() if args.brand_labels else None,
        "color_model": Path(args.color_model).resolve() if args.color_model else None,
        "color_labels": Path(args.color_labels).resolve() if args.color_labels else None,
        "model_model": Path(args.model_model).resolve() if args.model_model else None,
        "model_labels": Path(args.model_labels).resolve() if args.model_labels else None,
    }

    sources = {
        key: (explicit.get(key) or auto.get(key))
        for key in ("brand_model", "brand_labels", "color_model", "color_labels", "model_model", "model_labels")
    }

    copy_results: Dict[str, Dict[str, object]] = {}
    if not args.skip_copy:
        copy_results["brand_model"] = _copy_if_needed(sources.get("brand_model"), destinations.brand_model, args.overwrite)
        copy_results["brand_labels"] = _copy_if_needed(sources.get("brand_labels"), destinations.brand_labels, args.overwrite)
        copy_results["color_model"] = _copy_if_needed(sources.get("color_model"), destinations.color_model, args.overwrite)
        copy_results["color_labels"] = _copy_if_needed(sources.get("color_labels"), destinations.color_labels, args.overwrite)
        copy_results["model_model"] = _copy_if_needed(sources.get("model_model"), destinations.model_model, args.overwrite)
        copy_results["model_labels"] = _copy_if_needed(sources.get("model_labels"), destinations.model_labels, args.overwrite)

    exists = {
        "brand_model": destinations.brand_model.exists(),
        "brand_labels": destinations.brand_labels.exists(),
        "color_model": destinations.color_model.exists(),
        "color_labels": destinations.color_labels.exists(),
        "model_model": destinations.model_model.exists(),
        "model_labels": destinations.model_labels.exists(),
    }

    validation = {"terrain_available": False, "brand_head": False, "color_head": False, "model_head": False, "error": ""}
    try:
        from vms.backend.services.vehicle_ai.tiny_onnx_terrain_classifier import TinyOnnxTerrainClassifier

        terrain = TinyOnnxTerrainClassifier(
            enabled=True,
            brand_model_path=str(destinations.brand_model),
            brand_labels_path=str(destinations.brand_labels),
            color_model_path=str(destinations.color_model),
            color_labels_path=str(destinations.color_labels),
            model_model_path=str(destinations.model_model),
            model_labels_path=str(destinations.model_labels),
            input_size=112,
        )
        validation["terrain_available"] = bool(getattr(terrain, "available", False))
        validation["brand_head"] = bool(getattr(terrain.brand_head, "available", False))
        validation["color_head"] = bool(getattr(terrain.color_head, "available", False))
        validation["model_head"] = bool(getattr(terrain.model_head, "available", False))
    except Exception as exc:  # pragma: no cover
        validation["error"] = str(exc)

    report = {
        "repo_root": str(repo_root),
        "source_dir": str(source_dir) if source_dir is not None else None,
        "sources": {k: (str(v) if v is not None else None) for k, v in sources.items()},
        "destinations": {
            "brand_model": str(destinations.brand_model),
            "brand_labels": str(destinations.brand_labels),
            "color_model": str(destinations.color_model),
            "color_labels": str(destinations.color_labels),
            "model_model": str(destinations.model_model),
            "model_labels": str(destinations.model_labels),
        },
        "copy_results": copy_results,
        "exists": exists,
        "validation": validation,
    }

    output_json = Path(args.output_json).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"report_json={output_json}")

    required_ok = all(exists.values())
    return 0 if required_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
