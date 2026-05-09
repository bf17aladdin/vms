from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

try:
    from .lprnet_adapter import LPRNetAdapter
except Exception:
    LPRNetAdapter = None  # type: ignore[assignment]

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    cv2 = None
    _HAS_CV2 = False

try:
    import easyocr  # type: ignore

    _HAS_EASYOCR = True
except Exception:
    easyocr = None
    _HAS_EASYOCR = False

try:
    import pytesseract  # type: ignore

    _HAS_TESSERACT = True
except Exception:
    pytesseract = None
    _HAS_TESSERACT = False

_ARABIC_INDIC_DIGITS = str.maketrans("\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669", "0123456789")
_EXT_ARABIC_INDIC_DIGITS = str.maketrans("\u06F0\u06F1\u06F2\u06F3\u06F4\u06F5\u06F6\u06F7\u06F8\u06F9", "0123456789")
logger = logging.getLogger(__name__)


@dataclass
class PlateReadResult:
    raw_text: str
    confidence: float
    bbox: Optional[Tuple[int, int, int, int]]
    plate_crop: Optional[np.ndarray]
    source: str
    candidates: List[Dict[str, Any]]


class PlateReader:
    """Plate detector/reader with EasyOCR/Tesseract and optional LPRNet backend."""

    def __init__(self):
        self.ocr_backend_preference = self._resolve_backend_preference()
        self.ocr_conf_threshold = float(os.getenv("VEHICLE_OCR_MIN_CONF", "0.15"))
        self.min_plate_chars = max(3, int(os.getenv("VEHICLE_PLATE_MIN_CHARS", "4")))
        self.min_plate_digits = max(1, int(os.getenv("VEHICLE_PLATE_MIN_DIGITS", "2")))
        self.max_region_candidates = max(1, int(os.getenv("VEHICLE_PLATE_MAX_REGIONS", "2")))
        self.preprocess_resize_factor = max(1.0, float(os.getenv("VEHICLE_PLATE_RESIZE_FACTOR", "2.4")))
        self.max_ocr_input_side = max(320, int(os.getenv("VEHICLE_OCR_MAX_INPUT_SIDE", "960")))
        self.upscale_trigger_max_side = max(64, int(os.getenv("VEHICLE_OCR_UPSCALE_TRIGGER_MAX_SIDE", "380")))
        self.max_preprocess_variants = max(2, int(os.getenv("VEHICLE_OCR_MAX_VARIANTS", "4")))
        self.easyocr_allowlist = os.getenv(
            "VEHICLE_OCR_ALLOWLIST",
            "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZTN\u062a\u0648\u0646\u0633",
        )
        # Keep default small/robust to avoid blocking startup on heavy model downloads.
        # You can override with VEHICLE_OCR_LANGS=ar,en when Arabic OCR model is available.
        langs = os.getenv("VEHICLE_OCR_LANGS", "en")
        self.languages = [x.strip() for x in langs.split(",") if x.strip()]
        self.lprnet_auto_enabled = os.getenv("VEHICLE_LPRNET_ENABLE", "false").strip().lower() == "true"
        self.lprnet_max_variants = max(1, int(os.getenv("VEHICLE_LPRNET_MAX_VARIANTS", "4")))
        self.lprnet_reader = None
        self.reader = None
        self.tesseract_ready = False
        self._init_lprnet()
        self._init_easyocr()
        self._init_tesseract()

    @property
    def backend(self) -> str:
        if self.ocr_backend_preference == "lprnet" and self.lprnet_reader is not None:
            return "lprnet"
        if self.reader is not None:
            return "easyocr"
        if self.tesseract_ready:
            return "tesseract"
        if self.lprnet_reader is not None:
            return "lprnet"
        return "none"

    def _init_lprnet(self) -> None:
        if LPRNetAdapter is None:
            return
        if self.ocr_backend_preference == "lprnet" or (
            self.ocr_backend_preference == "auto" and self.lprnet_auto_enabled
        ):
            try:
                candidate = LPRNetAdapter()
                if getattr(candidate, "ready", False):
                    self.lprnet_reader = candidate
            except Exception as exc:
                logger.warning("LPRNet plate reader initialization failed: %s", exc)
                self.lprnet_reader = None

    def _init_easyocr(self) -> None:
        if self.ocr_backend_preference == "tesseract":
            return
        if not _HAS_EASYOCR:
            return
        if os.getenv("VEHICLE_DISABLE_EASYOCR", "false").lower() == "true":
            return
        try:
            use_gpu = os.getenv("VEHICLE_EASYOCR_GPU", "false").lower() == "true"
            download_enabled = os.getenv("VEHICLE_EASYOCR_DOWNLOAD_ENABLED", "true").lower() == "true"
            self.reader = easyocr.Reader(self.languages, gpu=use_gpu, download_enabled=download_enabled)
        except Exception as exc:
            logger.warning("EasyOCR initialization failed for languages %s: %s", self.languages, exc)
            self.reader = None
            # Arabic model in EasyOCR is only compatible with English.
            fallback_langs = self._resolve_easyocr_fallback_languages(self.languages)
            if fallback_langs:
                try:
                    use_gpu = os.getenv("VEHICLE_EASYOCR_GPU", "false").lower() == "true"
                    download_enabled = os.getenv("VEHICLE_EASYOCR_DOWNLOAD_ENABLED", "true").lower() == "true"
                    self.reader = easyocr.Reader(
                        fallback_langs,
                        gpu=use_gpu,
                        download_enabled=download_enabled,
                    )
                except Exception as fallback_exc:
                    logger.warning(
                        "EasyOCR fallback initialization failed for languages %s: %s",
                        fallback_langs,
                        fallback_exc,
                    )
                    self.reader = None

    def _resolve_easyocr_fallback_languages(self, langs: List[str]) -> Optional[List[str]]:
        norm = [str(x).strip().lower() for x in langs if str(x).strip()]
        if not norm:
            return ["en"]
        fallback = ["ar", "en"] if "ar" in norm else ["en"]
        if norm == fallback:
            if fallback != ["en"]:
                return ["en"]
            return None
        return fallback

    def _init_tesseract(self) -> None:
        if self.ocr_backend_preference == "easyocr":
            return
        if not _HAS_TESSERACT:
            self.tesseract_ready = False
            return
        candidates: List[str] = []
        env_cmd = os.getenv("TESSERACT_CMD", "").strip()
        if env_cmd:
            candidates.append(env_cmd)
        candidates.extend(
            [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
        )
        chosen = None
        for cmd in candidates:
            if cmd and Path(cmd).exists():
                chosen = cmd
                break
        if chosen:
            try:
                pytesseract.pytesseract.tesseract_cmd = chosen
            except Exception as exc:
                logger.debug("Unable to set Tesseract binary path %s: %s", chosen, exc)
        try:
            _ = pytesseract.get_tesseract_version()
            self.tesseract_ready = True
        except Exception as exc:
            logger.debug("Tesseract version probe failed: %s", exc)
            self.tesseract_ready = False

    def read_plate(
        self,
        frame_bgr: np.ndarray,
        vehicle_bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> Optional[PlateReadResult]:
        regions = self._extract_plate_regions(frame_bgr, vehicle_bbox=vehicle_bbox)
        if not regions:
            return None

        global_best: Optional[Dict[str, Any]] = None
        global_candidates: List[Dict[str, Any]] = []

        for plate_crop, plate_bbox in regions:
            if plate_crop is None or plate_crop.size == 0:
                continue
            variants = self._build_ocr_variants(plate_crop)
            candidates: List[Dict[str, Any]] = []
            if self.ocr_backend_preference == "lprnet":
                if self.lprnet_reader is not None:
                    candidates.extend(self._read_with_lprnet(variants))
                if not candidates and self.reader is not None:
                    candidates.extend(self._read_with_easyocr(variants))
                if not candidates and self.tesseract_ready:
                    candidates.extend(self._read_with_tesseract(variants))
            else:
                if self.reader is not None and self.ocr_backend_preference in {"auto", "easyocr"}:
                    candidates.extend(self._read_with_easyocr(variants))
                if self.tesseract_ready and self.ocr_backend_preference in {"auto", "tesseract"}:
                    candidates.extend(self._read_with_tesseract(variants))
                if self.lprnet_reader is not None and self.ocr_backend_preference == "auto":
                    best_before_lprnet = self._select_best(candidates)
                    needs_lprnet_fallback = best_before_lprnet is None or float(
                        best_before_lprnet.get("confidence", 0.0)
                    ) < max(0.05, self.ocr_conf_threshold)
                    if needs_lprnet_fallback:
                        candidates.extend(self._read_with_lprnet(variants))

            for c in candidates:
                c["bbox"] = plate_bbox
            global_candidates.extend(candidates)

            best = self._select_best(candidates)
            if best is None:
                continue
            if global_best is None or float(best.get("score", 0.0)) > float(global_best.get("score", 0.0)):
                global_best = best

        if global_best is None:
            return None

        best_bbox = global_best.get("bbox")
        best_crop = None
        if best_bbox is not None:
            bx, by, bw, bh = best_bbox
            h, w = frame_bgr.shape[:2]
            x1 = max(0, int(bx))
            y1 = max(0, int(by))
            x2 = min(w, int(bx + bw))
            y2 = min(h, int(by + bh))
            if x2 > x1 and y2 > y1:
                best_crop = frame_bgr[y1:y2, x1:x2]

        return PlateReadResult(
            raw_text=str(global_best.get("text") or "").strip(),
            confidence=float(global_best.get("confidence", 0.0)),
            bbox=best_bbox,
            plate_crop=best_crop,
            source=str(global_best.get("source") or "ocr"),
            candidates=sorted(global_candidates, key=lambda x: float(x.get("score", 0.0)), reverse=True)[:10],
        )

    def _extract_plate_regions(
        self,
        frame_bgr: np.ndarray,
        vehicle_bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
        out: List[Tuple[np.ndarray, Tuple[int, int, int, int]]] = []
        if frame_bgr is None or frame_bgr.size == 0:
            return out

        h, w = frame_bgr.shape[:2]
        if vehicle_bbox is None:
            # Fallback: whole frame as search area.
            roi = frame_bgr
            x0, y0 = 0, 0
        else:
            x, y, bw, bh = vehicle_bbox
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w, x + bw)
            y2 = min(h, y + bh)
            roi = frame_bgr[y1:y2, x1:x2]
            x0, y0 = x1, y1

        if roi is None or roi.size == 0:
            return out

        rh, rw = roi.shape[:2]
        # Multi-window heuristic for front/rear plate variation.
        # Keep center-first to support close frontal shots where plate sits mid-frame.
        windows = [
            (0.15, 0.85, 0.28, 0.72),  # centered primary
            (0.18, 0.82, 0.52, 0.95),  # classic lower-middle
            (0.22, 0.78, 0.58, 0.96),  # tighter lower center
            (0.10, 0.90, 0.18, 0.62),  # wider mid-height
            (0.20, 0.80, 0.42, 0.86),  # fallback slightly lower
            (0.00, 1.00, 0.40, 0.98),  # broad fallback
        ]
        for wx1, wx2, wy1, wy2 in windows[: self.max_region_candidates]:
            px1 = int(rw * wx1)
            px2 = int(rw * wx2)
            py1 = int(rh * wy1)
            py2 = int(rh * wy2)
            if px2 <= px1 or py2 <= py1:
                continue
            plate = roi[py1:py2, px1:px2]
            if plate is None or plate.size == 0:
                continue
            bbox = (x0 + px1, y0 + py1, max(0, px2 - px1), max(0, py2 - py1))
            out.append((plate, bbox))

        if not out:
            out.append((roi, (x0, y0, rw, rh)))
        return out

    def _build_ocr_variants(self, plate_bgr: np.ndarray) -> List[np.ndarray]:
        variants: List[np.ndarray] = []
        if plate_bgr is None or plate_bgr.size == 0:
            return variants
        base = plate_bgr
        if _HAS_CV2:
            h, w = base.shape[:2]
            longest = max(int(h), int(w))
            # Cap OCR input size to keep endpoint latency bounded.
            if longest > self.max_ocr_input_side:
                scale = float(self.max_ocr_input_side) / float(max(1, longest))
                base = cv2.resize(base, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        variants.append(base)

        if not _HAS_CV2:
            return variants[: self.max_preprocess_variants]

        upscale_base = base
        if self.preprocess_resize_factor > 1.0 and max(upscale_base.shape[:2]) <= self.upscale_trigger_max_side:
            upscale_base = cv2.resize(
                base,
                None,
                fx=float(self.preprocess_resize_factor),
                fy=float(self.preprocess_resize_factor),
                interpolation=cv2.INTER_CUBIC,
            )
            variants.append(upscale_base)

        gray = cv2.cvtColor(upscale_base, cv2.COLOR_BGR2GRAY)
        variants.append(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))

        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        gray_eq = clahe.apply(gray)
        variants.append(cv2.cvtColor(gray_eq, cv2.COLOR_GRAY2BGR))

        # Two threshold families to handle light/dark backgrounds.
        thr_otsu = cv2.threshold(gray_eq, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        variants.append(cv2.cvtColor(thr_otsu, cv2.COLOR_GRAY2BGR))
        thr_inv = cv2.threshold(gray_eq, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        variants.append(cv2.cvtColor(thr_inv, cv2.COLOR_GRAY2BGR))
        thr_adapt = cv2.adaptiveThreshold(
            gray_eq,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            5,
        )
        variants.append(cv2.cvtColor(thr_adapt, cv2.COLOR_GRAY2BGR))

        # Simple de-dup by shape + byte hash to avoid redundant OCR calls.
        unique: List[np.ndarray] = []
        seen: set[str] = set()
        for img in variants:
            key = f"{img.shape}-{hash(bytes(img.tobytes()[:2048]))}"
            if key in seen:
                continue
            seen.add(key)
            unique.append(img)
        return unique[: self.max_preprocess_variants]

    def _read_with_easyocr(self, variants: List[np.ndarray]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if self.reader is None:
            return out
        for img in variants:
            raw_entries: List[Dict[str, Any]] = []
            try:
                results = self.reader.readtext(
                    img,
                    detail=1,
                    allowlist=self.easyocr_allowlist,
                )
            except Exception as exc:
                logger.debug("EasyOCR plate read failed on a preprocessing variant: %s", exc)
                continue

            for entry in results:
                try:
                    raw_bbox, text, conf = entry
                    text = self._normalize_ocr_text(text or "")
                    conf = float(conf)
                except Exception as exc:
                    logger.debug("Skipping malformed EasyOCR entry: %s", exc)
                    continue
                if not text:
                    continue
                x_center = self._bbox_x_center(raw_bbox, float(max(1, img.shape[1])))
                raw_entries.append({"text": text, "confidence": conf, "x_center": x_center})
                if conf < self.ocr_conf_threshold:
                    continue
                if not self._looks_like_plate(text):
                    continue
                out.append(
                    {
                        "text": text,
                        "confidence": conf,
                        "source": "easyocr",
                        "x_center": x_center,
                        "score": self._candidate_score(text, conf),
                    }
                )
            # Join split OCR tokens (e.g., "36" + "207" => "36 207").
            merged = self._merge_easyocr_tokens(raw_entries)
            if merged:
                out.append(merged)
        return out

    def _read_with_tesseract(self, variants: List[np.ndarray]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not self.tesseract_ready:
            return out
        for img in variants:
            ocr_img = img
            if _HAS_CV2:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                ocr_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            for psm in (7, 6, 11):
                try:
                    cfg = (
                        f"--oem 3 --psm {psm} "
                        "-c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                    )
                    text = pytesseract.image_to_string(ocr_img, config=cfg)
                    text = self._normalize_ocr_text(text or "")
                except Exception as exc:
                    logger.debug("Tesseract plate read failed for psm=%s: %s", psm, exc)
                    continue
                if not text or not self._looks_like_plate(text):
                    continue
                # Tesseract confidence is approximated; score function compensates with plate-likeness.
                conf = 0.28
                out.append(
                    {
                        "text": text,
                        "confidence": conf,
                        "source": f"tesseract_psm{psm}",
                        "score": self._candidate_score(text, conf),
                    }
                )
        return out

    def _read_with_lprnet(self, variants: List[np.ndarray]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if self.lprnet_reader is None:
            return out

        by_text: Dict[str, Dict[str, Any]] = {}
        for img in variants[: self.lprnet_max_variants]:
            try:
                decoded = self.lprnet_reader.decode(img)
            except Exception as exc:
                logger.debug("LPRNet decode failed on a preprocessing variant: %s", exc)
                decoded = None
            if decoded is None:
                continue

            text = self._normalize_ocr_text(decoded.text)
            conf = float(decoded.confidence)
            conf = max(0.0, min(1.0, conf))
            if not text:
                continue
            if conf < max(0.05, self.ocr_conf_threshold * 0.45):
                continue
            if not self._looks_like_plate(text):
                continue

            candidate = {
                "text": text,
                "confidence": conf,
                "source": "lprnet",
                "score": self._candidate_score(text, conf + 0.06),
            }
            prev = by_text.get(text)
            if prev is None or float(candidate["score"]) > float(prev.get("score", 0.0)):
                by_text[text] = candidate

        out.extend(by_text.values())
        return out

    def _select_best(self, candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not candidates:
            return None
        candidates = sorted(candidates, key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return candidates[0]

    def _normalize_ocr_text(self, text: str) -> str:
        stage = str(text or "").strip()
        if not stage:
            return ""
        stage = stage.translate(_ARABIC_INDIC_DIGITS).translate(_EXT_ARABIC_INDIC_DIGITS)
        stage = stage.upper()
        stage = re.sub(r"[^0-9A-Z\u0600-\u06FF]+", " ", stage)
        stage = re.sub(r"\s+", " ", stage).strip()
        return stage

    def _bbox_x_center(self, bbox: Any, width: float) -> float:
        try:
            xs = [float(p[0]) for p in bbox]
            return float((sum(xs) / max(1, len(xs))) / max(1.0, float(width)))
        except Exception:
            return 0.0

    def _merge_easyocr_tokens(self, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not rows:
            return None
        # Keep likely plate tokens and order by horizontal position.
        tokens = [r for r in rows if re.search(r"[0-9]", str(r.get("text", "")))]
        if len(tokens) < 2:
            return None
        tokens = sorted(tokens, key=lambda r: float(r.get("x_center", 0.0)))
        merged_text = " ".join(str(r.get("text", "")).strip() for r in tokens if str(r.get("text", "")).strip())
        merged_text = self._normalize_ocr_text(merged_text)
        if not merged_text or not self._looks_like_plate(merged_text):
            return None
        conf_values = [float(r.get("confidence", 0.0)) for r in tokens]
        conf = float(sum(conf_values) / max(1, len(conf_values)))
        x_centers = [float(r.get("x_center", 0.0)) for r in tokens]
        return {
            "text": merged_text,
            "confidence": conf,
            "source": "easyocr_merge",
            "x_center": (sum(x_centers) / max(1, len(x_centers))),
            "score": self._candidate_score(merged_text, conf),
        }

    def _candidate_score(self, text: str, confidence: float) -> float:
        cleaned = re.sub(r"[^0-9A-Z\u0600-\u06FF]+", "", (text or "").upper())
        digit_count = sum(1 for ch in cleaned if ch.isdigit())
        alpha_count = sum(1 for ch in cleaned if ch.isalpha())
        pattern_bonus = 0.0
        if re.fullmatch(r"\d{3,8}", cleaned):
            pattern_bonus += 0.18
        if re.search(r"(TUNIS|TN|\u062a\u0648\u0646\u0633)", (text or "").upper()):
            pattern_bonus += 0.12
        if digit_count >= 3:
            pattern_bonus += 0.08
        if alpha_count > 0 and digit_count > 0:
            pattern_bonus += 0.05
        return float(confidence) + pattern_bonus

    def _looks_like_plate(self, text: str) -> bool:
        cleaned = re.sub(r"[^0-9A-Za-z\u0600-\u06FF]+", "", (text or ""))
        if len(cleaned) < self.min_plate_chars:
            return False
        digit_count = sum(1 for ch in cleaned if ch.isdigit())
        if digit_count < self.min_plate_digits:
            return False
        return True

    def _resolve_backend_preference(self) -> str:
        raw = (
            os.getenv("OCR_BACKEND", "").strip().lower()
            or os.getenv("VEHICLE_OCR_BACKEND", "").strip().lower()
            or "auto"
        )
        if raw in {"auto", "easyocr", "tesseract", "lprnet"}:
            return raw
        return "auto"
