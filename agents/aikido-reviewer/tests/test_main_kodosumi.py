"""Tests for main backend execution fallback behavior."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main


@pytest.mark.asyncio
async def test_kodosumi_failure_falls_back_when_enabled(monkeypatch):
    job_id = "job-fallback"
    main.jobs[job_id] = {
        "execution_backend": "kodosumi",
        "execution_meta": main._new_execution_meta(),
    }

    async def fake_worker(**kwargs):
        raise RuntimeError("worker unavailable")

    async def fake_local(input_data):
        return {"source": "local"}

    monkeypatch.setattr(main, "execute_via_worker", fake_worker)
    monkeypatch.setattr(main, "execute_agentic_task", fake_local)
    monkeypatch.setenv("KODOSUMI_FALLBACK_ON_ERROR", "true")

    result = await main._execute_with_selected_backend(job_id, "payment-1", {"a": "b"})
    assert result == {"source": "local"}
    assert main.jobs[job_id]["execution_meta"]["fallback_used"] is True
    assert isinstance(main.jobs[job_id]["execution_meta"]["duration_ms"], int)

    main.jobs.pop(job_id, None)


@pytest.mark.asyncio
async def test_kodosumi_failure_raises_when_fallback_disabled(monkeypatch):
    job_id = "job-no-fallback"
    main.jobs[job_id] = {
        "execution_backend": "kodosumi",
        "execution_meta": main._new_execution_meta(),
    }

    async def fake_worker(**kwargs):
        raise RuntimeError("worker unavailable")

    monkeypatch.setattr(main, "execute_via_worker", fake_worker)
    monkeypatch.setenv("KODOSUMI_FALLBACK_ON_ERROR", "false")

    with pytest.raises(RuntimeError, match="worker unavailable"):
        await main._execute_with_selected_backend(job_id, "payment-2", {"a": "b"})

    main.jobs.pop(job_id, None)
