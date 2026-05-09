from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional


class OcrStabilizerModule:
    """Weighted multi-frame OCR stabilizer keyed by camera and track."""

    _state_lock = Lock()
    _state_by_key: Dict[str, List[Dict[str, Any]]] = {}

    def __init__(
        self,
        *,
        window_sec: float,
        max_samples: int,
        decay_sec: float,
        min_samples: int,
        min_stability: float,
        min_margin: float,
    ):
        self.window_sec = max(0.1, float(window_sec))
        self.max_samples = max(2, int(max_samples))
        self.decay_sec = max(0.05, float(decay_sec))
        self.min_samples = max(1, int(min_samples))
        self.min_stability = max(0.0, min(1.0, float(min_stability)))
        self.min_margin = max(0.0, float(min_margin))

    def update(
        self,
        *,
        camera_id: int,
        track_id: Optional[int],
        compact_text: str,
        normalized_text: str,
        raw_text: str,
        confidence: float,
    ) -> Optional[Dict[str, Any]]:
        candidate = self._candidate_key(compact_text=compact_text, normalized_text=normalized_text, raw_text=raw_text)
        if not candidate:
            return None

        now = datetime.now(timezone.utc).timestamp()
        key = self._stream_key(camera_id=camera_id, track_id=track_id)
        entry = {
            "ts": now,
            "candidate": candidate,
            "raw": str(raw_text or "").strip(),
            "confidence": float(max(0.0, min(1.0, confidence))),
        }

        with self._state_lock:
            rows = self._state_by_key.get(key, [])
            rows = [row for row in rows if (now - float(row.get("ts", 0.0))) <= self.window_sec]
            rows.append(entry)
            if len(rows) > self.max_samples:
                rows = rows[-self.max_samples :]
            self._state_by_key[key] = rows

            grouped: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                token = str(row.get("candidate", "")).strip().upper()
                if not token:
                    continue
                conf = float(row.get("confidence", 0.0))
                age = max(0.0, now - float(row.get("ts", now)))
                recency_weight = math.exp(-(age / self.decay_sec))
                quality_weight = self._quality_weight(token)
                weight = max(0.01, conf) * recency_weight * quality_weight

                bucket = grouped.setdefault(
                    token,
                    {
                        "weight": 0.0,
                        "weighted_conf_sum": 0.0,
                        "sample_count": 0,
                        "best_conf": 0.0,
                        "raw": "",
                        "last_ts": 0.0,
                    },
                )
                bucket["weight"] += weight
                bucket["weighted_conf_sum"] += (weight * conf)
                bucket["sample_count"] += 1
                if conf >= float(bucket["best_conf"]):
                    bucket["best_conf"] = conf
                    bucket["raw"] = str(row.get("raw", "")).strip()
                bucket["last_ts"] = max(float(bucket["last_ts"]), float(row.get("ts", 0.0)))

            if not grouped:
                return None

            ordered = sorted(
                grouped.items(),
                key=lambda kv: (
                    float(kv[1]["weight"]),
                    int(kv[1]["sample_count"]),
                    float(kv[1]["best_conf"]),
                    len(str(kv[0])),
                ),
                reverse=True,
            )
            winner_key, winner = ordered[0]
            runner_weight = float(ordered[1][1]["weight"]) if len(ordered) > 1 else 0.0
            winner_weight = float(winner["weight"])
            total_weight = float(sum(float(meta["weight"]) for _k, meta in ordered))
            stability_ratio = (winner_weight / total_weight) if total_weight > 0 else 0.0
            margin = winner_weight - runner_weight

            weighted_conf = float(winner["weighted_conf_sum"]) / max(1e-6, winner_weight)
            winner_conf = float(max(float(winner["best_conf"]), weighted_conf))

            enough_samples = int(len(rows)) >= int(self.min_samples)
            stable_winner = stability_ratio >= self.min_stability and margin >= self.min_margin
            high_conf_override = winner_conf >= 0.92 and int(winner["sample_count"]) >= 1
            applied = bool(enough_samples and (stable_winner or high_conf_override))

            return {
                "applied": applied,
                "raw_text": str(winner.get("raw", "")).strip() or str(raw_text or "").strip(),
                "confidence": float(max(0.0, min(1.0, winner_conf))),
                "aggregate_size": int(len(rows)),
                "winner_compact": winner_key,
                "winner_weight": round(winner_weight, 4),
                "runner_weight": round(runner_weight, 4),
                "stability_ratio": round(float(stability_ratio), 4),
                "margin": round(float(margin), 4),
                "winner_samples": int(winner["sample_count"]),
                "stream_key": key,
            }

    def _stream_key(self, *, camera_id: int, track_id: Optional[int]) -> str:
        track_token = str(int(track_id)) if track_id is not None and int(track_id) > 0 else "na"
        return f"{int(camera_id)}:{track_token}"

    def _candidate_key(self, *, compact_text: str, normalized_text: str, raw_text: str) -> str:
        for candidate in (compact_text, normalized_text, raw_text):
            token = self._canonicalize(candidate)
            if token:
                return token
        return ""

    def _canonicalize(self, text: str) -> str:
        return re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", str(text or "").strip().upper())

    def _quality_weight(self, token: str) -> float:
        digits = sum(1 for ch in token if ch.isdigit())
        letters = sum(1 for ch in token if ch.isalpha())

        weight = 1.0
        if len(token) >= 5:
            weight += 0.06
        if digits >= 4:
            weight += 0.10
        if re.fullmatch(r"\d{3,8}", token):
            weight += 0.10
        if letters >= 1:
            weight += 0.03
        return float(max(0.8, min(1.35, weight)))
