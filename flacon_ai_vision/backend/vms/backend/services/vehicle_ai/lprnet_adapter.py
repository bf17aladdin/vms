from __future__ import annotations

import importlib
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

try:
    import cv2  # type: ignore

    _HAS_CV2 = True
except Exception:
    cv2 = None
    _HAS_CV2 = False

try:
    import torch  # type: ignore

    _HAS_TORCH = True
except Exception:
    torch = None
    _HAS_TORCH = False

logger = logging.getLogger(__name__)


@dataclass
class LPRNetDecodeResult:
    text: str
    confidence: float


class LPRNetAdapter:
    """
    Optional LPRNet loader/decoder inspired by car-number-detection.

    This adapter is intentionally defensive:
    - loads only if torch + model/factory are available
    - accepts multiple module/factory naming variants
    - keeps EasyOCR/Tesseract pipeline untouched when unavailable
    """

    def __init__(self):
        self.ready = False
        self.project_dir = self._resolve_path(os.getenv("VEHICLE_LPRNET_PROJECT_DIR", "").strip(), base=None)
        self.weights_path = self._resolve_path(
            os.getenv("VEHICLE_LPRNET_WEIGHTS", "").strip(),
            base=self.project_dir,
        )
        self.module_name = os.getenv("VEHICLE_LPRNET_MODULE", "").strip() or None
        self.factory_name = os.getenv("VEHICLE_LPRNET_FACTORY", "").strip() or None
        self.input_width = max(16, int(os.getenv("VEHICLE_LPRNET_INPUT_WIDTH", "94")))
        self.input_height = max(16, int(os.getenv("VEHICLE_LPRNET_INPUT_HEIGHT", "24")))
        self.max_chars = max(4, int(os.getenv("VEHICLE_LPRNET_MAX_CHARS", "14")))
        self.chars = self._load_chars()
        self.blank_index = self._resolve_blank_index(len(self.chars))
        self.device = self._resolve_device()
        self.model = None

        if not _HAS_TORCH or not self.chars:
            logger.debug(
                "LPRNet adapter disabled (torch_available=%s chars_loaded=%s)",
                _HAS_TORCH,
                bool(self.chars),
            )
            return

        if self.project_dir is not None and self.project_dir.exists():
            project_dir_str = str(self.project_dir)
            if project_dir_str not in sys.path:
                sys.path.insert(0, project_dir_str)

        self.model = self._load_model()
        if self.model is None:
            logger.debug("LPRNet adapter could not load a usable model")
            return
        self.ready = True

    def decode(self, plate_bgr: np.ndarray) -> Optional[LPRNetDecodeResult]:
        if not self.ready or self.model is None:
            return None
        tensor = self._preprocess(plate_bgr)
        if tensor is None:
            return None

        try:
            with torch.no_grad():
                logits = self.model(tensor)
        except Exception as exc:
            logger.debug("LPRNet forward pass failed: %s", exc)
            return None

        probs = self._to_probabilities(logits)
        if probs is None:
            return None

        try:
            conf_tensor, idx_tensor = probs.max(dim=1)
        except Exception as exc:
            logger.debug("LPRNet probability decoding failed: %s", exc)
            return None

        indices = [int(x) for x in idx_tensor.detach().cpu().tolist()]
        confidences = [float(x) for x in conf_tensor.detach().cpu().tolist()]
        text, confidence = self._ctc_decode(indices, confidences)
        if not text:
            return None
        return LPRNetDecodeResult(text=text, confidence=confidence)

    def _load_model(self):
        for module_name in self._candidate_modules():
            module = self._safe_import(module_name)
            if module is None:
                continue
            factory = self._resolve_factory(module)
            if factory is None:
                logger.debug("No LPRNet factory resolved in module %s", module_name)
                continue
            model = self._build_model(factory)
            if model is None:
                logger.debug("LPRNet factory %s did not build a usable model", getattr(factory, "__name__", factory))
                continue
            if self.weights_path is not None and self.weights_path.exists():
                if not self._load_weights(model, self.weights_path):
                    logger.debug("LPRNet weights failed to load from %s", self.weights_path)
                    continue
            try:
                model.eval()
                model.to(self.device)
            except Exception as exc:
                logger.debug("LPRNet model finalization failed on device %s: %s", self.device, exc)
                continue
            return model
        return None

    def _build_model(self, factory: Callable[..., Any]):
        kwargs_options = [
            {"class_num": len(self.chars)},
            {"num_classes": len(self.chars)},
            {"n_classes": len(self.chars)},
            {"nclass": len(self.chars)},
            {},
        ]
        for kwargs in kwargs_options:
            try:
                model = factory(**kwargs)
                if model is not None:
                    return model
            except TypeError:
                continue
            except Exception as exc:
                logger.debug(
                    "LPRNet factory %s failed with kwargs %s: %s",
                    getattr(factory, "__name__", factory),
                    kwargs,
                    exc,
                )
                return None
        return None

    def _load_weights(self, model: Any, weights_path: Path) -> bool:
        try:
            state = torch.load(str(weights_path), map_location=self.device)
        except Exception as exc:
            logger.debug("Unable to load LPRNet weights from %s: %s", weights_path, exc)
            return False

        if isinstance(state, dict):
            for key in ("state_dict", "model_state_dict", "model", "net"):
                nested = state.get(key)
                if isinstance(nested, dict):
                    state = nested
                    break
        if not isinstance(state, dict):
            return False

        load_candidates = [state]
        stripped = {}
        for key, value in state.items():
            k = str(key)
            if k.startswith("module."):
                k = k[len("module.") :]
            stripped[k] = value
        load_candidates.append(stripped)

        for candidate in load_candidates:
            try:
                model.load_state_dict(candidate, strict=False)
                return True
            except Exception as exc:
                logger.debug("LPRNet state_dict application failed: %s", exc)
                continue
        return False

    def _preprocess(self, plate_bgr: np.ndarray):
        if plate_bgr is None or plate_bgr.size == 0:
            return None

        img = plate_bgr
        if _HAS_CV2:
            try:
                img = cv2.resize(img, (self.input_width, self.input_height), interpolation=cv2.INTER_CUBIC)
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            except Exception as exc:
                logger.debug("LPRNet OpenCV preprocessing failed: %s", exc)
                return None
        else:
            try:
                img = np.asarray(img)
                img = img[:, :, ::-1]
            except Exception as exc:
                logger.debug("LPRNet NumPy preprocessing failed: %s", exc)
                return None

        arr = img.astype(np.float32)
        # LPRNet-style normalization used in several public implementations.
        arr = (arr - 127.5) * 0.0078125
        arr = np.transpose(arr, (2, 0, 1))
        try:
            tensor = torch.from_numpy(arr).unsqueeze(0).to(self.device)
        except Exception as exc:
            logger.debug("LPRNet tensor conversion failed: %s", exc)
            return None
        return tensor

    def _to_probabilities(self, logits: Any):
        tensor = logits
        if isinstance(tensor, (list, tuple)):
            if not tensor:
                return None
            tensor = tensor[0]
        if not torch.is_tensor(tensor):
            try:
                tensor = torch.as_tensor(tensor)
            except Exception as exc:
                logger.debug("LPRNet logits conversion to tensor failed: %s", exc)
                return None

        if tensor.dim() == 4:
            # Common shape variants: [B, C, T, 1] or [B, T, C, 1]
            tensor = tensor.squeeze(-1)
        if tensor.dim() == 3 and int(tensor.shape[0]) == 1:
            tensor = tensor[0]
        if tensor.dim() != 2:
            return None

        # We want [T, C] before softmax over classes.
        d0 = int(tensor.shape[0])
        d1 = int(tensor.shape[1])
        if d0 >= len(self.chars) and d1 < len(self.chars):
            tensor = tensor.transpose(0, 1)
        elif d0 >= len(self.chars) and d1 >= len(self.chars):
            # Pick orientation whose class dimension is closer to charset size.
            if abs(d0 - len(self.chars)) < abs(d1 - len(self.chars)):
                tensor = tensor.transpose(0, 1)

        if tensor.shape[1] <= 1:
            return None
        return torch.softmax(tensor, dim=1)

    def _ctc_decode(self, indices: list[int], confidences: list[float]) -> tuple[str, float]:
        out_chars: list[str] = []
        conf_values: list[float] = []
        prev = None

        for idx, conf in zip(indices, confidences):
            if idx == self.blank_index or idx < 0 or idx >= len(self.chars):
                prev = None
                continue
            if prev == idx:
                continue
            prev = idx
            ch = str(self.chars[idx]).strip()
            if not ch or ch in {"-", "_", "|"}:
                continue
            out_chars.append(ch)
            conf_values.append(max(0.0, min(1.0, float(conf))))
            if len(out_chars) >= self.max_chars:
                break

        text = "".join(out_chars).strip()
        text = re.sub(r"\s+", "", text)
        confidence = float(sum(conf_values) / max(1, len(conf_values))) if conf_values else 0.0
        return text, max(0.0, min(1.0, confidence))

    def _candidate_modules(self) -> list[str]:
        modules: list[str] = []
        if self.module_name:
            modules.append(self.module_name)
        modules.extend(
            [
                "lpr_net.model.lpr_net",
                "lpr_net.model.LPRNet",
                "lpr_net.model",
                "model.lpr_net",
                "LPRNet_Pytorch.model.LPRNet",
            ]
        )
        # Keep order while removing duplicates.
        seen: set[str] = set()
        ordered: list[str] = []
        for name in modules:
            key = str(name).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(key)
        return ordered

    def _resolve_factory(self, module: Any) -> Optional[Callable[..., Any]]:
        if self.factory_name:
            factory = getattr(module, self.factory_name, None)
            if callable(factory):
                return factory

        for name in ("LPRNet", "LPRNET", "build_lprnet", "get_model", "create_model"):
            factory = getattr(module, name, None)
            if callable(factory):
                return factory
        return None

    def _load_chars(self) -> list[str]:
        chars_file = self._resolve_path(os.getenv("VEHICLE_LPRNET_CHARS_FILE", "").strip(), base=self.project_dir)
        if chars_file is not None and chars_file.exists():
            try:
                text = chars_file.read_text(encoding="utf-8")
                parsed = self._parse_chars_text(text)
                if parsed:
                    return parsed
            except Exception as exc:
                logger.debug("Unable to read LPRNet chars file %s: %s", chars_file, exc)

        raw_chars = os.getenv("VEHICLE_LPRNET_CHARS", "").strip()
        if raw_chars:
            parsed = self._parse_chars_text(raw_chars)
            if parsed:
                return parsed

        return list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")

    def _parse_chars_text(self, raw: str) -> list[str]:
        value = str(raw or "").strip()
        if not value:
            return []
        if "," in value:
            parts = [part.strip() for part in value.split(",") if part.strip()]
        elif "\n" in value:
            parts = [part.strip() for part in value.splitlines() if part.strip()]
        else:
            parts = [ch for ch in value if ch.strip()]

        seen: set[str] = set()
        out: list[str] = []
        for token in parts:
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
        return out

    def _resolve_blank_index(self, charset_len: int) -> int:
        if charset_len <= 0:
            return 0
        raw = os.getenv("VEHICLE_LPRNET_BLANK_INDEX", "").strip()
        if raw:
            try:
                idx = int(raw)
                if 0 <= idx < charset_len:
                    return idx
            except Exception as exc:
                logger.debug("Invalid VEHICLE_LPRNET_BLANK_INDEX value %r: %s", raw, exc)
        return charset_len - 1

    def _resolve_device(self):
        if not _HAS_TORCH:
            return "cpu"
        requested = (
            os.getenv("VEHICLE_LPRNET_DEVICE", "").strip().lower()
            or os.getenv("AI_DEVICE", "").strip().lower()
            or "cpu"
        )
        if requested in {"", "auto"}:
            return "cuda:0" if torch.cuda.is_available() else "cpu"
        if requested == "cuda" and torch.cuda.is_available():
            return "cuda:0"
        if requested.startswith("cuda"):
            if torch.cuda.is_available():
                return requested
            return "cpu"
        return "cpu"

    def _safe_import(self, module_name: str):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            logger.debug("Unable to import LPRNet module %s: %s", module_name, exc)
            return None

    def _resolve_path(self, raw: str, base: Optional[Path]) -> Optional[Path]:
        value = str(raw or "").strip()
        if not value:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute() and base is not None:
            path = base / path
        elif not path.is_absolute():
            path = Path.cwd() / path
        return path
