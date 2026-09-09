"""OILTRACE-AI FastAPI application.

Run locally (from the backend/ directory):
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routers import (ais, attribution, detection, drift, health, origins,
                          report, store)
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],            # tighten for production deployments
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (health, detection, drift, origins, ais, attribution, report, store):
    app.include_router(r.router, prefix=settings.api_prefix)

logger.info("OILTRACE-AI API ready (prefix=%s)", settings.api_prefix)