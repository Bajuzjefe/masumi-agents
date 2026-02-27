"""Masumi MIP-003 compliant entry point for the Aikido Audit Reviewer agent.

All review requests go through Masumi payment flow. No free/standalone access.
"""

import json
import logging
import os
import time
import uuid
from typing import List

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from masumi.config import Config
from masumi.payment import Payment
from pydantic import BaseModel

from agent import process_job_async

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
                    {"key": "aikido_report", "value": "{...}"},
                    {"key": "source_files", "value": "{...}"},
                    {"key": "review_depth", "value": "standard"},
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

        if "aikido_report" not in input_data_dict:
            raise HTTPException(
                status_code=400,
                detail="'aikido_report' is required in input_data.",
            )

        if "source_files" not in input_data_dict:
            raise HTTPException(
                status_code=400,
                detail=(
                    "'source_files' is required in input_data. "
                    "Provide a JSON object mapping file paths to source code contents "
                    '(e.g. {"validators/main.ak": "validator main { ... }"}). '
                    "Without source code the reviewer cannot verify findings against your actual contract."
                ),
            )

        # Validate both are valid JSON before creating a payment request
        try:
            report_data = json.loads(input_data_dict["aikido_report"])
            if not isinstance(report_data, dict) or "findings" not in report_data:
                raise ValueError("Missing 'findings' key")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"'aikido_report' must be valid Aikido JSON (aikido.findings.v1): {e}",
            )

        try:
            source_data = json.loads(input_data_dict["source_files"])
            if not isinstance(source_data, dict) or len(source_data) == 0:
                raise ValueError("Must contain at least one file entry")
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(
                status_code=400,
                detail=f"'source_files' must be a non-empty JSON object mapping file paths to source code: {e}",
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
        jobs[job_id]["status"] = "running"
        input_data = jobs[job_id]["input_data"]

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
            job["payment_status"] = status.get("data", {}).get("status")
        except Exception:
            job["payment_status"] = "unknown"

    return {
        "job_id": job_id,
        "status": job["status"],
        "payment_status": job["payment_status"],
        "result": job.get("result"),
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
                "id": "aikido_report",
                "type": "string",
                "name": "Aikido JSON Report",
                "required": True,
                "data": {
                    "description": (
                        "REQUIRED. The full JSON output from an Aikido scan "
                        "(aikido.findings.v1 schema). Run 'aikido scan --format json' "
                        "to generate this."
                    ),
                    "placeholder": '{"schema_version": "aikido.findings.v1", ...}',
                },
            },
            {
                "id": "source_files",
                "type": "string",
                "name": "Source Code Files (JSON dict)",
                "required": True,
                "data": {
                    "description": (
                        "REQUIRED. A JSON object mapping file paths to source code "
                        "contents. The reviewer needs your actual Aiken source code to "
                        "verify findings against real contract logic. Without it, "
                        "classifications cannot be accurate. "
                        'Example: {"validators/foo.ak": "validator foo { ... }"}'
                    ),
                    "placeholder": '{"validators/main.ak": "..."}',
                },
            },
            {
                "id": "review_depth",
                "type": "string",
                "name": "Review Depth",
                "data": {
                    "description": (
                        "How deeply to review findings. "
                        "'quick' = heuristic only (instant, no LLM). "
                        "'standard' = LLM review for critical/high findings. "
                        "'deep' = two-pass LLM with cross-finding correlation."
                    ),
                    "placeholder": "standard",
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
