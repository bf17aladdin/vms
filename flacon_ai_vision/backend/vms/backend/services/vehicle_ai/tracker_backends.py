from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any, Dict, List, Optional, Protocol

from .vehicle_detector import VehicleDetection


class VehicleTrackerBackend(Protocol):
    name: str

    def assign(
        self,
        *,
        camera_id: int,
        detections: List[VehicleDetection],
        reference_time: datetime,
    ) -> List[Optional[int]]:
        ...


def _bbox_to_dict(bbox: tuple[int, int, int, int]) -> Dict[str, int]:
    x, y, w, h = bbox
    return {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}


def _bbox_center(bbox: Dict[str, Any]) -> tuple[float, float]:
    x = float(bbox.get("x", 0))
    y = float(bbox.get("y", 0))
    w = float(bbox.get("w", 0))
    h = float(bbox.get("h", 0))
    return (x + (w / 2.0), y + (h / 2.0))


def _bbox_diag(bbox: Dict[str, Any]) -> float:
    w = max(0.0, float(bbox.get("w", 0)))
    h = max(0.0, float(bbox.get("h", 0)))
    return (w * w + h * h) ** 0.5


def _bbox_iou_dict(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ax1 = float(a.get("x", 0))
    ay1 = float(a.get("y", 0))
    ax2 = ax1 + max(0.0, float(a.get("w", 0)))
    ay2 = ay1 + max(0.0, float(a.get("h", 0)))

    bx1 = float(b.get("x", 0))
    by1 = float(b.get("y", 0))
    bx2 = bx1 + max(0.0, float(b.get("w", 0)))
    by2 = by1 + max(0.0, float(b.get("h", 0)))

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = max(0.0, (ax2 - ax1)) * max(0.0, (ay2 - ay1))
    area_b = max(0.0, (bx2 - bx1)) * max(0.0, (by2 - by1))
    union = area_a + area_b - inter_area
    if union <= 0.0:
        return 0.0
    return float(max(0.0, min(1.0, inter_area / union)))


class IouTrackerBackend:
    """Lightweight IoU + center-distance tracker."""

    name = "iou"
    _tracking_lock = Lock()
    _track_state_by_camera: Dict[int, Dict[int, Dict[str, Any]]] = {}
    _next_track_id_by_camera: Dict[int, int] = {}

    def __init__(
        self,
        *,
        max_age_sec: float,
        iou_threshold: float,
        center_distance_ratio: float,
    ):
        self.max_age_sec = max(0.1, float(max_age_sec))
        self.iou_threshold = max(0.0, min(1.0, float(iou_threshold)))
        self.center_distance_ratio = max(0.1, float(center_distance_ratio))

    def assign(
        self,
        *,
        camera_id: int,
        detections: List[VehicleDetection],
        reference_time: datetime,
    ) -> List[Optional[int]]:
        if not detections:
            return []

        now_ts = float(reference_time.timestamp())
        assigned_track_ids: List[Optional[int]] = []
        with self._tracking_lock:
            tracks = self._track_state_by_camera.setdefault(int(camera_id), {})
            expired_ids = [
                tid
                for tid, state in tracks.items()
                if (now_ts - float(state.get("last_seen_ts", 0.0))) > self.max_age_sec
            ]
            for tid in expired_ids:
                tracks.pop(tid, None)

            unmatched_track_ids = set(tracks.keys())
            for detection in detections:
                bbox = _bbox_to_dict(detection.bbox)
                best_track_id: Optional[int] = None
                best_score = float("-inf")
                bbox_diag = max(1.0, _bbox_diag(bbox))
                bbox_center = _bbox_center(bbox)

                for candidate_track_id in list(unmatched_track_ids):
                    state = tracks.get(candidate_track_id)
                    if state is None:
                        continue
                    previous_bbox = state.get("bbox") or {}
                    iou = _bbox_iou_dict(previous_bbox, bbox)
                    prev_diag = max(1.0, _bbox_diag(previous_bbox))
                    prev_center = _bbox_center(previous_bbox)
                    center_distance = (
                        (bbox_center[0] - prev_center[0]) ** 2
                        + (bbox_center[1] - prev_center[1]) ** 2
                    ) ** 0.5
                    distance_ratio = center_distance / max(bbox_diag, prev_diag)
                    if iou < self.iou_threshold and distance_ratio > self.center_distance_ratio:
                        continue
                    score = iou - (0.15 * distance_ratio)
                    if score > best_score:
                        best_score = score
                        best_track_id = int(candidate_track_id)

                if best_track_id is None:
                    next_track_id = self._next_track_id_by_camera.get(int(camera_id), 0) + 1
                    self._next_track_id_by_camera[int(camera_id)] = next_track_id
                    best_track_id = int(next_track_id)
                else:
                    unmatched_track_ids.discard(best_track_id)

                previous_state = tracks.get(best_track_id, {})
                previous_state["bbox"] = bbox
                previous_state["cx"], previous_state["cy"] = _bbox_center(bbox)
                previous_state["last_seen_ts"] = now_ts
                tracks[best_track_id] = previous_state
                assigned_track_ids.append(best_track_id)

            self._track_state_by_camera[int(camera_id)] = tracks
        return assigned_track_ids


class SortTrackerBackend:
    """SORT-like tracker with constant-velocity prediction and greedy assignment."""

    name = "sort"
    _tracking_lock = Lock()
    _track_state_by_camera: Dict[int, Dict[int, Dict[str, Any]]] = {}
    _next_track_id_by_camera: Dict[int, int] = {}

    def __init__(
        self,
        *,
        max_age_sec: float,
        match_iou: float,
        match_distance_ratio: float,
    ):
        self.max_age_sec = max(0.1, float(max_age_sec))
        self.match_iou = max(0.0, min(1.0, float(match_iou)))
        self.match_distance_ratio = max(0.1, float(match_distance_ratio))

    def assign(
        self,
        *,
        camera_id: int,
        detections: List[VehicleDetection],
        reference_time: datetime,
    ) -> List[Optional[int]]:
        if not detections:
            return []

        now_ts = float(reference_time.timestamp())
        det_bboxes = [_bbox_to_dict(det.bbox) for det in detections]
        assigned: List[Optional[int]] = [None for _ in detections]

        with self._tracking_lock:
            tracks = self._track_state_by_camera.setdefault(int(camera_id), {})
            expired_ids = [
                tid
                for tid, state in tracks.items()
                if (now_ts - float(state.get("last_seen_ts", 0.0))) > self.max_age_sec
            ]
            for tid in expired_ids:
                tracks.pop(tid, None)

            candidate_pairs: List[tuple[float, int, int]] = []
            for det_idx, det_bbox in enumerate(det_bboxes):
                det_center = _bbox_center(det_bbox)
                det_diag = max(1.0, _bbox_diag(det_bbox))
                for track_id, state in tracks.items():
                    pred_bbox = self._predict_bbox(state=state, now_ts=now_ts)
                    pred_center = _bbox_center(pred_bbox)
                    pred_diag = max(1.0, _bbox_diag(pred_bbox))
                    iou = _bbox_iou_dict(pred_bbox, det_bbox)
                    center_distance = (
                        (det_center[0] - pred_center[0]) ** 2
                        + (det_center[1] - pred_center[1]) ** 2
                    ) ** 0.5
                    distance_ratio = center_distance / max(det_diag, pred_diag)
                    if iou < self.match_iou and distance_ratio > self.match_distance_ratio:
                        continue
                    score = (0.70 * iou) + (0.30 * max(0.0, 1.0 - min(2.0, distance_ratio)))
                    candidate_pairs.append((float(score), int(det_idx), int(track_id)))

            candidate_pairs.sort(key=lambda row: row[0], reverse=True)
            used_detections: set[int] = set()
            used_tracks: set[int] = set()

            for _score, det_idx, track_id in candidate_pairs:
                if det_idx in used_detections or track_id in used_tracks:
                    continue
                self._update_track_state(
                    state=tracks[track_id],
                    bbox=det_bboxes[det_idx],
                    now_ts=now_ts,
                )
                assigned[det_idx] = int(track_id)
                used_detections.add(det_idx)
                used_tracks.add(track_id)

            for det_idx, det_bbox in enumerate(det_bboxes):
                if assigned[det_idx] is not None:
                    continue
                next_track_id = self._next_track_id_by_camera.get(int(camera_id), 0) + 1
                self._next_track_id_by_camera[int(camera_id)] = next_track_id
                tracks[int(next_track_id)] = self._new_track_state(bbox=det_bbox, now_ts=now_ts)
                assigned[det_idx] = int(next_track_id)

            self._track_state_by_camera[int(camera_id)] = tracks

        return assigned

    def _new_track_state(self, *, bbox: Dict[str, int], now_ts: float) -> Dict[str, Any]:
        cx, cy = _bbox_center(bbox)
        return {
            "bbox": dict(bbox),
            "cx": float(cx),
            "cy": float(cy),
            "vx": 0.0,
            "vy": 0.0,
            "hits": 1,
            "last_seen_ts": float(now_ts),
        }

    def _update_track_state(self, *, state: Dict[str, Any], bbox: Dict[str, int], now_ts: float) -> None:
        prev_cx = float(state.get("cx", 0.0))
        prev_cy = float(state.get("cy", 0.0))
        prev_vx = float(state.get("vx", 0.0))
        prev_vy = float(state.get("vy", 0.0))
        prev_ts = float(state.get("last_seen_ts", now_ts))
        dt = max(0.05, now_ts - prev_ts)

        cx, cy = _bbox_center(bbox)
        obs_vx = (cx - prev_cx) / dt
        obs_vy = (cy - prev_cy) / dt
        state["vx"] = (0.60 * obs_vx) + (0.40 * prev_vx)
        state["vy"] = (0.60 * obs_vy) + (0.40 * prev_vy)
        state["cx"] = float(cx)
        state["cy"] = float(cy)
        state["bbox"] = dict(bbox)
        state["hits"] = int(state.get("hits", 0)) + 1
        state["last_seen_ts"] = float(now_ts)

    def _predict_bbox(self, *, state: Dict[str, Any], now_ts: float) -> Dict[str, float]:
        bbox = state.get("bbox") or {}
        cx = float(state.get("cx", 0.0))
        cy = float(state.get("cy", 0.0))
        vx = float(state.get("vx", 0.0))
        vy = float(state.get("vy", 0.0))
        last_seen_ts = float(state.get("last_seen_ts", now_ts))
        dt = max(0.0, now_ts - last_seen_ts)

        pred_cx = cx + (vx * dt)
        pred_cy = cy + (vy * dt)
        w = max(1.0, float(bbox.get("w", 1.0)))
        h = max(1.0, float(bbox.get("h", 1.0)))
        return {
            "x": pred_cx - (w / 2.0),
            "y": pred_cy - (h / 2.0),
            "w": w,
            "h": h,
        }


def create_tracker_backend(
    *,
    mode: str,
    max_age_sec: float,
    iou_threshold: float,
    center_distance_ratio: float,
    sort_match_iou: float,
    sort_match_distance_ratio: float,
) -> VehicleTrackerBackend:
    normalized = str(mode or "iou").strip().lower()
    if normalized == "sort":
        return SortTrackerBackend(
            max_age_sec=max_age_sec,
            match_iou=sort_match_iou,
            match_distance_ratio=sort_match_distance_ratio,
        )
    return IouTrackerBackend(
        max_age_sec=max_age_sec,
        iou_threshold=iou_threshold,
        center_distance_ratio=center_distance_ratio,
    )
