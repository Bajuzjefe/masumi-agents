"""Kodosumi runtime entry point for the Aikido Audit Reviewer.

Provides ServeAPI with input forms, Ray-based parallelization,
and real-time Tracer events for progress monitoring.
"""

import json
import logging
import os
from typing import Any, Dict

from kodosumi import forms as F
from kodosumi.serve import ServeAPI, Launch

from agent import process_job_async

logger = logging.getLogger(__name__)

app = ServeAPI()

# ---------------------------------------------------------------------------
# Input form definition
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

@app.enter(form=input_form)
async def review_handler(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Kodosumi entrypoint — receives form data, runs review pipeline."""
    aikido_report = payload.get("aikido_report", "")
    source_files = payload.get("source_files", "{}")
    review_depth = "deep"

    if not aikido_report:
        return {"error": "aikido_report is required"}

    # Validate JSON
    try:
        report_data = json.loads(aikido_report) if isinstance(aikido_report, str) else aikido_report
        total = report_data.get("total", 0)
    except (json.JSONDecodeError, AttributeError):
        return {"error": "Invalid JSON in aikido_report"}

    logger.info(
        "Starting review: %d findings, depth=%s",
        total,
        review_depth,
    )

    # Run the review pipeline (async-safe, no asyncio.run() nesting)
    result = await process_job_async({
        "aikido_report": aikido_report,
        "source_files": source_files,
        "review_depth": review_depth,
    })

    return result


# ---------------------------------------------------------------------------
# Ray Serve deployment (optional, for production scaling)
# ---------------------------------------------------------------------------

try:
    from ray import serve

    @serve.deployment(
        num_replicas=1,
        ray_actor_options={"num_cpus": 1},
    )
    @serve.ingress(app)
    class AikidoReviewerDeployment:
        """Ray Serve deployment wrapper."""
        pass

except ImportError:
    # Ray not installed — app still works standalone via uvicorn
    pass
