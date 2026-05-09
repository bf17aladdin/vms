from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
PLATE_SPLIT_RE = re.compile(r"[^0-9A-Za-z]+")


def _normalize_plate_compact(value: Optional[str]) -> str:
    return re.sub(r"[^0-9A-Z]+", "", str(value or "").upper())


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _bool_to_str(value: bool) -> str:
    return "true" if bool(value) else "false"


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


@dataclass
class GroundTruth:
    plate_number: Optional[str] = None
    plate_type: Optional[str] = None
    color: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None


def _find_images(root: Path, recursive: bool) -> List[Path]:
    if recursive:
        paths = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    else:
        paths = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(paths)


def _infer_expected_from_path(path: Path) -> GroundTruth:
    folder_tags = {part.strip().lower() for part in path.parts}
    stem = path.stem
    stem_tokens = [token for token in PLATE_SPLIT_RE.split(stem) if token]
    stem_tokens_lower = [token.lower() for token in stem_tokens]

    expected_type: Optional[str] = None
    if "military" in folder_tags or "militaire" in folder_tags or any(
        token in {"military", "militaire"} for token in stem_tokens_lower
    ):
        expected_type = "military"
    elif "civil" in folder_tags or "civile" in folder_tags or any(token in {"civil", "civile"} for token in stem_tokens_lower):
        expected_type = "civil"

    numeric_tokens = [token for token in stem_tokens if token.isdigit()]
    expected_plate: Optional[str] = None
    if expected_type == "military" and len(numeric_tokens) >= 2:
        expected_plate = f"{numeric_tokens[0]} {numeric_tokens[1]}"
    elif len(stem_tokens) >= 2:
        # Generic fallback when civil format is unknown.
        filtered = [t for t in stem_tokens if t.lower() not in {"military", "militaire", "civil", "civile", "mix"}]
        if filtered:
            if filtered[-1].isdigit() and len(filtered[-1]) <= 2 and len(filtered) >= 2:
                filtered = filtered[:-1]
            expected_plate = " ".join(filtered) if filtered else None

    return GroundTruth(plate_number=expected_plate, plate_type=expected_type)


def _load_ground_truth_csv(path: Optional[Path]) -> Dict[str, GroundTruth]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"Ground truth CSV not found: {path}")

    mapping: Dict[str, GroundTruth] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row:
                continue
            filename = str(
                row.get("filename")
                or row.get("file")
                or row.get("image")
                or row.get("image_name")
                or ""
            ).strip()
            if not filename:
                continue
            key = filename.replace("\\", "/").lower()
            mapping[key] = GroundTruth(
                plate_number=str(row.get("plate_number") or row.get("plate") or "").strip() or None,
                plate_type=str(row.get("plate_type") or row.get("type") or "").strip().lower() or None,
                color=str(row.get("color") or row.get("dominant_color") or "").strip().lower() or None,
                brand=str(row.get("brand") or row.get("make") or "").strip() or None,
                model=str(row.get("model") or "").strip() or None,
            )
    return mapping


def _resolve_ground_truth(
    image_path: Path,
    dataset_root: Path,
    csv_map: Dict[str, GroundTruth],
) -> GroundTruth:
    inferred = _infer_expected_from_path(image_path)
    if not csv_map:
        return inferred

    relative_key = image_path.relative_to(dataset_root).as_posix().lower()
    basename_key = image_path.name.lower()
    gt = csv_map.get(relative_key) or csv_map.get(basename_key)
    if gt is None:
        return inferred

    return GroundTruth(
        plate_number=gt.plate_number or inferred.plate_number,
        plate_type=gt.plate_type or inferred.plate_type,
        color=gt.color,
        brand=gt.brand,
        model=gt.model,
    )


def _build_upload_file(
    image_path: Path,
    *,
    upload_max_side: int,
    upload_jpeg_quality: int,
) -> Tuple[str, bytes, str]:
    raw = image_path.read_bytes()
    if upload_max_side <= 0 or cv2 is None or np is None:
        return image_path.name, raw, "application/octet-stream"

    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return image_path.name, raw, "application/octet-stream"

    height, width = frame.shape[:2]
    current_max_side = max(int(height), int(width))
    if current_max_side <= upload_max_side:
        return image_path.name, raw, "application/octet-stream"

    scale = float(upload_max_side) / float(max(1, current_max_side))
    target_w = max(1, int(round(width * scale)))
    target_h = max(1, int(round(height * scale)))
    resized = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
    quality = max(60, min(100, int(upload_jpeg_quality)))
    ok, encoded = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        return image_path.name, raw, "application/octet-stream"

    return f"{image_path.stem}_side{upload_max_side}.jpg", encoded.tobytes(), "image/jpeg"


def _is_timeout_error(api_error: str, payload: Dict[str, Any]) -> bool:
    text = str(api_error or "").lower()
    if isinstance(payload, dict):
        text = f"{text} {str(payload.get('detail') or '')} {str(payload.get('message') or '')}".lower()
    return any(token in text for token in ("timeout", "timed out", "deadline exceeded"))


def _call_detect(
    session: requests.Session,
    *,
    api_base: str,
    image_path: Path,
    camera_id: int,
    confidence: float,
    iou_threshold: float,
    max_detections: int,
    vehicle_only: bool,
    plate_only_fallback: bool,
    use_modular_engine: bool,
    timeout_sec: float,
    upload_max_side: int = 0,
    upload_jpeg_quality: int = 90,
) -> Tuple[bool, Dict[str, Any], str, float]:
    url = f"{api_base.rstrip('/')}/vehicle/detect"
    payload = {
        "camera_id": str(camera_id),
        "confidence": str(confidence),
        "iou_threshold": str(iou_threshold),
        "max_detections": str(max_detections),
        "vehicle_only": _bool_to_str(vehicle_only),
        "plate_only_fallback": _bool_to_str(plate_only_fallback),
        "use_modular_engine": _bool_to_str(use_modular_engine),
    }
    started = time.perf_counter()
    try:
        upload_name, upload_bytes, upload_mime = _build_upload_file(
            image_path,
            upload_max_side=int(upload_max_side),
            upload_jpeg_quality=int(upload_jpeg_quality),
        )
        files = {"file": (upload_name, upload_bytes, upload_mime)}
        response = session.post(url, data=payload, files=files, timeout=timeout_sec)
        latency_ms = (time.perf_counter() - started) * 1000.0
    except Exception as exc:
        return False, {}, str(exc), (time.perf_counter() - started) * 1000.0

    text_error = ""
    try:
        body = response.json()
    except Exception:
        body = {}
        text_error = response.text[:400]

    if not response.ok:
        detail = ""
        if isinstance(body, dict):
            detail = str(body.get("detail") or body.get("message") or "")
        if not detail:
            detail = text_error or f"HTTP {response.status_code}"
        return False, body if isinstance(body, dict) else {}, detail, latency_ms

    return True, body if isinstance(body, dict) else {}, "", latency_ms


def _extract_detection(payload: Dict[str, Any]) -> Dict[str, Any]:
    vehicles = payload.get("vehicles") if isinstance(payload.get("vehicles"), list) else []
    first = vehicles[0] if vehicles else {}
    profile = first.get("vehicle_profile") if isinstance(first.get("vehicle_profile"), dict) else {}
    consistency = first.get("consistency") if isinstance(first.get("consistency"), dict) else {}
    if not consistency and isinstance(payload.get("consistency"), dict):
        consistency = payload.get("consistency")
    anomaly = first.get("anomaly") if isinstance(first.get("anomaly"), dict) else {}
    if not anomaly and isinstance(payload.get("anomaly"), dict):
        anomaly = payload.get("anomaly")
    alert = first.get("anomaly_alert") if isinstance(first.get("anomaly_alert"), dict) else {}
    if not alert and isinstance(payload.get("anomaly_alert"), dict):
        alert = payload.get("anomaly_alert")

    plate = str(first.get("plate") or payload.get("plate_number") or "").strip() or None
    plate_type = str(first.get("plate_type") or payload.get("plate_type") or "unknown").strip().lower()
    if plate_type not in {"civil", "military", "unknown"}:
        plate_type = "unknown"

    return {
        "success": bool(payload.get("success", False)),
        "vehicles_count": _safe_int(payload.get("vehicles_count"), len(vehicles)),
        "plate_number": plate,
        "plate_type": plate_type,
        "vehicle_class": first.get("class"),
        "vehicle_confidence": _safe_float(first.get("confidence")),
        "plate_confidence": _safe_float(first.get("plate_confidence")),
        "vehicle_bbox": first.get("bbox"),
        "plate_bbox": first.get("plate_bbox"),
        "dominant_color": str(first.get("color") or profile.get("dominant_color") or "unknown").strip().lower(),
        "brand": str(profile.get("brand") or profile.get("make") or "").strip() or None,
        "brand_key": str(profile.get("brand_key") or "").strip() or None,
        "model": str(profile.get("model") or "").strip() or None,
        "logo_path": str(first.get("logo_path") or profile.get("logo_path") or "").strip() or None,
        "track_id": first.get("track_id"),
        "consistency_score": _safe_float(consistency.get("consistency_score")),
        "consistency_level": str(consistency.get("confidence_level") or ""),
        "consistency_flags": consistency.get("flags") if isinstance(consistency.get("flags"), list) else [],
        "anomaly_detected": bool(anomaly.get("detected")),
        "anomaly_level": str(anomaly.get("level") or ""),
        "anomaly_reason": str(anomaly.get("reason") or ""),
        "anomaly_alert_emit": bool(alert.get("should_emit")),
        "anomaly_alert_suppressed": bool(alert.get("suppressed")),
        "anomaly_alert_level": str(alert.get("severity_level") or ""),
        "pipeline": payload.get("pipeline") if isinstance(payload.get("pipeline"), dict) else {},
        "backend": payload.get("backend"),
        "inference_ms": _safe_float(payload.get("inference_ms")),
    }


def _evaluate_detection(detected: Dict[str, Any], expected: GroundTruth) -> Dict[str, Any]:
    expected_plate_compact = _normalize_plate_compact(expected.plate_number)
    detected_plate_compact = _normalize_plate_compact(detected.get("plate_number"))

    checks: Dict[str, Optional[bool]] = {
        "plate_detected": bool(detected.get("plate_number")),
        "vehicle_detected": _safe_int(detected.get("vehicles_count"), 0) > 0,
        "plate_type_match": None,
        "plate_match": None,
        "color_match": None,
        "brand_match": None,
        "model_match": None,
    }

    if expected.plate_type:
        checks["plate_type_match"] = _normalize_text(expected.plate_type) == _normalize_text(
            str(detected.get("plate_type") or "")
        )
    if expected_plate_compact:
        checks["plate_match"] = expected_plate_compact == detected_plate_compact
    if expected.color:
        checks["color_match"] = _normalize_text(expected.color) == _normalize_text(str(detected.get("dominant_color") or ""))
    if expected.brand:
        checks["brand_match"] = _normalize_text(expected.brand) == _normalize_text(str(detected.get("brand") or ""))
    if expected.model:
        checks["model_match"] = _normalize_text(expected.model) == _normalize_text(str(detected.get("model") or ""))

    scored_items = [value for value in checks.values() if value is not None]
    pass_count = sum(1 for value in scored_items if value)
    score = float(pass_count / len(scored_items)) if scored_items else 0.0

    return {
        "checks": checks,
        "score": round(score, 4),
    }


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "image_path",
        "ok_http",
        "api_error",
        "latency_ms",
        "expected_plate",
        "expected_type",
        "detected_plate",
        "detected_type",
        "plate_detected",
        "plate_match",
        "plate_type_match",
        "consistency_score",
        "anomaly_detected",
        "anomaly_level",
        "brand",
        "model",
        "dominant_color",
        "logo_path",
        "score",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for item in rows:
            checks = item.get("evaluation", {}).get("checks", {})
            det = item.get("detected", {})
            expected = item.get("expected", {})
            writer.writerow(
                {
                    "image_path": item.get("image_path"),
                    "ok_http": item.get("ok_http"),
                    "api_error": item.get("api_error") or "",
                    "latency_ms": round(_safe_float(item.get("latency_ms")), 2),
                    "expected_plate": expected.get("plate_number"),
                    "expected_type": expected.get("plate_type"),
                    "detected_plate": det.get("plate_number"),
                    "detected_type": det.get("plate_type"),
                    "plate_detected": checks.get("plate_detected"),
                    "plate_match": checks.get("plate_match"),
                    "plate_type_match": checks.get("plate_type_match"),
                    "consistency_score": det.get("consistency_score"),
                    "anomaly_detected": det.get("anomaly_detected"),
                    "anomaly_level": det.get("anomaly_level"),
                    "brand": det.get("brand"),
                    "model": det.get("model"),
                    "dominant_color": det.get("dominant_color"),
                    "logo_path": det.get("logo_path"),
                    "score": item.get("evaluation", {}).get("score"),
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch benchmark for vehicle ANPR detect API on image datasets.")
    parser.add_argument("--dataset-root", required=True, help="Root folder containing images (military/civil/mix).")
    parser.add_argument("--ground-truth-csv", default="", help="Optional CSV with expected labels.")
    parser.add_argument("--api-base", default="http://127.0.0.1:5003/api", help="Backend API base URL.")
    parser.add_argument("--token", default="", help="Bearer auth token.")
    parser.add_argument("--username", default="", help="Optional username for auto-login when token is empty.")
    parser.add_argument("--password", default="", help="Optional password for auto-login when token is empty.")
    parser.add_argument("--camera-id", type=int, default=1, help="camera_id sent to /vehicle/detect.")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--iou-threshold", type=float, default=0.45)
    parser.add_argument("--max-detections", type=int, default=100)
    parser.add_argument("--vehicle-only", type=_to_bool, default=True)
    parser.add_argument("--plate-only-fallback", type=_to_bool, default=True)
    parser.add_argument("--use-modular-engine", type=_to_bool, default=True)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--timeout-sec", type=float, default=90.0)
    parser.add_argument(
        "--upload-max-side",
        type=int,
        default=0,
        help="Resize large input image before upload (max side in px). 0 disables resize.",
    )
    parser.add_argument(
        "--retry-on-timeout",
        type=_to_bool,
        default=True,
        help="Retry once with fallback resized upload when timeout happens.",
    )
    parser.add_argument(
        "--timeout-retry-max-side",
        type=int,
        default=1600,
        help="Fallback max side for timeout retry (only when retry-on-timeout=true).",
    )
    parser.add_argument("--upload-jpeg-quality", type=int, default=90)
    parser.add_argument("--output-json", default="data/vehicle_dataset_benchmark/report.json")
    parser.add_argument("--output-csv", default="data/vehicle_dataset_benchmark/report.csv")
    parser.add_argument("--include-raw-response", action="store_true")
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).resolve()
    if not dataset_root.exists():
        raise SystemExit(f"Dataset root not found: {dataset_root}")

    image_paths = _find_images(dataset_root, recursive=bool(args.recursive))
    if not image_paths:
        raise SystemExit(f"No images found in: {dataset_root}")

    gt_map = _load_ground_truth_csv(Path(args.ground_truth_csv).resolve()) if args.ground_truth_csv else {}

    session = requests.Session()
    if str(args.token or "").strip():
        session.headers.update({"Authorization": f"Bearer {str(args.token).strip()}"})
    elif str(args.username or "").strip() and str(args.password or "").strip():
        auth_url = f"{str(args.api_base).rstrip('/')}/auth/login"
        auth_response = session.post(
            auth_url,
            json={"username": str(args.username).strip(), "password": str(args.password).strip()},
            timeout=max(10.0, float(args.timeout_sec)),
        )
        auth_response.raise_for_status()
        auth_payload = auth_response.json() if auth_response.content else {}
        token = str(auth_payload.get("access_token") or "").strip()
        if token:
            session.headers.update({"Authorization": f"Bearer {token}"})

    result_rows: List[Dict[str, Any]] = []
    for index, image_path in enumerate(image_paths, start=1):
        relative = image_path.relative_to(dataset_root).as_posix()
        expected = _resolve_ground_truth(image_path=image_path, dataset_root=dataset_root, csv_map=gt_map)
        attempt_sides: List[int] = [max(0, int(args.upload_max_side))]
        retry_side = max(0, int(args.timeout_retry_max_side))
        if bool(args.retry_on_timeout) and retry_side > 0 and retry_side not in attempt_sides:
            attempt_sides.append(retry_side)

        ok_http = False
        payload: Dict[str, Any] = {}
        api_error = ""
        latency_ms = 0.0
        used_upload_side = attempt_sides[0] if attempt_sides else 0
        attempts: List[Dict[str, Any]] = []

        for side in attempt_sides:
            ok_http, payload, api_error, latency_ms = _call_detect(
                session,
                api_base=str(args.api_base).strip(),
                image_path=image_path,
                camera_id=int(args.camera_id),
                confidence=float(args.confidence),
                iou_threshold=float(args.iou_threshold),
                max_detections=int(args.max_detections),
                vehicle_only=bool(args.vehicle_only),
                plate_only_fallback=bool(args.plate_only_fallback),
                use_modular_engine=bool(args.use_modular_engine),
                timeout_sec=float(args.timeout_sec),
                upload_max_side=int(side),
                upload_jpeg_quality=int(args.upload_jpeg_quality),
            )
            used_upload_side = int(side)
            attempts.append(
                {
                    "upload_max_side": int(side),
                    "ok_http": bool(ok_http),
                    "api_error": api_error,
                    "latency_ms": round(float(latency_ms), 3),
                }
            )
            if ok_http or not _is_timeout_error(api_error, payload):
                break

        detected = _extract_detection(payload) if ok_http else {}
        evaluation = _evaluate_detection(detected=detected, expected=expected) if ok_http else {"checks": {}, "score": 0.0}

        row: Dict[str, Any] = {
            "index": index,
            "image_path": relative,
            "ok_http": ok_http,
            "api_error": api_error,
            "latency_ms": round(latency_ms, 3),
            "upload_max_side_used": int(used_upload_side),
            "attempts": attempts,
            "expected": {
                "plate_number": expected.plate_number,
                "plate_type": expected.plate_type,
                "color": expected.color,
                "brand": expected.brand,
                "model": expected.model,
            },
            "detected": detected,
            "evaluation": evaluation,
        }
        if bool(args.include_raw_response):
            row["raw_response"] = payload
        result_rows.append(row)

        print(
            f"[{index}/{len(image_paths)}] {relative} | "
            f"http={'ok' if ok_http else 'fail'} | "
            f"plate={detected.get('plate_number') if ok_http else 'N/A'} | "
            f"type={detected.get('plate_type') if ok_http else 'N/A'} | "
            f"side={used_upload_side if used_upload_side > 0 else 'orig'} | "
            f"score={evaluation.get('score', 0.0):.2f} | "
            f"{latency_ms:.1f}ms"
        )

    http_ok = sum(1 for row in result_rows if row.get("ok_http"))
    avg_latency = sum(_safe_float(row.get("latency_ms")) for row in result_rows) / max(1, len(result_rows))
    avg_score = sum(_safe_float(row.get("evaluation", {}).get("score")) for row in result_rows) / max(1, len(result_rows))
    plate_detected = sum(
        1
        for row in result_rows
        if bool(row.get("evaluation", {}).get("checks", {}).get("plate_detected"))
    )
    plate_match_known = [
        row
        for row in result_rows
        if row.get("evaluation", {}).get("checks", {}).get("plate_match") is not None
    ]
    plate_match_ok = sum(
        1
        for row in plate_match_known
        if bool(row.get("evaluation", {}).get("checks", {}).get("plate_match"))
    )
    type_match_known = [
        row
        for row in result_rows
        if row.get("evaluation", {}).get("checks", {}).get("plate_type_match") is not None
    ]
    type_match_ok = sum(
        1
        for row in type_match_known
        if bool(row.get("evaluation", {}).get("checks", {}).get("plate_type_match"))
    )

    summary = {
        "dataset_root": str(dataset_root),
        "api_base": str(args.api_base),
        "total_images": len(result_rows),
        "http_ok": http_ok,
        "http_fail": len(result_rows) - http_ok,
        "plate_detected": plate_detected,
        "plate_detect_rate": round(plate_detected / max(1, len(result_rows)), 4),
        "plate_match_known_count": len(plate_match_known),
        "plate_match_ok_count": plate_match_ok,
        "plate_match_rate": round(plate_match_ok / max(1, len(plate_match_known)), 4) if plate_match_known else None,
        "plate_type_match_known_count": len(type_match_known),
        "plate_type_match_ok_count": type_match_ok,
        "plate_type_match_rate": round(type_match_ok / max(1, len(type_match_known)), 4) if type_match_known else None,
        "avg_latency_ms": round(avg_latency, 3),
        "avg_score": round(avg_score, 4),
        "params": {
            "camera_id": int(args.camera_id),
            "confidence": float(args.confidence),
            "iou_threshold": float(args.iou_threshold),
            "max_detections": int(args.max_detections),
            "vehicle_only": bool(args.vehicle_only),
            "plate_only_fallback": bool(args.plate_only_fallback),
            "use_modular_engine": bool(args.use_modular_engine),
            "recursive": bool(args.recursive),
            "upload_max_side": int(args.upload_max_side),
            "retry_on_timeout": bool(args.retry_on_timeout),
            "timeout_retry_max_side": int(args.timeout_retry_max_side),
            "upload_jpeg_quality": int(args.upload_jpeg_quality),
            "ground_truth_csv": str(args.ground_truth_csv or ""),
        },
    }

    output_json = Path(args.output_json).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    with output_json.open("w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "results": result_rows}, fh, indent=2, ensure_ascii=False)

    output_csv = Path(args.output_csv).resolve()
    _write_csv(output_csv, result_rows)

    print("\n=== Benchmark Summary ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"JSON report: {output_json}")
    print(f"CSV report:  {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
