"""
Quick runtime check for AI GPU readiness (face + vehicle).

Usage:
  .\venv_ai\Scripts\python.exe scripts\verify_gpu_stack.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _safe_import(name: str):
    try:
        return __import__(name)
    except Exception:
        return None


def collect_report() -> Dict[str, Any]:
    report: Dict[str, Any] = {}

    torch = _safe_import("torch")
    if torch is None:
        report["torch"] = {"installed": False}
    else:
        cuda_available = False
        cuda_devices = 0
        try:
            cuda_available = bool(torch.cuda.is_available())
            cuda_devices = int(torch.cuda.device_count()) if cuda_available else 0
        except Exception:
            pass
        report["torch"] = {
            "installed": True,
            "cuda_available": cuda_available,
            "cuda_devices": cuda_devices,
        }

    ort = _safe_import("onnxruntime")
    if ort is None:
        report["onnxruntime"] = {"installed": False}
    else:
        providers = []
        try:
            providers = [str(p) for p in ort.get_available_providers()]
        except Exception:
            pass
        report["onnxruntime"] = {
            "installed": True,
            "providers": providers,
            "has_cuda_provider": "CUDAExecutionProvider" in providers,
        }

    try:
        from vms.backend.services.face_ai.face_detector import resolve_face_onnx_runtime

        providers, ctx_id, available = resolve_face_onnx_runtime()
        report["face_runtime"] = {
            "resolved_providers": providers or [],
            "ctx_id": int(ctx_id),
            "available_providers": available,
            "gpu_selected": any(str(p) != "CPUExecutionProvider" for p in (providers or [])),
        }
    except Exception as e:
        report["face_runtime"] = {"error": str(e)}

    try:
        from vms.backend.services.vehicle_ai.vehicle_detector import VehicleDetector

        vd = VehicleDetector()
        report["vehicle_runtime"] = {
            "backend": vd.backend,
            "predict_device": getattr(vd, "predict_device", "unknown"),
            "gpu_selected": str(getattr(vd, "predict_device", "cpu")).startswith("cuda"),
        }
    except Exception as e:
        report["vehicle_runtime"] = {"error": str(e)}

    try:
        from vms.backend.services.vehicle_ai.plate_reader import PlateReader

        pr = PlateReader()
        report["plate_ocr"] = {
            "backend": pr.backend,
            "easyocr_loaded": bool(getattr(pr, "reader", None) is not None),
            "tesseract_ready": bool(getattr(pr, "tesseract_ready", False)),
        }
    except Exception as e:
        report["plate_ocr"] = {"error": str(e)}

    gpu_ready = bool(
        report.get("torch", {}).get("cuda_available")
        and report.get("onnxruntime", {}).get("has_cuda_provider")
        and (
            report.get("face_runtime", {}).get("gpu_selected")
            or report.get("vehicle_runtime", {}).get("gpu_selected")
        )
    )
    report["summary"] = {
        "gpu_ready": gpu_ready,
        "verdict": "GPU_READY" if gpu_ready else "CPU_ONLY_OR_PARTIAL",
    }
    return report


if __name__ == "__main__":
    print(json.dumps(collect_report(), indent=2, ensure_ascii=False))
