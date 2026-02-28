"""Masumi MIP-003 compliant entry point for the Aikido Audit Reviewer agent.

All review requests go through Masumi payment flow. No free/standalone access.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Dict, List

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from masumi.config import Config
from masumi.payment import Payment
from pydantic import BaseModel

from agent import process_job_async
from scan_runner import (
    contains_aiken_toml,
    run_aikido_scan_from_repo,
    run_aikido_scan_from_source_files,
)

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "")
PAYMENT_AUTH = os.getenv("PAYMENT_API_KEY", "")
NETWORK = os.getenv("NETWORK", "Preprod")

app = FastAPI(
    title="Aikido Audit Reviewer",
    description=(
        "AI-powered triage of Aikido security analysis findings for Aiken smart contracts. "
        "Classifies each finding as true/false positive with detailed reasoning."
    ),
    version="1.0.0",
)

# In-memory job store (not for production)
jobs: dict = {}
payment_instances: dict = {}
server_start_time = time.time()


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class InputDataItem(BaseModel):
    key: str
    value: str


class StartJobRequest(BaseModel):
    input_data: List[InputDataItem]

    class Config:
        json_schema_extra = {
            "example": {
                "input_data": [
                    {"key": "scan_mode", "value": "manual"},
                    {"key": "repo_url", "value": "https://github.com/org/repo"},
                    {"key": "aikido_report", "value": "{...}"},
                    {"key": "source_files", "value": "{...}"},
                ]
            }
        }


# ---------------------------------------------------------------------------
# Task execution
# ---------------------------------------------------------------------------

async def execute_agentic_task(input_data: dict) -> dict:
    """Execute the aikido review task (async-safe)."""
    logger.info("Starting aikido review task")
    result = await process_job_async(input_data)
    logger.info("Aikido review task completed")
    return result


def _parse_source_files(value: str | Dict[str, str]) -> Dict[str, str]:
    source_data = json.loads(value) if isinstance(value, str) else value
    if not isinstance(source_data, dict) or len(source_data) == 0:
        raise ValueError("Must contain at least one file entry")
    for file_path, content in source_data.items():
        if not isinstance(file_path, str) or not isinstance(content, str):
            raise ValueError("All source_files keys and values must be strings")
    return source_data


def _get_source_files_if_provided(input_data: Dict[str, str]) -> Dict[str, str] | None:
    raw = input_data.get("source_files")
    if raw is None:
        return None
    return _parse_source_files(raw)


# ---------------------------------------------------------------------------
# MIP-003: POST /start_job
# ---------------------------------------------------------------------------

@app.post("/start_job")
async def start_job(data: StartJobRequest):
    """Initiate a review job and create a payment request."""
    try:
        job_id = str(uuid.uuid4())

        agent_identifier = os.getenv("AGENT_IDENTIFIER", "").strip()
        if not agent_identifier or agent_identifier == "REPLACE":
            raise HTTPException(status_code=500, detail="AGENT_IDENTIFIER not configured.")

        if not PAYMENT_SERVICE_URL or not PAYMENT_AUTH:
            raise HTTPException(status_code=500, detail="Payment service not configured.")

        identifier_from_purchaser = uuid.uuid4().hex[:24]  # 24-char hex string
        input_data_dict = {item.key: item.value for item in data.input_data}
        requested_depth = str(input_data_dict.get("review_depth", "")).strip().lower()
        input_data_dict["review_depth"] = "deep"
        if requested_depth and requested_depth != "deep":
            logger.info("Ignoring requested review_depth=%s; deep mode is enforced", requested_depth)

        scan_mode = str(input_data_dict.get("scan_mode", "manual")).strip().lower()
        input_data_dict["scan_mode"] = scan_mode

        if scan_mode not in ("manual", "auto"):
            raise HTTPException(
                status_code=400,
                detail="'scan_mode' must be either 'manual' or 'auto'.",
            )

        report_raw = str(input_data_dict.get("aikido_report", "")).strip()
        repo_url = str(input_data_dict.get("repo_url", "")).strip()
        repo_ref = str(input_data_dict.get("repo_ref", "")).strip() or None
        repo_subpath = str(input_data_dict.get("repo_subpath", "")).strip() or None

        has_source_files = "source_files" in input_data_dict and str(input_data_dict.get("source_files", "")).strip() != ""

        if scan_mode == "manual" and not has_source_files:
            raise HTTPException(
                status_code=400,
                detail=(
                    "'source_files' is required in input_data. "
                    "Provide a JSON object mapping file paths to source code contents "
                    '(e.g. {"validators/main.ak": "validator main { ... }"}). '
                    "Without source code the reviewer cannot verify findings against your actual contract."
                ),
            )

        source_data = None
        if has_source_files:
            # Validate source files if present.
            try:
                source_data = _parse_source_files(input_data_dict["source_files"])
            except (json.JSONDecodeError, ValueError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"'source_files' must be a non-empty JSON object mapping file paths to source code: {e}",
                )

        # manual mode: report is mandatory
        if scan_mode == "manual" and not report_raw:
            raise HTTPException(
                status_code=400,
                detail="'aikido_report' is required in manual scan_mode.",
            )

        # auto mode: report is optional; if omitted, agent runs Aikido CLI after payment
        if scan_mode == "auto" and not report_raw:
            if repo_url:
                # repo_url path validated later during scan
                pass
            elif source_data and contains_aiken_toml(source_data):
                pass
            else:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Auto scan mode requires either repo_url or a complete Aiken project in source_files, "
                        "including aiken.toml."
                    ),
                )

        if scan_mode == "auto" and repo_url:
            # Keep these in canonical fields for background scan
            input_data_dict["repo_url"] = repo_url
            if repo_ref:
                input_data_dict["repo_ref"] = repo_ref
            if repo_subpath:
                input_data_dict["repo_subpath"] = repo_subpath

        if scan_mode == "auto" and not report_raw and source_data and not contains_aiken_toml(source_data):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Auto scan mode with source_files requires a complete Aiken project "
                    "including aiken.toml."
                ),
            )

        # if a report is provided (manual mode or auto override), validate shape now
        if report_raw:
            try:
                report_data = json.loads(report_raw)
                if not isinstance(report_data, dict) or "findings" not in report_data:
                    raise ValueError("Missing 'findings' key")
            except (json.JSONDecodeError, ValueError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"'aikido_report' must be valid Aikido JSON (aikido.findings.v1): {e}",
                )

        config = Config(
            payment_service_url=PAYMENT_SERVICE_URL,
            payment_api_key=PAYMENT_AUTH,
        )

        payment = Payment(
            agent_identifier=agent_identifier,
            config=config,
            identifier_from_purchaser=identifier_from_purchaser,
            input_data=input_data_dict,
            network=NETWORK,
        )

        payment_request = await payment.create_payment_request()
        payment_id = payment_request["data"]["blockchainIdentifier"]
        payment.payment_ids.add(payment_id)

        jobs[job_id] = {
            "status": "awaiting_payment",
            "payment_status": "pending",
            "payment_id": payment_id,
            "input_data": input_data_dict,
            "result": None,
            "identifier_from_purchaser": identifier_from_purchaser,
        }

        async def payment_callback(pid: str):
            await handle_payment_status(job_id, pid)

        payment_instances[job_id] = payment
        await payment.start_status_monitoring(payment_callback)

        seller_vkey = os.getenv("SELLER_VKEY", "")

        return {
            "job_id": job_id,
            "payment_id": payment_id,
            "identifierFromPurchaser": identifier_from_purchaser,
            "network": NETWORK,
            "sellerVkey": seller_vkey,
            "paymentType": "Web3CardanoV1",
            "blockchainIdentifier": payment_id,
            "submitResultTime": str(payment_request["data"]["submitResultTime"]),
            "unlockTime": str(payment_request["data"]["unlockTime"]),
            "externalDisputeUnlockTime": str(payment_request["data"]["externalDisputeUnlockTime"]),
            "agentIdentifier": agent_identifier,
            "inputHash": payment_request["data"]["inputHash"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error in start_job: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error.")


async def handle_payment_status(job_id: str, payment_id: str) -> None:
    """Execute task after payment confirmation."""
    try:
        logger.info("Payment %s completed for job %s, executing task...", payment_id, job_id)
        input_data = jobs[job_id]["input_data"]
        scan_mode = str(input_data.get("scan_mode", "manual")).strip().lower()
        report_raw = str(input_data.get("aikido_report", "")).strip()

        if scan_mode == "auto" and not report_raw:
            jobs[job_id]["status"] = "running_scan"
            logger.info("Running Aikido CLI auto scan for job %s", job_id)
            repo_url = str(input_data.get("repo_url", "")).strip()

            if repo_url:
                repo_ref = str(input_data.get("repo_ref", "")).strip() or None
                repo_subpath = str(input_data.get("repo_subpath", "")).strip() or None
                report_data, normalized_sources = await asyncio.to_thread(
                    run_aikido_scan_from_repo,
                    repo_url,
                    repo_ref,
                    repo_subpath,
                )
            else:
                source_data = _get_source_files_if_provided(input_data)
                if source_data is None:
                    raise ValueError("Auto scan expected source_files or repo_url.")
                report_data, normalized_sources = await asyncio.to_thread(
                    run_aikido_scan_from_source_files,
                    source_data,
                )

            input_data["aikido_report"] = json.dumps(report_data)
            input_data["source_files"] = json.dumps(normalized_sources)
            jobs[job_id]["scan_summary"] = {
                "schema_version": report_data.get("schema_version"),
                "total_findings": report_data.get("total", len(report_data.get("findings", []))),
                "scan_mode": "repo" if repo_url else "source_files",
            }

        jobs[job_id]["status"] = "running"

        result = await execute_agentic_task(input_data)

        await payment_instances[job_id].complete_payment(payment_id, result)

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["payment_status"] = "completed"
        jobs[job_id]["result"] = result
    except Exception as e:
        logger.error("Error processing job %s: %s", job_id, e, exc_info=True)
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error"] = str(e)
    finally:
        if job_id in payment_instances:
            payment_instances[job_id].stop_status_monitoring()
            del payment_instances[job_id]


# ---------------------------------------------------------------------------
# MIP-003: GET /status
# ---------------------------------------------------------------------------

@app.get("/status")
async def get_status(job_id: str):
    """Retrieve the current status of a job."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[job_id]

    if job_id in payment_instances:
        try:
            status = await payment_instances[job_id].check_payment_status()
            resolved_status = None
            if isinstance(status, dict):
                resolved_status = status.get("data", {}).get("status")
            if resolved_status:
                job["payment_status"] = resolved_status
            elif not job.get("payment_status"):
                job["payment_status"] = "pending"
        except Exception:
            job["payment_status"] = "unknown"

    return {
        "job_id": job_id,
        "status": job["status"],
        "payment_status": job["payment_status"],
        "result": job.get("result"),
        "scan_summary": job.get("scan_summary"),
        "error": job.get("error"),
    }


# ---------------------------------------------------------------------------
# MIP-003: GET /availability
# ---------------------------------------------------------------------------

@app.get("/availability")
async def check_availability():
    """Check if the server is operational."""
    return {
        "status": "available",
        "uptime": int(time.time() - server_start_time),
        "message": "Aikido Audit Reviewer operational.",
    }


# ---------------------------------------------------------------------------
# MIP-003: GET /input_schema
# ---------------------------------------------------------------------------

@app.get("/input_schema")
async def input_schema():
    """Return the expected input schema for /start_job."""
    return {
        "input_data": [
            {
                "id": "scan_mode",
                "type": "string",
                "name": "Scan Mode",
                "required": False,
                "data": {
                    "description": (
                        "Optional. 'manual' (default) expects aikido_report + source_files. "
                        "'auto' allows omitting aikido_report and the agent will run Aikido CLI "
                        "after payment using source_files or repo_url."
                    ),
                    "placeholder": "manual",
                },
            },
            {
                "id": "repo_url",
                "type": "string",
                "name": "Repository URL",
                "required": False,
                "data": {
                    "description": (
                        "Optional in auto mode. HTTPS git repository URL containing an Aiken project. "
                        "If provided and aikido_report is omitted, the agent clones and scans this repo."
                    ),
                    "placeholder": "https://github.com/org/repo",
                },
            },
            {
                "id": "repo_ref",
                "type": "string",
                "name": "Repository Ref",
                "required": False,
                "data": {
                    "description": "Optional branch/tag to scan in auto mode.",
                    "placeholder": "main",
                },
            },
            {
                "id": "repo_subpath",
                "type": "string",
                "name": "Repository Subpath",
                "required": False,
                "data": {
                    "description": (
                        "Optional relative path inside repo where aiken.toml lives. "
                        "Defaults to repository root."
                    ),
                    "placeholder": "contracts/my-aiken-project",
                },
            },
            {
                "id": "aikido_report",
                "type": "string",
                "name": "Aikido JSON Report",
                "required": False,
                "data": {
                    "description": (
                        "Required in manual mode. Optional in auto mode. "
                        "The full JSON output from an Aikido scan "
                        "(aikido.findings.v1 schema). Run 'aikido . --format json' "
                        "to generate this."
                    ),
                    "placeholder": '{"schema_version": "aikido.findings.v1", ...}',
                },
            },
            {
                "id": "source_files",
                "type": "string",
                "name": "Source Code Files (JSON dict)",
                "required": False,
                "data": {
                    "description": (
                        "Required for manual mode. In auto mode, required only if repo_url is not provided. "
                        "A JSON object mapping file paths to source code "
                        "contents. The reviewer needs your actual Aiken source code to "
                        "verify findings against real contract logic. In auto mode this must "
                        "contain a complete Aiken project including aiken.toml. "
                        'Example: {"aiken.toml": "...", "validators/foo.ak": "validator foo { ... }"}'
                    ),
                    "placeholder": '{"validators/main.ak": "..."}',
                },
            },
        ]
    }


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy"}


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8011"))

    # Validate required config before starting
    missing = []
    if not PAYMENT_SERVICE_URL:
        missing.append("PAYMENT_SERVICE_URL")
    if not PAYMENT_AUTH:
        missing.append("PAYMENT_API_KEY")
    if not os.getenv("AGENT_IDENTIFIER", "").strip():
        missing.append("AGENT_IDENTIFIER")
    if not os.getenv("ANTHROPIC_API_KEY", ""):
        missing.append("ANTHROPIC_API_KEY")

    if missing:
        logger.error(
            "Missing required env vars: %s. "
            "See .env.example and run scripts/register-agent.sh first.",
            ", ".join(missing),
        )
        raise SystemExit(1)

    logger.info("Starting Aikido Audit Reviewer on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
