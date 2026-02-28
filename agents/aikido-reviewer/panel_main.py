"""Minimal Railway entrypoint for self-hosted Kodosumi panel."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List


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
    """Railway fix: do not forward panel host header when proxying to registered app."""
    path = Path("/usr/local/lib/python3.11/site-packages/kodosumi/service/proxy.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    needle = 'request_headers.pop("content-length", None)'
    replacement = (
        'request_headers.pop("content-length", None)\n'
        '            request_headers.pop("host", None)\n'
        '            request_headers.pop("Host", None)'
    )
    if needle in text and replacement not in text:
        path.write_text(text.replace(needle, replacement), encoding="utf-8")


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

    if os.getenv("KODO_PATCH_HEALTH_AUTH", "true").strip().lower() in {"1", "true", "yes"}:
        _patch_health_auth()
    if os.getenv("KODO_PATCH_HTTPS_PROXY", "true").strip().lower() in {"1", "true", "yes"}:
        _patch_inputs_force_https_panel_proxy()
    if os.getenv("KODO_PATCH_PROXY_HOST", "true").strip().lower() in {"1", "true", "yes"}:
        _patch_proxy_host_forwarding()
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

    start_cmd = ["koco", "start", "--address", app_server]
    for endpoint in registers:
        start_cmd.extend(["--register", endpoint])

    try:
        return subprocess.call(start_cmd)
    finally:
        _run(["ray", "stop", "--force"], check=False)


if __name__ == "__main__":
    sys.exit(main())
