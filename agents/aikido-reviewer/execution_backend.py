"""Execution backend helpers for default vs Kodosumi worker routing."""

from __future__ import annotations

import uuid
from typing import Mapping, Optional, Tuple

import httpx

ALLOWED_BACKENDS = {"default", "kodosumi"}
TRUTHY_VALUES = {"1", "true", "yes", "on"}


def parse_bool(value: str | bool | None, default: bool = False) -> bool:
    """Parse a boolean from string-like values."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized == "":
        return default
    return normalized in TRUTHY_VALUES


def normalize_backend(value: str | None) -> Optional[str]:
    """Normalize backend value to supported values or None."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized not in ALLOWED_BACKENDS:
        raise ValueError("execution_backend must be one of: default, kodosumi")
    return normalized


def resolve_execution_backend(
    requested_backend: str | None,
    canary_header_value: str | None,
    kodosumi_enabled: bool,
) -> str:
    """Resolve selected execution backend using precedence.

    Precedence:
    1) explicit requested_backend
    2) canary header when kodosumi is enabled
    3) default
    """
    requested = normalize_backend(requested_backend)
    if requested is not None:
        if requested == "kodosumi" and not kodosumi_enabled:
            raise ValueError("execution_backend=kodosumi requested but KODOSUMI_ENABLED is false")
        return requested

    header_canary = parse_bool(canary_header_value, default=False)
    if kodosumi_enabled and header_canary:
        return "kodosumi"
    return "default"


def build_worker_headers(token: str, worker_request_id: str) -> dict:
    """Build auth + tracing headers for worker calls."""
    return {
        "Authorization": f"Bearer {token}",
        "x-worker-request-id": worker_request_id,
        "content-type": "application/json",
    }


async def execute_via_worker(
    *,
    internal_url: str,
    token: str,
    timeout_seconds: float,
    input_data: dict,
    job_id: str,
    payment_id: str,
    attempts: int = 2,
) -> Tuple[dict, str]:
    """Execute analysis on remote Kodosumi worker with retry."""
    if not internal_url:
        raise RuntimeError("KODOSUMI_INTERNAL_URL is not configured")
    if not token:
        raise RuntimeError("KODOSUMI_INTERNAL_TOKEN is not configured")

    worker_request_id = uuid.uuid4().hex
    headers = build_worker_headers(token, worker_request_id)
    payload = {
        "job_id": job_id,
        "payment_id": payment_id,
        "input_data": input_data,
    }
    url = f"{internal_url.rstrip('/')}/internal/execute"

    last_error: Exception | None = None
    for _ in range(max(1, attempts)):
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise RuntimeError("Worker returned non-object JSON payload")
                return result, worker_request_id
        except Exception as exc:  # noqa: BLE001 - propagate caller-level handling
            last_error = exc

    assert last_error is not None
    raise last_error


def header_value(headers: Mapping[str, str], header_name: str) -> str:
    """Case-insensitive header lookup helper."""
    # Starlette headers are case-insensitive already, but keep helper deterministic.
    return headers.get(header_name, "")
