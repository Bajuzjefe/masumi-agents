"""Dedicated worker entrypoint for Railway Kodosumi service."""

import os

import uvicorn

from kodosumi_app import machine_app

app = machine_app


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8021"))
    uvicorn.run(app, host=host, port=port)
