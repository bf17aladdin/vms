"""
Complete face dataset enrollment and evaluate top1/top5 from local folders.

Default dataset layout:
  data/datasets/tunisian_vehicles_prepared/raw/face/person_001/*.jpg

This script:
1) Ensures one personnel profile per folder (DatasetNNN Face).
2) Ensures minimum images per identity via API enrollment.
3) Evaluates recognition on one probe image per identity and reports top1/top5.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None
    np = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
PERSON_RE = re.compile(r"person_(\d+)$", re.IGNORECASE)


@dataclass
class IdentityMap:
    folder_name: str
    person_index: int
    personnel_id: int
    full_name: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch enroll + evaluate face dataset through backend API.")
    parser.add_argument("--api-base", default="http://127.0.0.1:5003/api")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument(
        "--dataset-root",
        default="data/datasets/tunisian_vehicles_prepared/raw/face",
        help="Root folder containing person_XXX subfolders.",
    )
    parser.add_argument("--camera-id", type=int, default=1)
    parser.add_argument("--min-images-per-identity", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=90.0)
    parser.add_argument("--request-retries", type=int, default=4)
    parser.add_argument("--request-retry-delay-sec", type=float, default=1.5)
    parser.add_argument(
        "--output-json",
        default="data/reports/face_dataset_enroll_eval_report.json",
        help="Path to save detailed JSON report.",
    )
    return parser.parse_args()


def _sleep_with_backoff(base_delay_sec: float, attempt_index: int) -> None:
    delay = base_delay_sec * (1.0 + (attempt_index * 0.5))
    time.sleep(max(0.1, delay))


def _request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout_sec: float,
    retries: int,
    retry_delay_sec: float,
    **kwargs,
) -> requests.Response:
    last_exc: Optional[Exception] = None
    for attempt in range(max(1, retries)):
        try:
            response = session.request(method=method, url=url, timeout=timeout_sec, **kwargs)
            if response.status_code >= 500 and attempt < retries - 1:
                _sleep_with_backoff(retry_delay_sec, attempt)
                continue
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= retries - 1:
                break
            _sleep_with_backoff(retry_delay_sec, attempt)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"Failed request with no response: {method} {url}")


def _login(session: requests.Session, api_base: str, username: str, password: str, timeout_sec: float, retries: int, retry_delay_sec: float) -> str:
    url = f"{api_base.rstrip('/')}/auth/login"
    response = _request_with_retry(
        session,
        "POST",
        url,
        timeout_sec=timeout_sec,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
        json={"username": username, "password": password},
    )
    response.raise_for_status()
    token = (response.json() or {}).get("access_token")
    if not token:
        raise RuntimeError("Login succeeded without access_token.")
    return str(token)


def _list_personnel(
    session: requests.Session,
    api_base: str,
    *,
    timeout_sec: float,
    retries: int,
    retry_delay_sec: float,
) -> List[dict]:
    url = f"{api_base.rstrip('/')}/personnel?limit=500"
    response = _request_with_retry(
        session,
        "GET",
        url,
        timeout_sec=timeout_sec,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _ensure_personnel_for_index(
    session: requests.Session,
    api_base: str,
    *,
    person_index: int,
    existing_by_name: Dict[str, dict],
    timeout_sec: float,
    retries: int,
    retry_delay_sec: float,
) -> IdentityMap:
    prenom = f"Dataset{person_index:03d}"
    nom = "Face"
    full_name = f"{prenom} {nom}"
    key = full_name.strip().lower()

    if key in existing_by_name:
        personnel_id = int(existing_by_name[key].get("id"))
        return IdentityMap(
            folder_name=f"person_{person_index:03d}",
            person_index=person_index,
            personnel_id=personnel_id,
            full_name=full_name,
        )

    payload = {
        "nom": nom,
        "prenom": prenom,
        "cin": f"DS{person_index:07d}",
        "num_recrutement": f"DSR{person_index:07d}",
        "categorie": "civil",
        "grade": "Civil",
        "unite": "DATASET_FACE",
        "telephone": None,
        "email": None,
        "authorized_hours_start": "00:00",
        "authorized_hours_end": "23:59",
        "notes": f"Auto-generated for dataset identity {person_index:03d}",
    }

    url = f"{api_base.rstrip('/')}/personnel"
    response = _request_with_retry(
        session,
        "POST",
        url,
        timeout_sec=timeout_sec,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
        json=payload,
    )
    if response.status_code == 409:
        refreshed = _list_personnel(
            session,
            api_base,
            timeout_sec=timeout_sec,
            retries=retries,
            retry_delay_sec=retry_delay_sec,
        )
        for row in refreshed:
            row_key = str(row.get("full_name") or "").strip().lower()
            existing_by_name[row_key] = row
        if key not in existing_by_name:
            raise RuntimeError(f"Personnel conflict for {full_name}, but record not found afterward.")
        personnel_id = int(existing_by_name[key].get("id"))
    else:
        response.raise_for_status()
        row = response.json() if isinstance(response.json(), dict) else {}
        existing_by_name[key] = row
        personnel_id = int(row.get("id"))

    return IdentityMap(
        folder_name=f"person_{person_index:03d}",
        person_index=person_index,
        personnel_id=personnel_id,
        full_name=full_name,
    )


def _list_person_images(
    session: requests.Session,
    api_base: str,
    personnel_id: int,
    *,
    timeout_sec: float,
    retries: int,
    retry_delay_sec: float,
) -> List[dict]:
    url = f"{api_base.rstrip('/')}/face/personnel/{personnel_id}/images"
    response = _request_with_retry(
        session,
        "GET",
        url,
        timeout_sec=timeout_sec,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else []
    return items if isinstance(items, list) else []


def _decode_bgr(raw: bytes):
    if cv2 is None or np is None:
        return None
    return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)


def _encode_bgr_jpg(frame_bgr) -> Optional[bytes]:
    if cv2 is None:
        return None
    ok, encoded = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        return None
    return encoded.tobytes()


def _detect_face_bboxes(
    session: requests.Session,
    api_base: str,
    *,
    image_name: str,
    image_bytes: bytes,
    camera_id: int,
    timeout_sec: float,
    retries: int,
    retry_delay_sec: float,
) -> List[Tuple[int, int, int, int]]:
    url = f"{api_base.rstrip('/')}/face/recognize-multi"
    response = _request_with_retry(
        session,
        "POST",
        url,
        timeout_sec=timeout_sec,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
        data={"camera_id": str(camera_id), "top_k": "1", "max_faces": "10"},
        files={"file": (image_name, io.BytesIO(image_bytes), "application/octet-stream")},
    )
    if not response.ok:
        return []
    payload = response.json() if response.content else {}
    faces = payload.get("faces") if isinstance(payload, dict) else []
    bboxes: List[Tuple[int, int, int, int]] = []
    for face in faces if isinstance(faces, list) else []:
        if not isinstance(face, dict):
            continue
        bbox = face.get("bbox")
        if not isinstance(bbox, dict):
            continue
        try:
            x = int(float(bbox.get("x", 0)))
            y = int(float(bbox.get("y", 0)))
            w = int(float(bbox.get("w", 0)))
            h = int(float(bbox.get("h", 0)))
        except Exception:
            continue
        if w > 4 and h > 4:
            bboxes.append((x, y, w, h))
    bboxes.sort(key=lambda item: item[2] * item[3], reverse=True)
    return bboxes


def _crop_face(frame_bgr, bbox: Tuple[int, int, int, int], pad_ratio: float = 0.28):
    if frame_bgr is None:
        return None
    x, y, w, h = bbox
    height, width = frame_bgr.shape[:2]
    pad_x = int(round(w * pad_ratio))
    pad_y = int(round(h * pad_ratio))
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(width, x + w + pad_x)
    y2 = min(height, y + h + pad_y)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame_bgr[y1:y2, x1:x2]
    if crop is None or crop.size == 0:
        return None
    return crop


def _encode_variants_from_frame(frame_bgr) -> List[Tuple[str, bytes]]:
    if frame_bgr is None or cv2 is None:
        return []
    variants = [("front", frame_bgr)]
    variants.append(("bright", cv2.convertScaleAbs(frame_bgr, alpha=1.06, beta=18)))
    variants.append(("dark", cv2.convertScaleAbs(frame_bgr, alpha=0.95, beta=-16)))
    out: List[Tuple[str, bytes]] = []
    for label, frame in variants:
        encoded = _encode_bgr_jpg(frame)
        if encoded:
            out.append((label, encoded))
    return out


def _enroll_one_image(
    session: requests.Session,
    api_base: str,
    *,
    personnel_id: int,
    image_name: str,
    image_bytes: bytes,
    make_primary: bool,
    timeout_sec: float,
    retries: int,
    retry_delay_sec: float,
) -> Tuple[bool, str]:
    url = f"{api_base.rstrip('/')}/face/personnel/{personnel_id}/images"
    response = _request_with_retry(
        session,
        "POST",
        url,
        timeout_sec=timeout_sec,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
        data={
            "pose_label": "front",
            "make_primary": "true" if make_primary else "false",
            "allow_conflict": "true",
        },
        files={"file": (image_name, io.BytesIO(image_bytes), "image/jpeg")},
    )
    if response.ok:
        return True, ""
    try:
        payload = response.json()
        detail = str(payload.get("detail") or payload.get("message") or "")
    except Exception:
        detail = response.text[:240]
    return False, detail or f"HTTP {response.status_code}"


def _recognize_probe_bytes(
    session: requests.Session,
    api_base: str,
    *,
    image_name: str,
    image_bytes: bytes,
    camera_id: int,
    timeout_sec: float,
    retries: int,
    retry_delay_sec: float,
) -> Tuple[bool, dict]:
    url = f"{api_base.rstrip('/')}/face/recognize"
    response = _request_with_retry(
        session,
        "POST",
        url,
        timeout_sec=timeout_sec,
        retries=retries,
        retry_delay_sec=retry_delay_sec,
        data={"camera_id": str(camera_id)},
        files={"file": (image_name, io.BytesIO(image_bytes), "application/octet-stream")},
    )
    if not response.ok:
        return False, {"status_code": response.status_code, "error": response.text[:240]}
    payload = response.json() if response.content else {}
    return True, payload if isinstance(payload, dict) else {}


def _iter_id_folders(dataset_root: Path) -> Iterable[Tuple[Path, int]]:
    for child in sorted(dataset_root.iterdir()):
        if not child.is_dir():
            continue
        match = PERSON_RE.search(child.name)
        if not match:
            continue
        yield child, int(match.group(1))


def main() -> int:
    args = _parse_args()
    dataset_root = Path(args.dataset_root).resolve()
    if not dataset_root.exists():
        raise SystemExit(f"Dataset root not found: {dataset_root}")

    id_folders = list(_iter_id_folders(dataset_root))
    if not id_folders:
        raise SystemExit(f"No person_XXX folders found under: {dataset_root}")

    session = requests.Session()
    token = _login(
        session,
        args.api_base,
        args.username,
        args.password,
        timeout_sec=float(args.timeout_sec),
        retries=int(args.request_retries),
        retry_delay_sec=float(args.request_retry_delay_sec),
    )
    session.headers.update({"Authorization": f"Bearer {token}"})

    personnel_rows = _list_personnel(
        session,
        args.api_base,
        timeout_sec=float(args.timeout_sec),
        retries=int(args.request_retries),
        retry_delay_sec=float(args.request_retry_delay_sec),
    )
    existing_by_name: Dict[str, dict] = {}
    for row in personnel_rows:
        key = str(row.get("full_name") or "").strip().lower()
        if key:
            existing_by_name[key] = row

    identity_maps: List[IdentityMap] = []
    created_count = 0
    reused_count = 0

    for _, idx in id_folders:
        before = len(existing_by_name)
        identity = _ensure_personnel_for_index(
            session,
            args.api_base,
            person_index=idx,
            existing_by_name=existing_by_name,
            timeout_sec=float(args.timeout_sec),
            retries=int(args.request_retries),
            retry_delay_sec=float(args.request_retry_delay_sec),
        )
        after = len(existing_by_name)
        if after > before:
            created_count += 1
        else:
            reused_count += 1
        identity_maps.append(identity)

    enroll_ok = 0
    enroll_fail = 0
    enroll_errors: List[dict] = []
    per_person_image_count: Dict[int, int] = {}

    for folder, idx in id_folders:
        identity = next(item for item in identity_maps if item.person_index == idx)
        images = sorted(
            p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        )
        if not images:
            per_person_image_count[identity.personnel_id] = 0
            enroll_errors.append(
                {"folder": folder.name, "personnel_id": identity.personnel_id, "error": "no_images"}
            )
            continue

        existing_images = _list_person_images(
            session,
            args.api_base,
            identity.personnel_id,
            timeout_sec=float(args.timeout_sec),
            retries=int(args.request_retries),
            retry_delay_sec=float(args.request_retry_delay_sec),
        )
        current_count = len(existing_images)
        target = max(1, int(args.min_images_per_identity))
        missing = max(0, target - current_count)
        per_person_image_count[identity.personnel_id] = current_count

        if missing <= 0:
            continue

        for src in images:
            if missing <= 0:
                break
            raw = src.read_bytes()
            frame = _decode_bgr(raw)
            candidate_variants: List[Tuple[str, bytes]] = []

            if frame is not None:
                bboxes = _detect_face_bboxes(
                    session,
                    args.api_base,
                    image_name=src.name,
                    image_bytes=raw,
                    camera_id=int(args.camera_id),
                    timeout_sec=float(args.timeout_sec),
                    retries=int(args.request_retries),
                    retry_delay_sec=float(args.request_retry_delay_sec),
                )
                for face_idx, bbox in enumerate(bboxes[:4], start=1):
                    face_crop = _crop_face(frame, bbox)
                    for variant_label, variant_bytes in _encode_variants_from_frame(face_crop):
                        candidate_variants.append((f"f{face_idx}_{variant_label}", variant_bytes))
                for variant_label, variant_bytes in _encode_variants_from_frame(frame):
                    candidate_variants.append((f"full_{variant_label}", variant_bytes))

            if not candidate_variants:
                candidate_variants = [("full_front", raw)]

            for variant_idx, (variant_label, variant_bytes) in enumerate(candidate_variants, start=1):
                if missing <= 0:
                    break
                ok, error_text = _enroll_one_image(
                    session,
                    args.api_base,
                    personnel_id=identity.personnel_id,
                    image_name=f"{src.stem}_{variant_label}_{variant_idx}.jpg",
                    image_bytes=variant_bytes,
                    make_primary=(current_count == 0 and per_person_image_count.get(identity.personnel_id, 0) == 0),
                    timeout_sec=float(args.timeout_sec),
                    retries=int(args.request_retries),
                    retry_delay_sec=float(args.request_retry_delay_sec),
                )
                if ok:
                    enroll_ok += 1
                    per_person_image_count[identity.personnel_id] = per_person_image_count.get(identity.personnel_id, 0) + 1
                    missing -= 1
                else:
                    enroll_fail += 1
                    enroll_errors.append(
                        {
                            "folder": folder.name,
                            "personnel_id": identity.personnel_id,
                            "source_image": src.name,
                            "variant": variant_label,
                            "error": error_text,
                        }
                    )

    eval_rows: List[dict] = []
    for folder, idx in id_folders:
        identity = next(item for item in identity_maps if item.person_index == idx)
        images = sorted(
            p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        )
        if not images:
            eval_rows.append(
                {
                    "folder": folder.name,
                    "personnel_id": identity.personnel_id,
                    "ok": False,
                    "error": "no_images",
                }
            )
            continue

        probe_raw = images[0].read_bytes()
        probe_frame = _decode_bgr(probe_raw)
        probe_name = images[0].name
        if probe_frame is not None:
            probe_bboxes = _detect_face_bboxes(
                session,
                args.api_base,
                image_name=images[0].name,
                image_bytes=probe_raw,
                camera_id=int(args.camera_id),
                timeout_sec=float(args.timeout_sec),
                retries=int(args.request_retries),
                retry_delay_sec=float(args.request_retry_delay_sec),
            )
            if probe_bboxes:
                best_crop = _crop_face(probe_frame, probe_bboxes[0])
                encoded_crop = _encode_bgr_jpg(best_crop)
                if encoded_crop:
                    probe_raw = encoded_crop
                    probe_name = f"{images[0].stem}_crop.jpg"

        ok, payload = _recognize_probe_bytes(
            session,
            args.api_base,
            image_name=probe_name,
            image_bytes=probe_raw,
            camera_id=int(args.camera_id),
            timeout_sec=float(args.timeout_sec),
            retries=int(args.request_retries),
            retry_delay_sec=float(args.request_retry_delay_sec),
        )
        if not ok:
            eval_rows.append(
                {
                    "folder": folder.name,
                    "personnel_id": identity.personnel_id,
                    "ok": False,
                    **payload,
                }
            )
            continue

        top_matches = payload.get("top_matches") if isinstance(payload.get("top_matches"), list) else []
        top_ids = [
            int(item.get("personnel_id"))
            for item in top_matches
            if isinstance(item, dict) and item.get("personnel_id") is not None
        ]
        top1 = top_ids[0] if top_ids else None
        eval_rows.append(
            {
                "folder": folder.name,
                "personnel_id": identity.personnel_id,
                "ok": True,
                "status": payload.get("status"),
                "recognized": str(payload.get("status") or "").lower() == "recognized",
                "top1_personnel_id": top1,
                "top1_match": top1 == identity.personnel_id,
                "top5_hit": identity.personnel_id in top_ids[:5],
                "confidence": payload.get("confidence"),
            }
        )

    eval_ok = [row for row in eval_rows if row.get("ok")]
    top1_match_count = sum(1 for row in eval_ok if row.get("top1_match"))
    top5_hit_count = sum(1 for row in eval_ok if row.get("top5_hit"))
    recognized_count = sum(1 for row in eval_ok if row.get("recognized"))

    summary = {
        "dataset_root": str(dataset_root),
        "identities_total": len(id_folders),
        "personnel_created": created_count,
        "personnel_reused": reused_count,
        "min_images_target": int(args.min_images_per_identity),
        "enroll_success_count": enroll_ok,
        "enroll_fail_count": enroll_fail,
        "dataset_personnel_with_images": sum(1 for _, count in per_person_image_count.items() if count > 0),
        "dataset_total_images_after_enroll": sum(per_person_image_count.values()),
        "evaluation_total": len(eval_rows),
        "evaluation_ok": len(eval_ok),
        "evaluation_fail": len(eval_rows) - len(eval_ok),
        "recognized_count": recognized_count,
        "top1_match_count": top1_match_count,
        "top5_hit_count": top5_hit_count,
        "top1_accuracy": round(top1_match_count / max(1, len(eval_ok)), 4),
        "top5_hit_rate": round(top5_hit_count / max(1, len(eval_ok)), 4),
    }

    report = {
        "summary": summary,
        "enroll_errors": enroll_errors,
        "evaluation_rows": eval_rows,
    }

    output_json = Path(args.output_json).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"report_json={output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
