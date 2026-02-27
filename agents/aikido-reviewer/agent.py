"""Pipeline orchestrator — process_job entry point for masumi."""

import asyncio
import json
import logging
import os

from analyzer import analyze_findings
from report_builder import build_report
from schemas import AikidoReport, ReviewReport

logger = logging.getLogger(__name__)


def process_job(input_data: dict) -> dict:
    """Masumi start_job_handler — synchronous wrapper around async pipeline.

    Only safe to call from synchronous context (not inside an existing event loop).

    input_data keys:
        aikido_report: str — JSON string of aikido.findings.v1 report
        source_files: str — JSON string of {path: source_code} dict
        review_depth: str — "quick" | "standard" | "deep" (default: "standard")
    """
    return asyncio.run(process_job_async(input_data))


async def process_job_async(input_data: dict) -> dict:
    """Async pipeline: parse → analyze → build report → serialize."""
    # Parse inputs
    aikido_json = input_data.get("aikido_report", "")
    source_json = input_data.get("source_files", "{}")
    depth = input_data.get("review_depth", "standard")

    if depth not in ("quick", "standard", "deep"):
        depth = "standard"

    logger.info("Starting aikido review job (depth=%s)", depth)

    # Parse aikido report
    try:
        report_data = json.loads(aikido_json) if isinstance(aikido_json, str) else aikido_json
        report = AikidoReport(**report_data)
    except Exception as e:
        logger.error("Failed to parse aikido report: %s", e)
        return {"error": f"Invalid aikido report: {e}"}

    # Parse source files
    try:
        source_files = json.loads(source_json) if isinstance(source_json, str) else source_json
        if not isinstance(source_files, dict):
            logger.warning("source_files is not a dict, ignoring")
            source_files = {}
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("Failed to parse source_files: %s — proceeding without source context", e)
        source_files = {}

    logger.info(
        "Reviewing %d findings from project '%s' with %d source files",
        len(report.findings), report.project, len(source_files),
    )

    # Analyze
    anthropic_credential = os.environ.get("ANTHROPIC_API_KEY")
    reviews = await analyze_findings(
        report.findings,
        source_files,
        depth=depth,
        anthropic_credential=anthropic_credential,
    )

    # Build report
    review_report = build_report(report.project, reviews, depth)

    logger.info(
        "Review complete: %d TP, %d FP, %d needs_review (risk: %s)",
        review_report.classification_summary.confirmed_tp
        + review_report.classification_summary.likely_tp,
        review_report.classification_summary.confirmed_fp
        + review_report.classification_summary.likely_fp,
        review_report.classification_summary.needs_review,
        review_report.risk_level,
    )

    return review_report.model_dump(mode="json")
