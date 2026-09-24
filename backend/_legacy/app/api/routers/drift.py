"""Drift endpoints (backward origin trajectories + forward forecast)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...models.schemas import DriftResult
from ..state import get_analysis

router = APIRouter(tags=["drift"])


@router.get("/events/{event_id}/drift/backward", response_model=DriftResult)
def drift_backward(event_id: str) -> DriftResult:
    try:
        return get_analysis(event_id).drift_backward
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/events/{event_id}/drift/forward", response_model=DriftResult)
def drift_forward(event_id: str) -> DriftResult:
    try:
        return get_analysis(event_id).forward_tracks
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
