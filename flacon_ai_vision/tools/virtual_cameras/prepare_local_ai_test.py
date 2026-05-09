from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PACKAGE_ROOT = REPO_ROOT / "backend"
if str(BACKEND_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_PACKAGE_ROOT))

os.environ.setdefault("DATABASE_URL", f"sqlite:///{(REPO_ROOT / 'data' / 'falcon.db').as_posix()}")
os.environ.setdefault("FACE_PGVECTOR_ENABLED", "false")

from vms.backend import crud, models  # noqa: E402
from vms.backend.bootstrap import seed_admin_user  # noqa: E402
from vms.backend.core.config import settings  # noqa: E402
from vms.backend.core.database import SessionLocal, init_db  # noqa: E402
from vms.backend.services.face_ai.face_detector import FaceDetector  # noqa: E402
from vms.backend.services.stream_service import StreamService  # noqa: E402
from vms.backend.services.vehicle_ai.vehicle_detector import VehicleDetector  # noqa: E402

try:
    import cv2  # type: ignore  # noqa: E402
    import numpy as np  # type: ignore  # noqa: E402
except Exception as exc:  # pragma: no cover - environment dependency
    raise SystemExit(f"OpenCV is required for this workflow: {exc}") from exc


DEFAULT_CAMERA_URLS = {
    "cam01": "rtsp://127.0.0.1:8554/cam01",
    "cam02": "rtsp://127.0.0.1:8554/cam02",
    "cam03": "rtsp://127.0.0.1:8554/cam03",
    "cam04": "rtsp://127.0.0.1:8554/cam04",
}
EXPECTED_CODEC = "h264"
EXPECTED_WIDTH = 1280
EXPECTED_HEIGHT = 720
EXPECTED_FPS = 25.0


@dataclass
class CameraSource:
    name: str
    rtsp_url: str
    source_video: Optional[str] = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare Falcon AI Vision for local SQLite testing with virtual RTSP cameras."
    )
    parser.add_argument(
        "--runtime-path",
        default=str(REPO_ROOT / "tools" / "virtual_cameras" / "virtual_camera_runtime.json"),
        help="Optional runtime metadata file produced by start_video_virtual_cameras.ps1",
    )
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "data" / "camera_selection"),
        help="Directory where snapshots and reports are written",
    )
    parser.add_argument("--sample-count", type=int, default=4, help="Frames to sample per camera")
    parser.add_argument(
        "--sample-interval-sec",
        type=float,
        default=1.2,
        help="Delay between sampled frames from a stream",
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:5003",
        help="Backend base URL for optional end-to-end API validation",
    )
    parser.add_argument(
        "--api-username",
        default=str(getattr(settings, "ADMIN_USERNAME", "admin") or "admin"),
        help="Username used for API validation if backend is already running",
    )
    parser.add_argument(
        "--api-password",
        default=str(getattr(settings, "ADMIN_PASSWORD", "admin123") or "admin123"),
        help="Password used for API validation if backend is already running",
    )
    parser.add_argument(
        "--skip-api-validation",
        action="store_true",
        help="Skip /api/facial and /api/vehicle validation against a live backend",
    )
    return parser.parse_args()


def load_camera_sources(runtime_path: Path) -> list[CameraSource]:
    if runtime_path.exists():
        try:
            payload = json.loads(runtime_path.read_text(encoding="utf-8"))
            rows = payload.get("cameras") or []
            sources: list[CameraSource] = []
            for row in rows:
                name = str(row.get("name") or "").strip()
                rtsp_url = str(row.get("rtsp_url") or "").strip()
                if not name or not rtsp_url:
                    continue
                source_video = str(row.get("source_video") or "").strip() or None
                sources.append(CameraSource(name=name, rtsp_url=rtsp_url, source_video=source_video))
            if sources:
                return sources
        except Exception:
            pass
    return [CameraSource(name=name, rtsp_url=url) for name, url in DEFAULT_CAMERA_URLS.items()]


def fps_from_fraction(raw_value: str) -> Optional[float]:
    raw = str(raw_value or "").strip()
    if not raw:
        return None
    if "/" in raw:
        left, right = raw.split("/", 1)
        try:
            numerator = float(left)
            denominator = float(right)
            if denominator == 0:
                return None
            return numerator / denominator
        except Exception:
            return None
    try:
        return float(raw)
    except Exception:
        return None


def run_ffprobe(rtsp_url: str) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        rtsp_url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {
            "reachable": False,
            "codec": None,
            "width": None,
            "height": None,
            "fps": None,
            "frame_rate_raw": None,
            "error": str(exc),
            "profile_match": False,
        }

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    if result.returncode != 0 or not stdout:
        return {
            "reachable": False,
            "codec": None,
            "width": None,
            "height": None,
            "fps": None,
            "frame_rate_raw": None,
            "error": stderr or f"ffprobe exited with code {result.returncode}",
            "profile_match": False,
        }

    try:
        payload = json.loads(stdout)
        stream = (payload.get("streams") or [{}])[0]
    except Exception as exc:
        return {
            "reachable": False,
            "codec": None,
            "width": None,
            "height": None,
            "fps": None,
            "frame_rate_raw": None,
            "error": f"Failed to parse ffprobe output: {exc}",
            "profile_match": False,
        }

    fps = fps_from_fraction(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
    codec = str(stream.get("codec_name") or "").strip().lower() or None
    width = int(stream.get("width") or 0) or None
    height = int(stream.get("height") or 0) or None
    profile_match = bool(
        codec == EXPECTED_CODEC
        and width == EXPECTED_WIDTH
        and height == EXPECTED_HEIGHT
        and fps is not None
        and abs(float(fps) - EXPECTED_FPS) <= 0.6
    )
    return {
        "reachable": True,
        "codec": codec,
        "width": width,
        "height": height,
        "fps": round(float(fps), 3) if fps is not None else None,
        "frame_rate_raw": str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or ""),
        "error": stderr or None,
        "profile_match": profile_match,
    }


def json_request(
    method: str,
    url: str,
    payload: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    body = None
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url=url, method=method.upper(), data=body, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return int(response.status), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {"detail": raw or str(exc)}
        return int(exc.code), data


def face_visibility_score(detections: list[Any], frame_shape: tuple[int, int, int]) -> tuple[float, float]:
    frame_h, frame_w = frame_shape[:2]
    if frame_h <= 0 or frame_w <= 0 or not detections:
        return (0.0, 0.0)
    image_area = float(frame_h * frame_w)
    max_distance = math.sqrt((frame_w / 2.0) ** 2 + (frame_h / 2.0) ** 2) or 1.0
    total_score = 0.0
    max_area_ratio = 0.0
    for det in detections:
        x, y, w, h = det.bbox
        area_ratio = max(0.0, (float(w) * float(h)) / image_area)
        center_x = float(x) + (float(w) / 2.0)
        center_y = float(y) + (float(h) / 2.0)
        distance = math.sqrt((center_x - (frame_w / 2.0)) ** 2 + (center_y - (frame_h / 2.0)) ** 2)
        center_bonus = 1.0 - min(1.0, distance / max_distance)
        source = str(getattr(det, "source", "") or "").lower()
        frontal_bonus = 0.6 if "profile" in source else 1.0
        total_score += float(getattr(det, "score", 0.0) or 0.0) * (1.0 + area_ratio * 18.0) * (0.35 + center_bonus) * frontal_bonus
        max_area_ratio = max(max_area_ratio, area_ratio)
    return (total_score, max_area_ratio)


def vehicle_motion_proxy(previous_gray: Optional[np.ndarray], current_gray: np.ndarray) -> dict[str, float]:
    if previous_gray is None:
        return {
            "motion_ratio": 0.0,
            "proxy_count": 0.0,
            "proxy_area_ratio": 0.0,
            "proxy_spread": 0.0,
        }
    diff = cv2.absdiff(previous_gray, current_gray)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    kernel = np.ones((3, 3), dtype=np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
    thresh = cv2.dilate(thresh, kernel, iterations=1)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    frame_area = float(current_gray.shape[0] * current_gray.shape[1]) or 1.0
    centers: list[float] = []
    area_ratios: list[float] = []
    for contour in contours:
        area_ratio = float(cv2.contourArea(contour)) / frame_area
        if area_ratio < 0.002 or area_ratio > 0.35:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = float(w) / max(float(h), 1.0)
        if aspect_ratio < 0.7 or aspect_ratio > 4.5:
            continue
        centers.append(float(x) + (float(w) / 2.0))
        area_ratios.append(area_ratio)
    spread = 0.0
    if len(centers) > 1:
        spread = float(statistics.pstdev(centers) / max(float(current_gray.shape[1]), 1.0))
    motion_ratio = float((thresh > 0).mean())
    return {
        "motion_ratio": motion_ratio,
        "proxy_count": float(len(area_ratios)),
        "proxy_area_ratio": float(sum(area_ratios)),
        "proxy_spread": spread,
    }


def snapshot_path_for(sample_dir: Path, index: int) -> Path:
    return sample_dir / f"sample_{index:02d}.jpg"


def sample_camera(
    camera: CameraSource,
    sample_dir: Path,
    sample_count: int,
    sample_interval_sec: float,
    face_detector: FaceDetector,
    vehicle_detector: VehicleDetector,
) -> dict[str, Any]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    previous_gray: Optional[np.ndarray] = None
    best_snapshot: Optional[str] = None
    best_face_signal = -1.0
    inspect_payload = StreamService.inspect_rtsp_stream(
        camera.rtsp_url,
        open_timeout_sec=4.0,
        read_timeout_sec=4.0,
        force_tcp=True,
        sample_frames=max(2, min(sample_count, 6)),
        include_preview=False,
    )

    for index in range(sample_count):
        frame = StreamService.get_camera_frame(camera_id=index + 1, rtsp_url=camera.rtsp_url)
        if frame is None:
            samples.append(
                {
                    "index": index,
                    "captured": False,
                    "brightness": None,
                    "blur": None,
                    "motion_ratio": None,
                    "face_count": 0,
                    "vehicle_count": 0,
                    "snapshot_path": None,
                }
            )
            time.sleep(max(0.0, sample_interval_sec))
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = float(gray.mean())
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        motion = vehicle_motion_proxy(previous_gray, gray)
        faces = face_detector.detect(frame, max_faces=10)
        vehicles = vehicle_detector.detect(frame)
        face_signal, face_area_ratio = face_visibility_score(faces, frame.shape)
        vehicle_area_ratio = 0.0
        vehicle_signal = 0.0
        image_area = float(frame.shape[0] * frame.shape[1]) or 1.0
        for det in vehicles:
            x, y, w, h = det.bbox
            ratio = (float(w) * float(h)) / image_area
            vehicle_area_ratio += ratio
            vehicle_signal += float(det.confidence) * (1.0 + (ratio * 12.0))

        snapshot_path = snapshot_path_for(sample_dir, index)
        cv2.imwrite(str(snapshot_path), frame)
        if face_signal > best_face_signal:
            best_face_signal = face_signal
            best_snapshot = str(snapshot_path)

        samples.append(
            {
                "index": index,
                "captured": True,
                "brightness": round(brightness, 3),
                "blur": round(blur, 3),
                "motion_ratio": round(float(motion["motion_ratio"]), 5),
                "vehicle_proxy_count": int(motion["proxy_count"]),
                "vehicle_proxy_area_ratio": round(float(motion["proxy_area_ratio"]), 5),
                "vehicle_proxy_spread": round(float(motion["proxy_spread"]), 5),
                "face_count": len(faces),
                "face_visibility": round(face_signal, 4),
                "face_area_ratio": round(face_area_ratio, 5),
                "vehicle_count": len(vehicles),
                "vehicle_visibility": round(vehicle_signal, 4),
                "vehicle_area_ratio": round(vehicle_area_ratio, 5),
                "snapshot_path": str(snapshot_path),
            }
        )
        previous_gray = gray
        time.sleep(max(0.0, sample_interval_sec))

    try:
        StreamService.release_camera_stream(rtsp_url=camera.rtsp_url)
    except Exception:
        pass

    captured_rows = [row for row in samples if row["captured"]]
    brightness_values = [float(row["brightness"]) for row in captured_rows]
    blur_values = [float(row["blur"]) for row in captured_rows]
    motion_values = [float(row["motion_ratio"]) for row in captured_rows]
    face_counts = [int(row["face_count"]) for row in captured_rows]
    face_visibility_values = [float(row["face_visibility"]) for row in captured_rows]
    face_area_values = [float(row["face_area_ratio"]) for row in captured_rows]
    vehicle_counts = [int(row["vehicle_count"]) for row in captured_rows]
    vehicle_visibility_values = [float(row["vehicle_visibility"]) for row in captured_rows]
    vehicle_area_values = [float(row["vehicle_area_ratio"]) for row in captured_rows]
    proxy_counts = [int(row["vehicle_proxy_count"]) for row in captured_rows]
    proxy_spreads = [float(row["vehicle_proxy_spread"]) for row in captured_rows]

    avg_brightness = statistics.mean(brightness_values) if brightness_values else 0.0
    avg_blur = statistics.mean(blur_values) if blur_values else 0.0
    avg_motion = statistics.mean(motion_values) if motion_values else 0.0
    avg_face_visibility = statistics.mean(face_visibility_values) if face_visibility_values else 0.0
    best_face_area = max(face_area_values) if face_area_values else 0.0
    avg_vehicle_visibility = statistics.mean(vehicle_visibility_values) if vehicle_visibility_values else 0.0
    avg_vehicle_area = statistics.mean(vehicle_area_values) if vehicle_area_values else 0.0
    avg_proxy_count = statistics.mean(proxy_counts) if proxy_counts else 0.0
    avg_proxy_spread = statistics.mean(proxy_spreads) if proxy_spreads else 0.0

    brightness_score = max(0.0, 100.0 - abs(avg_brightness - 135.0) * 1.15)
    sharpness_score = min(100.0, avg_blur / 5.0)
    motion_score = min(100.0, avg_motion * 1200.0)
    face_presence_score = min(
        100.0,
        (sum(face_counts) * 10.0) + (avg_face_visibility * 6.0) + (best_face_area * 1200.0),
    )
    vehicle_presence_score = min(
        100.0,
        (sum(vehicle_counts) * 12.0)
        + (avg_vehicle_visibility * 5.0)
        + (avg_vehicle_area * 800.0)
        + (avg_proxy_count * 8.0)
        + (avg_proxy_spread * 30.0),
    )
    face_score = round((brightness_score * 0.22) + (sharpness_score * 0.24) + (face_presence_score * 0.54), 2)
    vehicle_score = round(
        (brightness_score * 0.15)
        + (sharpness_score * 0.18)
        + (motion_score * 0.17)
        + (vehicle_presence_score * 0.50),
        2,
    )
    mixed_score = round(
        ((face_score + vehicle_score) / 2.0) + (min(brightness_score, sharpness_score) * 0.15),
        2,
    )

    return {
        "camera_name": camera.name,
        "rtsp_url": camera.rtsp_url,
        "source_video": camera.source_video,
        "stream_probe": inspect_payload,
        "sample_count_requested": sample_count,
        "sample_count_captured": len(captured_rows),
        "snapshots_dir": str(sample_dir),
        "best_snapshot_path": best_snapshot,
        "metrics": {
            "brightness_mean": round(avg_brightness, 3),
            "blur_mean": round(avg_blur, 3),
            "motion_ratio_mean": round(avg_motion, 5),
            "face_count_total": int(sum(face_counts)),
            "face_visibility_mean": round(avg_face_visibility, 4),
            "best_face_area_ratio": round(best_face_area, 5),
            "vehicle_count_total": int(sum(vehicle_counts)),
            "vehicle_visibility_mean": round(avg_vehicle_visibility, 4),
            "vehicle_area_ratio_mean": round(avg_vehicle_area, 5),
            "vehicle_proxy_count_mean": round(avg_proxy_count, 3),
            "vehicle_proxy_spread_mean": round(avg_proxy_spread, 5),
            "scores": {
                "brightness_score": round(brightness_score, 2),
                "sharpness_score": round(sharpness_score, 2),
                "motion_score": round(motion_score, 2),
                "face_score": face_score,
                "vehicle_score": vehicle_score,
                "mixed_score": mixed_score,
            },
        },
        "samples": samples,
    }


def pick_role(rankings: list[dict[str, Any]], excluded: set[str]) -> Optional[str]:
    for row in rankings:
        camera_name = str(row["camera_name"])
        if camera_name not in excluded:
            return camera_name
    return str(rankings[0]["camera_name"]) if rankings else None


def select_roles(camera_results: list[dict[str, Any]]) -> dict[str, str]:
    candidates = []
    for row in camera_results:
        ffprobe = row["ffprobe"]
        probe = row["analysis"]["stream_probe"]
        reachable = bool(ffprobe["reachable"] and probe.get("ok"))
        if not reachable:
            continue
        scores = row["analysis"]["metrics"]["scores"]
        candidates.append(
            {
                "camera_name": row["camera_name"],
                "face_score": float(scores["face_score"]),
                "vehicle_score": float(scores["vehicle_score"]),
                "mixed_score": float(scores["mixed_score"]),
            }
        )

    face_rank = sorted(candidates, key=lambda item: item["face_score"], reverse=True)
    vehicle_rank = sorted(candidates, key=lambda item: item["vehicle_score"], reverse=True)
    mixed_rank = sorted(candidates, key=lambda item: item["mixed_score"], reverse=True)
    face_pick = pick_role(face_rank, excluded=set())
    vehicle_pick = pick_role(vehicle_rank, excluded={face_pick} if face_pick else set())
    mixed_excluded = {name for name in [face_pick, vehicle_pick] if name}
    mixed_pick = pick_role(mixed_rank, excluded=mixed_excluded)

    roles: dict[str, str] = {}
    if face_pick:
        roles[face_pick] = "best_for_faces"
    if vehicle_pick:
        roles[vehicle_pick] = "best_for_vehicles"
    if mixed_pick:
        roles[mixed_pick] = "mixed_detection"
    return roles


def ensure_virtual_camera_rows(
    camera_results: list[dict[str, Any]],
    selected_roles: dict[str, str],
    zone_name: str = "Virtual Lab",
) -> dict[str, int]:
    init_db()
    seed_admin_user()
    db = SessionLocal()
    try:
        tenant = crud.ensure_default_tenant(db)
        admin_user = crud.get_user_by_username(db, settings.ADMIN_USERNAME)
        if admin_user is None:
            raise RuntimeError("Admin user missing after bootstrap")

        created_or_updated: dict[str, int] = {}
        role_to_camera_type = {
            "best_for_faces": "face",
            "best_for_vehicles": "vehicle",
            "mixed_detection": "mix",
        }
        for row in camera_results:
            name = str(row["camera_name"])
            rtsp_url = str(row["rtsp_url"])
            analysis = row["analysis"]
            ffprobe = row["ffprobe"]
            selection_role = selected_roles.get(name)
            selection_score = None
            if selection_role == "best_for_faces":
                selection_score = analysis["metrics"]["scores"]["face_score"]
            elif selection_role == "best_for_vehicles":
                selection_score = analysis["metrics"]["scores"]["vehicle_score"]
            elif selection_role == "mixed_detection":
                selection_score = analysis["metrics"]["scores"]["mixed_score"]

            camera = (
                db.query(models.Camera)
                .filter(
                    (models.Camera.rtsp_url == rtsp_url)
                    | (models.Camera.name == f"Virtual {name}")
                )
                .order_by(models.Camera.id.asc())
                .first()
            )
            if camera is None:
                camera = models.Camera(
                    tenant_id=int(tenant.id),
                    owner_id=int(admin_user.id),
                    name=f"Virtual {name}",
                    description=f"Virtual RTSP camera for local Falcon AI validation ({name})",
                    rtsp_url=rtsp_url,
                    ip_address="127.0.0.1",
                    port=8554,
                    location=f"Virtual Camera {name}",
                    zone_name=zone_name,
                    streaming_enabled=True,
                    is_active=True,
                    is_enabled=True,
                    motion_detection_enabled=True,
                    object_detection_enabled=True,
                    detection_sensitivity=60,
                    ai_enabled=True,
                )
                db.add(camera)
                db.flush()

            camera.tenant_id = int(tenant.id)
            camera.owner_id = int(admin_user.id)
            camera.name = f"Virtual {name}"
            camera.description = (
                f"Virtual RTSP camera for local Falcon AI validation ({name})"
                + (f" sourced from {analysis['source_video']}" if analysis.get("source_video") else "")
            )
            camera.rtsp_url = rtsp_url
            camera.ip_address = "127.0.0.1"
            camera.port = 8554
            camera.location = f"Virtual Camera {name}"
            camera.zone_name = zone_name
            camera.streaming_enabled = True
            camera.is_active = True
            camera.is_enabled = True
            camera.motion_detection_enabled = True
            camera.object_detection_enabled = True
            camera.ai_enabled = True
            camera.camera_type = role_to_camera_type.get(selection_role, "mix")
            camera.selection_role = selection_role
            camera.selection_score = float(selection_score) if selection_score is not None else None
            camera.stream_validation_status = "connected" if bool(ffprobe["reachable"]) else "error"
            camera.stream_validation_message = (
                "RTSP validated"
                if bool(ffprobe["reachable"])
                else str(ffprobe.get("error") or "RTSP validation failed")
            )[:255]
            camera.stream_codec = ffprobe.get("codec")
            camera.stream_width = int(ffprobe["width"]) if ffprobe.get("width") else None
            camera.stream_height = int(ffprobe["height"]) if ffprobe.get("height") else None
            camera.stream_fps = float(ffprobe["fps"]) if ffprobe.get("fps") is not None else None
            camera.last_snapshot_path = analysis.get("best_snapshot_path")
            camera.analysis_metadata = {
                "selected_role": selection_role,
                "ffprobe": ffprobe,
                "stream_probe": analysis.get("stream_probe"),
                "metrics": analysis.get("metrics"),
                "snapshots_dir": analysis.get("snapshots_dir"),
                "updated_at": utc_now_iso(),
            }
            created_or_updated[name] = int(camera.id)

        db.commit()
        return created_or_updated
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def validate_api_outputs(
    api_base: str,
    username: str,
    password: str,
    camera_ids: dict[str, int],
) -> dict[str, Any]:
    login_status, login_payload = json_request(
        "POST",
        f"{api_base.rstrip('/')}/api/auth/login",
        payload={"username": username, "password": password},
        timeout=20,
    )
    if login_status != 200:
        return {
            "available": False,
            "login_status": login_status,
            "error": login_payload.get("detail") or "Unable to authenticate against backend",
        }

    token = str(login_payload.get("access_token") or "").strip()
    if not token:
        return {
            "available": False,
            "login_status": login_status,
            "error": "Backend login succeeded but no access token was returned",
        }

    headers = {"Authorization": f"Bearer {token}"}
    results: dict[str, Any] = {"available": True, "login_status": login_status, "cameras": {}}
    for camera_name, camera_id in camera_ids.items():
        face_status, face_payload = json_request(
            "GET",
            f"{api_base.rstrip('/')}/api/facial/detect-faces/{camera_id}",
            headers=headers,
            timeout=45,
        )
        vehicle_status, vehicle_payload = json_request(
            "POST",
            f"{api_base.rstrip('/')}/api/vehicle/recognize/camera/{camera_id}",
            payload={"persist": False, "save_snapshot": False},
            headers=headers,
            timeout=60,
        )
        results["cameras"][camera_name] = {
            "camera_id": camera_id,
            "face_status": face_status,
            "face_detections_count": face_payload.get("detections_count"),
            "face_message": face_payload.get("message") or face_payload.get("detail"),
            "vehicle_status": vehicle_status,
            "vehicle_detected": vehicle_payload.get("vehicle_detected"),
            "vehicle_plate_number": vehicle_payload.get("plate_number"),
            "vehicle_message": vehicle_payload.get("message") or vehicle_payload.get("detail"),
        }
    return results


def main() -> int:
    args = parse_args()
    runtime_path = Path(args.runtime_path).resolve()
    output_root = Path(args.output_root).resolve()
    report_dir = output_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)

    camera_sources = load_camera_sources(runtime_path)
    face_detector = FaceDetector(det_size=(640, 640))
    vehicle_detector = VehicleDetector()

    camera_results: list[dict[str, Any]] = []
    for camera in camera_sources:
        ffprobe_result = run_ffprobe(camera.rtsp_url)
        analysis = sample_camera(
            camera=camera,
            sample_dir=report_dir / camera.name,
            sample_count=max(1, int(args.sample_count)),
            sample_interval_sec=max(0.0, float(args.sample_interval_sec)),
            face_detector=face_detector,
            vehicle_detector=vehicle_detector,
        )
        camera_results.append(
            {
                "camera_name": camera.name,
                "rtsp_url": camera.rtsp_url,
                "ffprobe": ffprobe_result,
                "analysis": analysis,
            }
        )

    selected_roles = select_roles(camera_results)
    camera_ids = ensure_virtual_camera_rows(camera_results, selected_roles=selected_roles)

    api_validation = {
        "available": False,
        "skipped": True,
        "reason": "skip requested",
    }
    if not args.skip_api_validation:
        try:
            api_validation = validate_api_outputs(
                api_base=str(args.api_base),
                username=str(args.api_username),
                password=str(args.api_password),
                camera_ids=camera_ids,
            )
        except Exception as exc:
            api_validation = {
                "available": False,
                "skipped": False,
                "error": str(exc),
            }

    report = {
        "generated_at": utc_now_iso(),
        "database_url": settings.DATABASE_URL,
        "database_path": str(REPO_ROOT / "data" / "falcon.db"),
        "report_dir": str(report_dir),
        "face_backend": face_detector.backend,
        "vehicle_backend": vehicle_detector.backend,
        "expected_stream_profile": {
            "codec": EXPECTED_CODEC,
            "width": EXPECTED_WIDTH,
            "height": EXPECTED_HEIGHT,
            "fps": EXPECTED_FPS,
        },
        "selected_roles": selected_roles,
        "camera_ids": camera_ids,
        "cameras": camera_results,
        "api_validation": api_validation,
    }

    report_path = report_dir / "local_ai_test_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
