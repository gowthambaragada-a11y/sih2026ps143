"""Health / meta endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from ...core.config import settings

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict:
    # Lightweight liveness probe — intentionally independent of model/db
    # loading so load balancers can check liveness even during cold starts.
    return {"status": "healthy", "service": "live-pipeline", "version": settings.version}


@router.get("/models")
def models() -> dict:
    return {
        "detection": "unet-v1",
        "origin": "xgboost-v1",
        "attribution": "xgboost-v1",
        "anomaly": "isolation-forest-v1",
        "drift": "fallback-lagrangian",
    }
