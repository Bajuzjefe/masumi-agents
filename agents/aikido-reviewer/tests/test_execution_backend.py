"""Unit tests for execution backend helpers."""

import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import execution_backend


def test_resolve_backend_requested_wins():
    backend = execution_backend.resolve_execution_backend(
        requested_backend="default",
        canary_header_value="1",
        kodosumi_enabled=True,
    )
    assert backend == "default"


def test_resolve_backend_header_routes_when_enabled():
    backend = execution_backend.resolve_execution_backend(
        requested_backend=None,
        canary_header_value="true",
        kodosumi_enabled=True,
    )
    assert backend == "kodosumi"


def test_resolve_backend_header_ignored_when_disabled():
    backend = execution_backend.resolve_execution_backend(
        requested_backend=None,
        canary_header_value="1",
        kodosumi_enabled=False,
    )
    assert backend == "default"


def test_resolve_backend_rejects_disabled_explicit_kodosumi():
    with pytest.raises(ValueError, match="KODOSUMI_ENABLED"):
        execution_backend.resolve_execution_backend(
            requested_backend="kodosumi",
            canary_header_value=None,
            kodosumi_enabled=False,
        )


def test_build_worker_headers():
    headers = execution_backend.build_worker_headers("tok", "rid")
    assert headers["Authorization"] == "Bearer tok"
    assert headers["x-worker-request-id"] == "rid"


@pytest.mark.asyncio
async def test_execute_via_worker_retries_once(monkeypatch):
    calls = {"count": 0}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"ok": True}

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == 5

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers, json):
            calls["count"] += 1
            if calls["count"] == 1:
                raise httpx.ConnectError("transient connect error")
            assert url.endswith("/internal/execute")
            assert headers["Authorization"] == "Bearer token"
            assert json["job_id"] == "job-1"
            return FakeResponse()

    monkeypatch.setattr(execution_backend.httpx, "AsyncClient", FakeClient)

    result, worker_request_id = await execution_backend.execute_via_worker(
        internal_url="https://worker.internal",
        token="token",
        timeout_seconds=5,
        input_data={"x": "y"},
        job_id="job-1",
        payment_id="pay-1",
        attempts=2,
    )

    assert result == {"ok": True}
    assert isinstance(worker_request_id, str)
    assert len(worker_request_id) > 0
    assert calls["count"] == 2
