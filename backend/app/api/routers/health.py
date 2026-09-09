"""Health / meta endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from ...core.config import settings

router = APIRouter(tags=["meta"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "oiltrace-ai", "version": settings.version}


@router.get("/models")
def models() -> dict:
    return {
        "detection": "unet-v1",
        "origin": "xgboost-v1",
        "attribution": "xgboost-v1",
        "anomaly": "isolation-forest-v1",
        "drift": "fallback-lagrangian",
    }
