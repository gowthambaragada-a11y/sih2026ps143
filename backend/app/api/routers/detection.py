"""Event + detection endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ...models.schemas import DetectionResponse
from ..state import get_analysis, list_events

router = APIRouter(tags=["detection"])


@router.get("/events")
def events() -> dict:
    return {"events": list_events()}


@router.post("/events/{event_id}/analyze")
def analyze(event_id: str, seed: int = 7,
            n_members: int = Query(16, ge=4, le=40),
            refresh: bool = False) -> dict:
    """Run (or return cached) full analysis for an event."""
    res = get_analysis(event_id, refresh=refresh, seed=seed, n_members=n_members)
    return {
        "event_id": res.event_id,
        "status": res.detection.status.value if hasattr(res.detection.status, 'value') else str(res.detection.status),
        "model_versions": res.model_versions,
        "warnings": res.warnings,
    }


@router.get("/events/{event_id}/detection", response_model=DetectionResponse)
def detection(event_id: str) -> DetectionResponse:
    try:
        return get_analysis(event_id).detection
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
