#!/usr/bin/env python
"""start_all.py

Start backend (uvicorn) and frontend (vite) from one command.
Usage:
  python start_all.py [--backend-only] [--frontend-only] [--dry-run]
"""

import argparse
import os
import socket
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple


ROOT = Path(__file__).parent
PLATFORM_ROOT = ROOT / "falcon-ai-vision-platform"
BACKEND_DIR = PLATFORM_ROOT / "backend"
FRONTEND_DIR = PLATFORM_ROOT / "frontend"
REQUIRED_BACKEND_MODULES = ("fastapi", "uvicorn", "slowapi", "email_validator", "argon2", "socketio")
REQUIRED_PYTHON_MAJOR = 3
REQUIRED_PYTHON_MINOR = 11


def _python_candidates() -> Iterable[Tuple[list[str], str]]:
    override = os.getenv("BACKEND_PYTHON", "").strip()
    if override:
        yield [override], f"BACKEND_PYTHON={override}"

    for relative in ("venv_ai/Scripts/python.exe", "venv/Scripts/python.exe", ".venv/Scripts/python.exe"):
        candidate = ROOT / relative
        if candidate.exists():
            yield [str(candidate)], str(candidate)

    py_launcher = shutil.which("py")
    if py_launcher:
        yield [py_launcher, "-3.11"], "py -3.11"

    yield [sys.executable], sys.executable

    python_cmd = shutil.which("python")
    if python_cmd:
        yield [python_cmd], python_cmd


def _supports_backend(command: list[str]) -> bool:
    probe_script = (
        "import importlib.util, sys; "
        f"mods={REQUIRED_BACKEND_MODULES!r}; "
        f"vok=(sys.version_info[:2]==({REQUIRED_PYTHON_MAJOR},{REQUIRED_PYTHON_MINOR})); "
        "mok=all(importlib.util.find_spec(m) for m in mods); "
        "sys.exit(0 if (vok and mok) else 1)"
    )
    try:
        result = subprocess.run(
            [*command, "-c", probe_script],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0


def resolve_backend_python() -> Tuple[Optional[list[str]], Optional[str]]:
    seen = set()
    for command, label in _python_candidates():
        key = " ".join(command)
        if key in seen:
            continue
        seen.add(key)
        if _supports_backend(command):
            return command, label
    return None, None


def build_commands(package_manager: str = "npm") -> Tuple[list[str], list[str], str]:
    backend_python, backend_label = resolve_backend_python()
    if backend_python is None or backend_label is None:
        raise RuntimeError(
            f"No usable Python {REQUIRED_PYTHON_MAJOR}.{REQUIRED_PYTHON_MINOR} for backend. "
            "Missing one of required modules: "
            + ", ".join(REQUIRED_BACKEND_MODULES)
        )

    backend_cmd = [
        *backend_python,
        "-m",
        "uvicorn",
        "vms.backend.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "5003",
        "--reload",
    ]

    if package_manager == "pnpm":
        frontend_cmd = ["pnpm", "run", "dev"]
    elif package_manager == "yarn":
        frontend_cmd = ["yarn", "run", "dev"]
    else:
        frontend_cmd = ["npm", "run", "dev"]

    return backend_cmd, frontend_cmd, backend_label


def check_tools() -> Tuple[list[str], Optional[str]]:
    available = {"npm": shutil.which("npm"), "pnpm": shutil.which("pnpm"), "yarn": shutil.which("yarn")}
    missing = [name for name, path in available.items() if path is None]

    if available["npm"]:
        selected = "npm"
    elif available["pnpm"]:
        selected = "pnpm"
    elif available["yarn"]:
        selected = "yarn"
    else:
        selected = None

    return missing, selected


def start_process(cmd: list[str], cwd: Optional[Path] = None, env: Optional[dict] = None) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=str(cwd) if cwd else None, env=env)


def is_port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Start backend (uvicorn) and frontend (vite)")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = parser.parse_args()

    missing, package_manager = check_tools()
    backend_cmd, frontend_cmd, backend_label = build_commands(package_manager=package_manager or "npm")

    if args.dry_run:
        print("Backend Python:", backend_label)
        print("Backend command:", " ".join(backend_cmd))
        print("Frontend command:", " ".join(frontend_cmd), f"(cwd={FRONTEND_DIR})")
        return

    if missing:
        print("Missing tools:", ", ".join(missing))
        if package_manager is None:
            print("No frontend package manager detected (npm/pnpm/yarn).")
            if not args.backend_only:
                print("Frontend disabled. Re-run with --backend-only if needed.")
                args.frontend_only = True
        else:
            print(f"Using '{package_manager}' for frontend.")

    processes: list[Tuple[str, subprocess.Popen]] = []
    try:
        if not args.frontend_only:
            if is_port_in_use("127.0.0.1", 5003):
                raise RuntimeError("Port 5003 is already in use. Stop existing backend before starting.")
            print(f"Starting backend with: {backend_label}")
            process = start_process(backend_cmd, cwd=BACKEND_DIR)
            processes.append(("backend", process))

        if not args.backend_only:
            print("Starting frontend (vite)...")
            process = start_process(frontend_cmd, cwd=FRONTEND_DIR)
            processes.append(("frontend", process))

        print("Servers started. Press Ctrl+C to stop.")
        while True:
            for name, process in list(processes):
                return_code = process.poll()
                if return_code is not None:
                    print(f"Process {name} exited with code {return_code}")
                    processes.remove((name, process))
            if not processes:
                print("All processes stopped.")
                break
            time.sleep(1)
    except RuntimeError as error:
        print(str(error))
    except KeyboardInterrupt:
        print("\nStopping child processes...")
    finally:
        for name, process in processes:
            try:
                print(f"Terminating {name} (pid={process.pid})")
                process.terminate()
            except Exception:
                pass

        time.sleep(1)
        for name, process in processes:
            if process.poll() is None:
                try:
                    print(f"Killing {name} (pid={process.pid})")
                    process.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
