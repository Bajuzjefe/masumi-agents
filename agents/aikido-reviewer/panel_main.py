"""Minimal Railway entrypoint for self-hosted Kodosumi panel."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


def _split_registers(raw: str) -> List[str]:
    values: List[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        item = chunk.strip()
        if item:
            values.append(item)
    return values


def _run(cmd: List[str], check: bool = True) -> int:
    proc = subprocess.run(cmd, check=check)
    return proc.returncode


def _is_true(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


def _wait_http_ok(url: str, timeout_seconds: float = 30.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                if 200 <= int(response.status) < 300:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    return False


def _dedupe_keep_order(values: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _start_local_ui() -> tuple[subprocess.Popen[bytes] | None, str | None]:
    if not _is_true("KODO_LOCAL_UI_ENABLED", "true"):
        return None, None
    local_ui_host = os.getenv("KODO_LOCAL_UI_HOST", "127.0.0.1")
    local_ui_port = os.getenv("KODO_LOCAL_UI_PORT", "8031")
    env = os.environ.copy()
    env["HOST"] = local_ui_host
    env["PORT"] = local_ui_port
    # Force ui_main/kodosumi_app Ray init to attach to the panel Ray head.
    env.setdefault("RAY_ADDRESS", "auto")
    env.setdefault("KODOSUMI_RAY_NAMESPACE", "kodosumi")
    cmd = [sys.executable, "ui_main.py"]
    logger.info("Starting colocated Kodosumi UI: %s", " ".join(cmd))
    process = subprocess.Popen(cmd, env=env)
    health_url = f"http://{local_ui_host}:{local_ui_port}/health"
    if not _wait_http_ok(
        health_url,
        timeout_seconds=float(os.getenv("KODO_LOCAL_UI_HEALTH_TIMEOUT_SECONDS", "45")),
    ):
        process.terminate()
        process.wait(timeout=10)
        raise RuntimeError(f"Local Kodosumi UI failed health check at {health_url}")
    logger.info("Colocated Kodosumi UI healthy at %s", health_url)
    register_url = f"http://{local_ui_host}:{local_ui_port}/openapi.json"
    return process, register_url


def _patch_inputs_force_https_panel_proxy() -> None:
    """Railway fix: keep internal panel proxy target on HTTPS to avoid POST downgrade."""
    path = Path("/usr/local/lib/python3.11/site-packages/kodosumi/service/inputs/inputs.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    get_old = (
        "schema_url = str(request.base_url).rstrip(\n"
        "            \"/\") + f\"/-/{path.lstrip('/')}\""
    )
    get_new = (
        "schema_url = ((f\"https://{request.headers.get('host', '')}\" "
        "if request.headers.get('host') else str(request.base_url).rstrip(\"/\")) "
        "+ f\"/-/{path.lstrip('/')}\" )"
    )
    post_old = 'schema_url = str(request.base_url).rstrip("/") + f"/-/{path}"'
    post_new = (
        "schema_url = ((f\"https://{request.headers.get('host', '')}\" "
        "if request.headers.get('host') else str(request.base_url).rstrip(\"/\")) "
        "+ f\"/-/{path.lstrip('/')}\" )"
    )
    changed = False
    if get_old in text:
        text = text.replace(get_old, get_new)
        changed = True
    if post_old in text:
        text = text.replace(post_old, post_new)
        changed = True
    if changed:
        path.write_text(text, encoding="utf-8")


def _patch_proxy_host_forwarding() -> None:
    """Railway fix: sanitize forwarded headers so Host never loops proxy traffic back to panel."""
    path = Path("/usr/local/lib/python3.11/site-packages/kodosumi/service/proxy.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    old_forward = (
        "request_headers = dict(request.headers)\n"
        "            request_headers[KODOSUMI_USER] = request.user\n"
        "            request_headers[KODOSUMI_BASE] = base\n"
        "            request_headers[KODOSUMI_URL] = str(request.base_url)\n"
        "            host = request.headers.get(\"host\", None)\n"
        "            body = await request.body()\n"
        "            request_headers.pop(\"content-length\", None)"
    )
    new_forward = (
        "request_headers = {\n"
        "                KODOSUMI_USER: request.user,\n"
        "                KODOSUMI_BASE: base,\n"
        "                KODOSUMI_URL: str(request.base_url),\n"
        "            }\n"
        "            for key in (\"accept\", \"content-type\", \"authorization\"):\n"
        "                value = request.headers.get(key)\n"
        "                if value:\n"
        "                    request_headers[key] = value\n"
        "            host = request.headers.get(\"host\", None)\n"
        "            body = await request.body()"
    )
    if old_forward in text:
        text = text.replace(old_forward, new_forward)

    old_lock = (
        "request_headers = dict(request.headers)\n"
        "            request_headers[KODOSUMI_USER] = request.user\n"
        "            # request_headers[KODOSUMI_BASE] = base\n"
        "            host = request.headers.get(\"host\", None)\n"
        "            body = await request.body()\n"
        "            request_headers.pop(\"content-length\", None)"
    )
    new_lock = (
        "request_headers = {\n"
        "                KODOSUMI_USER: request.user,\n"
        "            }\n"
        "            for key in (\"accept\", \"content-type\", \"authorization\"):\n"
        "                value = request.headers.get(key)\n"
        "                if value:\n"
        "                    request_headers[key] = value\n"
        "            host = request.headers.get(\"host\", None)\n"
        "            body = await request.body()"
    )
    if old_lock in text:
        text = text.replace(old_lock, new_lock)

    path.write_text(text, encoding="utf-8")


def _patch_health_auth() -> None:
    """Allow unauthenticated /health so Railway health checks can pass."""
    path = Path("/usr/local/lib/python3.11/site-packages/kodosumi/service/health.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if 'opt={"no_auth": True}' in text:
        return
    old = 'status_code=200, \n         operation_id="01_health_get")'
    new = 'status_code=200, opt={"no_auth": True}, \n         operation_id="01_health_get")'
    if old in text:
        path.write_text(text.replace(old, new), encoding="utf-8")


def _patch_spooler_actor_discovery() -> None:
    """Ray compatibility fix: discover Runner actors even when class_name is fully-qualified."""
    path = Path("/usr/local/lib/python3.11/site-packages/kodosumi/spooler.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "endswith(\"Runner\")" in text:
        return
    old = (
        "                states = list_actors(filters=[\n"
        "                    (\"class_name\", \"=\", \"Runner\"), \n"
        "                    (\"state\", \"=\", \"ALIVE\")])"
    )
    new = (
        "                states = list_actors(filters=[\n"
        "                    (\"state\", \"=\", \"ALIVE\")])\n"
        "                states = [\n"
        "                    state for state in states\n"
        "                    if str(getattr(state, \"class_name\", \"\")).endswith(\"Runner\")\n"
        "                ]"
    )
    if old in text:
        path.write_text(text.replace(old, new), encoding="utf-8")


def _reset_admin_db_if_requested() -> None:
    if os.getenv("KODO_RESET_ADMIN_DB", "").strip().lower() not in {"1", "true", "yes"}:
        return
    for file_name in ("admin.db", "admin.db-shm", "admin.db-wal"):
        path = Path("./data") / file_name
        if path.exists():
            path.unlink()


def main() -> int:
    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "8080")
    app_server = os.getenv("KODO_APP_SERVER", f"http://{host}:{port}")
    registers = _split_registers(os.getenv("REGISTER_ENDPOINT", ""))

    os.environ.setdefault("RAY_USE_MULTIPROCESSING_CPU_COUNT", "1")
    os.environ.setdefault("RAY_DISABLE_DOCKER_CPU_WARNING", "1")
    os.environ.setdefault("FORWARDED_ALLOW_IPS", "*")
    os.environ.setdefault("KODO_RAY_SERVER", "localhost:6379")
    os.environ.setdefault("KODO_APP_WORKERS", "1")
    os.environ.setdefault("KODO_APP_STD_LEVEL", "INFO")
    os.environ.setdefault("KODO_UVICORN_LEVEL", "INFO")
    os.environ["KODO_APP_SERVER"] = app_server

    if _is_true("KODO_PATCH_HEALTH_AUTH", "true"):
        _patch_health_auth()
    if _is_true("KODO_PATCH_HTTPS_PROXY", "true"):
        _patch_inputs_force_https_panel_proxy()
    if _is_true("KODO_PATCH_PROXY_HOST", "true"):
        _patch_proxy_host_forwarding()
    if _is_true("KODO_PATCH_SPOOLER_DISCOVERY", "true"):
        _patch_spooler_actor_discovery()
    _reset_admin_db_if_requested()

    _run(["ray", "stop", "--force"], check=False)
    ray_cmd = [
        "ray",
        "start",
        "--head",
        "--port",
        "6379",
        "--disable-usage-stats",
        "--include-dashboard=false",
        "--num-cpus",
        os.getenv("KODOSUMI_RAY_NUM_CPUS", "1"),
        "--object-store-memory",
        os.getenv("KODOSUMI_RAY_OBJECT_STORE_MEMORY", "78643200"),
    ]
    _run(ray_cmd, check=True)

    local_ui_process: subprocess.Popen[bytes] | None = None
    local_register: str | None = None
    start_cmd = ["koco", "start", "--address", app_server]
    try:
        local_ui_process, local_register = _start_local_ui()
    except Exception:
        _run(["ray", "stop", "--force"], check=False)
        raise

    if local_register:
        if _is_true("KODO_LOCAL_UI_INCLUDE_EXTERNAL_REGISTERS", "false"):
            registers = _dedupe_keep_order([local_register, *registers])
        else:
            registers = [local_register]
    else:
        registers = _dedupe_keep_order(registers)

    for endpoint in registers:
        start_cmd.extend(["--register", endpoint])
    logger.info("Starting Kodosumi panel with registers=%s", registers)

    try:
        return subprocess.call(start_cmd)
    finally:
        if local_ui_process is not None:
            local_ui_process.terminate()
            try:
                local_ui_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                local_ui_process.kill()
        _run(["ray", "stop", "--force"], check=False)


if __name__ == "__main__":
    sys.exit(main())
