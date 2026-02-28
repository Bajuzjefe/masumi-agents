"""Kodosumi + machine endpoint runtime for Aikido Audit Reviewer."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from agent import process_job_async

logger = logging.getLogger(__name__)

try:
    from kodosumi import forms as F
    from kodosumi.serve import ServeAPI
except ImportError:  # pragma: no cover - optional path for non-worker runtimes
    F = None
    ServeAPI = None


class ExecuteRequest(BaseModel):
    input_data: Dict[str, Any]
    job_id: str | None = None
    payment_id: str | None = None


def _validate_worker_token(authorization: str | None) -> None:
    token = str(os.getenv("KODOSUMI_INTERNAL_TOKEN", "")).strip()
    if not token:
        raise HTTPException(status_code=500, detail="KODOSUMI_INTERNAL_TOKEN not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    presented = authorization.split(" ", 1)[1].strip()
    if presented != token:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def run_review_payload(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Shared worker runner used by Kodosumi and machine endpoint."""
    return await process_job_async(input_data)


machine_app = FastAPI(
    title="Aikido Kodosumi Worker",
    description="Internal execution worker used by API canary routing.",
    version="1.0.0",
)


@machine_app.get("/health")
async def machine_health() -> dict:
    return {"status": "healthy", "service": "aikido-reviewer-kodosumi-worker"}


@machine_app.post("/internal/execute")
async def internal_execute(
    payload: ExecuteRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    _validate_worker_token(authorization)
    worker_request_id = request.headers.get("x-worker-request-id", "n/a")
    started_at = time.perf_counter()
    result = await run_review_payload(payload.input_data)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "Worker execution completed: job_id=%s payment_id=%s worker_request_id=%s duration_ms=%s",
        payload.job_id,
        payload.payment_id,
        worker_request_id,
        elapsed_ms,
    )
    return result


if ServeAPI is not None and F is not None:
    app = ServeAPI()
    input_form = F.Model([
        F.Markdown("# Aikido Audit Reviewer"),
        F.Markdown(
            "Upload your Aikido scan output and source code to receive "
            "an AI-powered triage report classifying each finding as "
            "true/false positive with detailed reasoning."
        ),
        F.Break(),
        F.InputArea(
            label="Aikido JSON Report",
            name="aikido_report",
        ),
        F.InputArea(
            label="Source Code Files (JSON dict)",
            name="source_files",
        ),
        F.Submit(),
        F.Cancel(),
    ])

    @app.enter(form=input_form)
    async def review_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Kodosumi form entrypoint."""
        aikido_report = payload.get("aikido_report", "")
        source_files = payload.get("source_files", "{}")
        review_depth = "deep"

        if not aikido_report:
            return {"error": "aikido_report is required"}

        try:
            report_data = json.loads(aikido_report) if isinstance(aikido_report, str) else aikido_report
            total = report_data.get("total", 0)
        except (json.JSONDecodeError, AttributeError):
            return {"error": "Invalid JSON in aikido_report"}

        logger.info("Kodosumi form review start: findings=%d depth=%s", total, review_depth)
        return await run_review_payload({
            "aikido_report": aikido_report,
            "source_files": source_files,
            "review_depth": review_depth,
        })
else:
    app = None


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8021"))
    uvicorn.run(machine_app, host=host, port=port)
