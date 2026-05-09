#!/usr/bin/env python
"""Simple runtime supervisor with auto-restart for backend and frontend.

Ports are fixed by project policy:
- backend: 5003
- frontend: 3000
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).parent
PLATFORM_ROOT = ROOT / "falcon-ai-vision-platform"
BACKEND_DIR = PLATFORM_ROOT / "backend"
FRONTEND_DIR = PLATFORM_ROOT / "frontend"

BACKEND_CMD = [
    str(ROOT / "venv_ai" / "Scripts" / "python.exe"),
    "-m",
    "uvicorn",
    "vms.backend.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "5003",
]
FRONTEND_CMD = ["npm", "run", "dev", "--", "--port", "3000", "--strictPort"]


def start(name: str, cmd: list[str], cwd: Path) -> subprocess.Popen:
    print(f"[supervisor] starting {name}: {' '.join(cmd)}")
    return subprocess.Popen(cmd, cwd=str(cwd))


def main() -> int:
    restart_delay_sec = float(os.getenv("SUPERVISOR_RESTART_DELAY_SEC", "2.0"))
    max_restarts = int(os.getenv("SUPERVISOR_MAX_RESTARTS", "100"))

    processes = {
        "backend": {"cmd": BACKEND_CMD, "cwd": BACKEND_DIR, "proc": None, "restarts": 0},
        "frontend": {"cmd": FRONTEND_CMD, "cwd": FRONTEND_DIR, "proc": None, "restarts": 0},
    }

    should_stop = False

    def handle_stop(signum, frame):  # type: ignore[no-untyped-def]
        nonlocal should_stop
        should_stop = True
        print(f"[supervisor] signal={signum}, stopping...")

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    for name, meta in processes.items():
        meta["proc"] = start(name, meta["cmd"], meta["cwd"])

    try:
        while not should_stop:
            for name, meta in processes.items():
                proc: subprocess.Popen = meta["proc"]
                code = proc.poll()
                if code is None:
                    continue
                if should_stop:
                    continue
                meta["restarts"] += 1
                if meta["restarts"] > max_restarts:
                    print(f"[supervisor] {name} exceeded restart budget, giving up")
                    should_stop = True
                    break
                print(f"[supervisor] {name} exited with code {code}, restarting in {restart_delay_sec}s")
                time.sleep(max(0.5, restart_delay_sec))
                meta["proc"] = start(name, meta["cmd"], meta["cwd"])
            time.sleep(1.0)
    finally:
        for name, meta in processes.items():
            proc = meta.get("proc")
            if proc and proc.poll() is None:
                print(f"[supervisor] terminating {name} pid={proc.pid}")
                proc.terminate()
        time.sleep(1.0)
        for name, meta in processes.items():
            proc = meta.get("proc")
            if proc and proc.poll() is None:
                print(f"[supervisor] killing {name} pid={proc.pid}")
                proc.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
