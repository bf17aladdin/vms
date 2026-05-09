# vms/__init__.py

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AI_ENGINE_ROOT = _REPO_ROOT / "ai-engine"

if _AI_ENGINE_ROOT.exists():
    ai_engine_path = str(_AI_ENGINE_ROOT)
    if ai_engine_path not in sys.path:
        sys.path.insert(0, ai_engine_path)
