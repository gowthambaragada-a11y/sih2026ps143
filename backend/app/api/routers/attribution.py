"""Attribution ranking endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...models.schemas import AttributionResponse
from ..state import get_analysis

router = APIRouter(tags=["attribution"])


@router.get("/events/{event_id}/attribution", response_model=AttributionResponse)
def attribution(event_id: str) -> AttributionResponse:
    try:
        return get_analysis(event_id).attribution
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
