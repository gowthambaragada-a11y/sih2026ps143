"""OILTRACE-AI FastAPI application.

Run locally (from the backend/ directory):
    uvicorn app.main:app --reload --port 8000

Cloud (Render/Railway/Fly.io): the platform injects PORT and runs the web
command in the Dockerfile / Procfile; the app binds 0.0.0.0 and honours PORT.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routers import (ais, attribution, detect, detection, drift, health,
                          origins, report, store)
from .core.config import settings
from .core.logger import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

app = FastAPI(
    title="OILTRACE-AI",
    version=settings.version,
    description=(
        "Automated satellite-based oil spill origin and vessel attribution. "
        "Dashboard + API for detection, drift reconstruction, origin "
        "probability and evidence-backed vessel ranking."
    ),
)

# Comma-separated allow-list, overridable via CORS_ORIGINS. The GitHub Pages
# dashboard and local Vite dev server are allowed explicitly.
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "https://gowthambaragada-a11y.github.io,"
        "http://localhost:5173,"
        "http://localhost:3000,"
        "http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (health, detect, detection, drift, origins, ais, attribution, report, store):
    app.include_router(r.router, prefix=settings.api_prefix)
# The meta/health router is also available unprefixed (/health, /models).
app.include_router(health.router)

logger.info("OILTRACE-AI API ready (prefix=%s) cors=%s", settings.api_prefix, CORS_ORIGINS)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port)