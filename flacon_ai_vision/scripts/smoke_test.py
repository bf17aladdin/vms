from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_WORKDIR = REPO_ROOT / "backend"
DEFAULT_HOST = "127.0.0.1"


class SmokeTestError(RuntimeError):
    """Raised when a smoke-test step fails."""


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((DEFAULT_HOST, 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _json_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, dict[str, Any] | list[Any] | None, str]:
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)

    body_bytes = None
    if payload is not None:
        body_bytes = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url=url,
        data=body_bytes,
        headers=request_headers,
        method=method.upper(),
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            parsed_body = json.loads(raw_body) if raw_body else None
            return int(response.status), parsed_body, raw_body
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        parsed_body: dict[str, Any] | list[Any] | None
        try:
            parsed_body = json.loads(raw_body) if raw_body else None
        except json.JSONDecodeError:
            parsed_body = None
        return int(exc.code), parsed_body, raw_body


def _expect_status(
    step: str,
    status_code: int,
    expected: int,
    raw_body: str,
) -> None:
    if status_code != expected:
        raise SmokeTestError(
            f"{step} failed: expected HTTP {expected}, got HTTP {status_code}. "
            f"Response body: {raw_body[:800]}"
        )


def _tail_file(path: Path, *, max_lines: int = 80) -> str:
    if not path.exists():
        return f"{path.name}: <missing>"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-max_lines:]
    return "\n".join(tail) if tail else f"{path.name}: <empty>"


class BackendProcess:
    def __init__(self, *, host: str, port: int, temp_dir: Path) -> None:
        self.host = host
        self.port = port
        self.temp_dir = temp_dir
        self.stdout_path = temp_dir / "backend.stdout.log"
        self.stderr_path = temp_dir / "backend.stderr.log"
        self._stdout_handle = None
        self._stderr_handle = None
        self.process: subprocess.Popen[str] | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "APP_ENV": "development",
                "DEBUG": "false",
                "RELOAD": "false",
                "HOST": self.host,
                "BACKEND_PORT": str(self.port),
                "DATABASE_URL": f"sqlite:///{(self.temp_dir / 'smoke_test.sqlite3').as_posix()}",
                "FACE_PGVECTOR_ENABLED": "false",
                "REQUEST_LOGGING_ENABLED": "false",
                "RATE_LIMIT_ENABLED": "false",
                "LOG_JSON": "false",
                "SECRET_KEY": "smoke-test-secret-key",
                "LOG_FILE_PATH": str((self.temp_dir / "backend.log").resolve()),
            }
        )

        self._stdout_handle = self.stdout_path.open("w", encoding="utf-8")
        self._stderr_handle = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "vms.backend.main:app",
                "--host",
                self.host,
                "--port",
                str(self.port),
            ],
            cwd=str(BACKEND_WORKDIR),
            env=env,
            stdout=self._stdout_handle,
            stderr=self._stderr_handle,
            text=True,
        )

    def wait_until_ready(self, *, timeout_sec: float = 90.0) -> None:
        deadline = time.time() + timeout_sec
        health_url = f"{self.base_url}/health"
        last_error = "health endpoint was never reachable"

        while time.time() < deadline:
            if self.process is None:
                raise SmokeTestError("Backend process was not started")

            exit_code = self.process.poll()
            if exit_code is not None:
                raise SmokeTestError(
                    f"Backend process exited early with code {exit_code}.\n"
                    f"--- stdout ---\n{_tail_file(self.stdout_path)}\n"
                    f"--- stderr ---\n{_tail_file(self.stderr_path)}"
                )

            try:
                status_code, payload, raw_body = _json_request("GET", health_url, timeout=2.0)
                if status_code == 200 and isinstance(payload, dict) and payload.get("status") == "ok":
                    return
                last_error = f"unexpected health response: HTTP {status_code} {raw_body[:400]}"
            except Exception as exc:  # pragma: no cover - network timing dependent
                last_error = str(exc)

            time.sleep(1.0)

        raise SmokeTestError(
            f"Backend did not become ready within {timeout_sec:.0f}s: {last_error}\n"
            f"--- stdout ---\n{_tail_file(self.stdout_path)}\n"
            f"--- stderr ---\n{_tail_file(self.stderr_path)}"
        )

    def stop(self) -> None:
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
        finally:
            if self._stdout_handle is not None:
                self._stdout_handle.close()
            if self._stderr_handle is not None:
                self._stderr_handle.close()


def run_smoke_test(*, keep_artifacts: bool = False) -> None:
    temp_dir_path = Path(tempfile.mkdtemp(prefix="falcon-smoke-test-"))
    backend = BackendProcess(host=DEFAULT_HOST, port=_find_free_port(), temp_dir=temp_dir_path)

    username = f"smoke_admin_{uuid4().hex[:8]}"
    password = "SmokeAdmin123!"
    email = f"{username}@example.com"
    company_name = f"Smoke Tenant {uuid4().hex[:6]}"
    headers: dict[str, str] = {}
    summary: dict[str, Any] = {
        "temp_dir": str(temp_dir_path),
        "base_url": backend.base_url,
        "steps": [],
    }

    try:
        print(f"[1/6] Starting backend on {backend.base_url}")
        backend.start()
        backend.wait_until_ready()
        summary["steps"].append("backend_start")

        print("[2/6] Checking /health")
        status_code, health_payload, raw_body = _json_request("GET", f"{backend.base_url}/health")
        _expect_status("GET /health", status_code, 200, raw_body)
        if not isinstance(health_payload, dict) or health_payload.get("status") != "ok":
            raise SmokeTestError(f"/health returned unexpected payload: {raw_body[:800]}")
        summary["health"] = health_payload
        summary["steps"].append("health")

        print("[3/6] Registering and logging in a test tenant")
        register_payload = {
            "username": username,
            "password": password,
            "full_name": "Smoke Test Admin",
            "email": email,
            "company_name": company_name,
            "plan": "starter",
        }
        status_code, register_body, raw_body = _json_request(
            "POST",
            f"{backend.base_url}/api/auth/register",
            payload=register_payload,
        )
        _expect_status("POST /api/auth/register", status_code, 200, raw_body)
        if not isinstance(register_body, dict) or not register_body.get("id"):
            raise SmokeTestError(f"Register payload missing user id: {raw_body[:800]}")

        status_code, login_body, raw_body = _json_request(
            "POST",
            f"{backend.base_url}/api/auth/login",
            payload={"username": username, "password": password},
        )
        _expect_status("POST /api/auth/login", status_code, 200, raw_body)
        if not isinstance(login_body, dict) or not login_body.get("access_token"):
            raise SmokeTestError(f"Login payload missing access_token: {raw_body[:800]}")
        headers = {"Authorization": f"Bearer {login_body['access_token']}"}
        summary["auth_user"] = login_body.get("user")
        summary["steps"].append("auth")

        print("[4/6] Creating a camera via API")
        camera_payload = {
            "name": "Smoke Test Camera",
            "description": "Created by automated smoke test",
            "camera_type": "mix",
            "rtsp_url": "rtsp://127.0.0.1:8554/smoke-test",
            "is_enabled": True,
            "is_active": True,
        }
        status_code, camera_body, raw_body = _json_request(
            "POST",
            f"{backend.base_url}/api/cameras",
            payload=camera_payload,
            headers=headers,
        )
        _expect_status("POST /api/cameras", status_code, 200, raw_body)
        if not isinstance(camera_body, dict) or not camera_body.get("camera"):
            raise SmokeTestError(f"Camera creation payload malformed: {raw_body[:800]}")
        camera = camera_body["camera"]
        camera_id = int(camera["id"])
        summary["camera"] = {"id": camera_id, "name": camera.get("name")}
        summary["steps"].append("camera_create")

        print("[5/6] Creating and reading events")
        event_payload = {
            "camera_id": camera_id,
            "event_type": "person",
            "severity": "info",
            "decision": "review",
            "description": "Smoke test event",
            "confidence": 0.92,
            "detected_objects": {"person": 1},
        }
        status_code, create_event_body, raw_body = _json_request(
            "POST",
            f"{backend.base_url}/api/events",
            payload=event_payload,
            headers=headers,
        )
        _expect_status("POST /api/events", status_code, 200, raw_body)
        if not isinstance(create_event_body, dict) or not create_event_body.get("event"):
            raise SmokeTestError(f"Event creation payload malformed: {raw_body[:800]}")
        event = create_event_body["event"]
        event_id = int(event["id"])

        status_code, list_events_body, raw_body = _json_request(
            "GET",
            f"{backend.base_url}/api/events?camera_id={camera_id}&limit=10",
            headers=headers,
        )
        _expect_status("GET /api/events", status_code, 200, raw_body)
        if not isinstance(list_events_body, dict) or "events" not in list_events_body:
            raise SmokeTestError(f"Event list payload malformed: {raw_body[:800]}")
        event_ids = {int(row["id"]) for row in list_events_body["events"]}
        if event_id not in event_ids:
            raise SmokeTestError(f"Created event {event_id} was not returned by /api/events")
        summary["event"] = {"id": event_id, "count": list_events_body.get("count", 0)}
        summary["steps"].append("events")

        print("[6/6] Calling an AI endpoint")
        status_code, detections_body, raw_body = _json_request(
            "GET",
            f"{backend.base_url}/api/ai/ops-kpi?camera_id={camera_id}&window_minutes=60",
            headers=headers,
            timeout=30.0,
        )
        _expect_status("GET /api/ai/ops-kpi", status_code, 200, raw_body)
        if not isinstance(detections_body, dict) or detections_body.get("success") is not True:
            raise SmokeTestError(f"AI ops-kpi payload malformed: {raw_body[:800]}")
        summary["ai"] = {
            "success": detections_body.get("success"),
            "detections_total_window": detections_body.get("detections_total_window"),
            "sla_status": detections_body.get("sla_status"),
        }
        summary["steps"].append("ai")

        print(json.dumps({"status": "ok", **summary}, indent=2))
    except Exception:
        print(
            json.dumps(
                {
                    "status": "failed",
                    **summary,
                    "backend_stdout_tail": _tail_file(backend.stdout_path),
                    "backend_stderr_tail": _tail_file(backend.stderr_path),
                },
                indent=2,
            )
        )
        raise
    finally:
        backend.stop()
        if keep_artifacts:
            print(f"Smoke-test artifacts kept in {temp_dir_path}")
        else:
            shutil.rmtree(temp_dir_path, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a backend smoke test against a temporary isolated environment.")
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep temporary database and backend logs after the run.",
    )
    args = parser.parse_args()

    try:
        run_smoke_test(keep_artifacts=bool(args.keep_artifacts))
        return 0
    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
