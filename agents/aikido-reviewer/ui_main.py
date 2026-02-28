"""Public Kodosumi UI service entrypoint."""

from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from kodosumi_app import app as kodosumi_form_app

ui_app = FastAPI(
    title="Aikido Reviewer Kodosumi UI",
    description="Public Kodosumi UI surface for running review jobs manually.",
    version="1.0.0",
)


@ui_app.get("/health")
async def health() -> dict:
    return {"status": "healthy", "service": "aikido-reviewer-kodosumi-ui"}


if kodosumi_form_app is not None:
    ui_app.mount("/", kodosumi_form_app)
else:
    @ui_app.get("/")
    async def root() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "message": "kodosumi dependency not installed"},
        )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8031"))
    uvicorn.run(ui_app, host=host, port=port)
