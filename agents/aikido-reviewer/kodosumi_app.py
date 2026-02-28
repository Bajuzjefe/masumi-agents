"""Kodosumi + machine endpoint runtime for Aikido Audit Reviewer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from agent import process_job_async

logger = logging.getLogger(__name__)

IMPORT_ERROR_DETAIL = None
F = None
ServeAPI = None
Launch = None
InputsError = None

_form_import_errors: list[str] = []
for form_import in (
    "from kodosumi.service.inputs import forms as F",
    "from kodosumi import forms as F",
):
    try:
        exec(form_import, globals())
        break
    except Exception as exc:  # pragma: no cover - import compatibility path
        _form_import_errors.append(repr(exc))

_serve_import_errors: list[str] = []
for serve_import in (
    "from kodosumi.serve import ServeAPI",
    "from kodosumi.core import ServeAPI",
):
    try:
        exec(serve_import, globals())
        break
    except Exception as exc:  # pragma: no cover - import compatibility path
        _serve_import_errors.append(repr(exc))

_core_import_errors: list[str] = []
for core_import in (
    "from kodosumi.core import Launch, InputsError",
    "from kodosumi import Launch, InputsError",
):
    try:
        exec(core_import, globals())
        break
    except Exception as exc:  # pragma: no cover - import compatibility path
        _core_import_errors.append(repr(exc))

if F is None or ServeAPI is None or Launch is None or InputsError is None:
    IMPORT_ERROR_DETAIL = (
        f"forms={'; '.join(_form_import_errors)}; "
        f"serve={'; '.join(_serve_import_errors)}; "
        f"core={'; '.join(_core_import_errors)}"
    )


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


async def run_review_flow(inputs: Dict[str, Any], tracer: Any = None) -> Dict[str, Any]:
    """Kodosumi launched runner for executing review jobs."""
    if tracer is not None and hasattr(tracer, "markdown"):
        await tracer.markdown("### Running Aikido deep review")
    return await run_review_payload({
        "aikido_report": inputs.get("aikido_report", ""),
        "source_files": inputs.get("source_files", "{}"),
        "review_depth": "deep",
    })


_ray_warmup_lock = threading.Lock()
_ray_warmup_started = False
_ray_ready = False
_ray_warmup_error: str | None = None


def _do_ray_init() -> None:
    global _ray_ready, _ray_warmup_error
    import ray

    try:
        if not ray.is_initialized():
            os.environ.setdefault("RAY_USE_MULTIPROCESSING_CPU_COUNT", "1")
            os.environ.setdefault("RAY_DISABLE_DOCKER_CPU_WARNING", "1")
            namespace = os.getenv("KODOSUMI_RAY_NAMESPACE", "kodosumi")
            attach_first = str(
                os.getenv("KODOSUMI_RAY_ATTACH_EXISTING", "true")
            ).strip().lower() in {"1", "true", "yes"}
            attach_required = str(
                os.getenv("KODOSUMI_RAY_ATTACH_REQUIRED", "false")
            ).strip().lower() in {"1", "true", "yes"}
            attach_address = (
                str(os.getenv("KODOSUMI_RAY_ADDRESS", "")).strip()
                or str(os.getenv("RAY_ADDRESS", "")).strip()
                or "auto"
            )
            attach_retries = max(1, int(os.getenv("KODOSUMI_RAY_ATTACH_RETRIES", "10")))
            attach_retry_delay = float(os.getenv("KODOSUMI_RAY_ATTACH_RETRY_DELAY_SECONDS", "1"))
            attached = False
            if attach_first:
                last_exc: Exception | None = None
                for attempt in range(1, attach_retries + 1):
                    try:
                        ray.init(
                            address=attach_address,
                            namespace=namespace,
                            ignore_reinit_error=True,
                            logging_level="WARNING",
                        )
                        attached = True
                        logger.info(
                            "Kodosumi Ray warmup attached to existing cluster "
                            "(address=%s, attempt=%d)",
                            attach_address,
                            attempt,
                        )
                        break
                    except Exception as exc:
                        last_exc = exc
                        logger.warning(
                            "Kodosumi Ray attach failed (address=%s, attempt=%d/%d): %r",
                            attach_address,
                            attempt,
                            attach_retries,
                            exc,
                        )
                        if attempt < attach_retries:
                            time.sleep(attach_retry_delay)
                if not attached and attach_required:
                    raise RuntimeError(
                        "KODOSUMI_RAY_ATTACH_REQUIRED=true and attach did not succeed; "
                        f"last_error={last_exc!r}"
                    )
            if not attached:
                ray.init(
                    namespace=namespace,
                    include_dashboard=False,
                    ignore_reinit_error=True,
                    num_cpus=float(os.getenv("KODOSUMI_RAY_NUM_CPUS", "1")),
                    object_store_memory=int(
                        os.getenv("KODOSUMI_RAY_OBJECT_STORE_MEMORY", "78643200")
                    ),
                    logging_level="WARNING",
                )
                logger.info("Kodosumi Ray warmup started local cluster")
        _ray_ready = True
        _ray_warmup_error = None
        logger.info("Kodosumi Ray warmup complete: %s", ray.available_resources())
    except Exception as exc:
        _ray_ready = False
        _ray_warmup_error = repr(exc)
        logger.warning("Kodosumi Ray warmup failed: %r", exc)


def trigger_ray_warmup() -> None:
    global _ray_warmup_started
    with _ray_warmup_lock:
        if _ray_warmup_started:
            return
        _ray_warmup_started = True
    _do_ray_init()


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


if ServeAPI is not None and F is not None and Launch is not None and InputsError is not None:
    app = ServeAPI()
    input_elements = [
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
        F.Submit("Run Analysis"),
        F.Cancel("Cancel"),
    ]

    try:
        input_form = F.Model(*input_elements)
    except TypeError:
        input_form = F.Model(input_elements)

    # Kodosumi API compatibility: some builds wrap children in an extra list.
    # Flatten once so get_model() always sees element objects with to_dict().
    if hasattr(input_form, "children"):
        normalized_children = []
        for child in getattr(input_form, "children"):
            if isinstance(child, list):
                normalized_children.extend(child)
            else:
                normalized_children.append(child)
        input_form.children = normalized_children

    @app.enter(
        path="/",
        model=input_form,
        summary="Aikido Audit Review",
        description="Run deep smart contract review from provided report and source files.",
        tags=["Aikido", "Security"],
        version="1.0.0",
        author="support@sokosumi.com",
    )
    async def review_handler(request: Request, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Kodosumi form entrypoint."""
        _ = request
        aikido_report = inputs.get("aikido_report", "")
        source_files = inputs.get("source_files", "{}")
        review_depth = "deep"

        if not aikido_report:
            raise InputsError(aikido_report="aikido_report is required")

        try:
            report_data = json.loads(aikido_report) if isinstance(aikido_report, str) else aikido_report
            total = report_data.get("total", 0)
        except (json.JSONDecodeError, AttributeError):
            raise InputsError(aikido_report="Invalid JSON in aikido_report")

        logger.info("Kodosumi form review start: findings=%d depth=%s", total, review_depth)
        if not _ray_ready:
            if _ray_warmup_error:
                raise InputsError(
                    _global_=(
                        "Kodosumi runtime failed to initialize. "
                        f"Please retry. Last error: {_ray_warmup_error}"
                    )
                )
            raise InputsError(
                _global_="Kodosumi runtime is warming up. Please retry in a few seconds."
            )

        def _launch() -> Any:
            return Launch(
                request,
                "kodosumi_app:run_review_flow",
                inputs={
                    "aikido_report": aikido_report,
                    "source_files": source_files,
                    "review_depth": review_depth,
                },
            )

        launch_timeout = float(os.getenv("KODOSUMI_LAUNCH_TIMEOUT_SECONDS", "20"))
        try:
            response = await asyncio.wait_for(asyncio.to_thread(_launch), timeout=launch_timeout)
        except TimeoutError:
            raise InputsError(
                _global_=(
                    "Kodosumi runtime is busy starting resources. "
                    "Please retry in a few seconds."
                )
            )
        except Exception as exc:
            raise InputsError(
                _global_=(f"Kodosumi launch failed: {exc!r}")
            )

        return response
else:
    app = None
    if IMPORT_ERROR_DETAIL:
        logger.warning("Kodosumi import failed: %s", IMPORT_ERROR_DETAIL)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8021"))
    uvicorn.run(machine_app, host=host, port=port)
